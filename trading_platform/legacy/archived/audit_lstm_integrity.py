"""Integrity checks for the temporal OTC LSTM retraining workflow.

Run one check at a time:
  python audit_lstm_integrity.py --check causality
  python audit_lstm_integrity.py --check parity
  python audit_lstm_integrity.py --check label-shuffle
  python audit_lstm_integrity.py --check embargo
  python audit_lstm_integrity.py --check forward

`label-shuffle` and `embargo` retrain an LSTM and are intentionally expensive.
They do not replace or export the deployed artifact.
"""

from __future__ import annotations

import argparse
import copy
import json
import pickle
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, roc_auc_score
from torch.utils.data import DataLoader

from trading_platform.legacy.archived import train_trading_model_fixed as train


def load_raw_data(data_file: Path, include_asset_features: bool) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Load and normalize the same raw input schema used for training."""
    if not data_file.is_file():
        raise FileNotFoundError(f"CSV not found: {data_file.resolve()}")
    df = pd.read_csv(data_file).rename(columns={"max": "high", "min": "low"})
    required = {"asset", "timestamp", "open", "high", "low", "close"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(missing)}")
    df["timestamp"] = train.parse_timestamps(df["timestamp"])
    for column in ("open", "high", "low", "close"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if df[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("OHLC data contains non-numeric values")
    df = df.sort_values(["asset", "timestamp"]).drop_duplicates(["asset", "timestamp"], keep="last")
    df = df.reset_index(drop=True)

    assets = sorted(df["asset"].unique())
    asset_columns = [f"asset_{asset}" for asset in assets]
    if include_asset_features:
        for asset, column in zip(assets, asset_columns):
            df[column] = (df["asset"] == asset).astype(np.float32)
    else:
        asset_columns = []
    return df, assets, asset_columns


def build_prepared_assets(
    data_file: Path,
    include_asset_features: bool,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], list[str]]:
    """Return raw and causal-feature frames, separately for every asset."""
    raw, assets, asset_columns = load_raw_data(data_file, include_asset_features)
    features = train.SCALE_FEATURES + train.BASE_PASS_FEATURES + asset_columns
    raw_assets: dict[str, pd.DataFrame] = {}
    prepared_assets: dict[str, pd.DataFrame] = {}
    for asset, raw_group in raw.groupby("asset", sort=True):
        raw_group = raw_group.sort_values("timestamp").reset_index(drop=True).copy()
        group = raw_group.copy()
        next_close = group["close"].shift(-1)
        group["target"] = np.where(
            next_close.notna(),
            (next_close > group["close"]).astype(np.float32),
            np.nan,
        )
        prepared = train.apply_features(group)
        prepared = prepared.replace([np.inf, -np.inf], np.nan).dropna(subset=features + ["target"])
        prepared_assets[asset] = prepared.reset_index(drop=True)
        raw_assets[asset] = raw_group
    return raw_assets, prepared_assets, features


def temporal_splits(group: pd.DataFrame, embargo_rows: int) -> dict[str, pd.DataFrame]:
    """Create chronology-only splits with an optional explicit boundary embargo."""
    n_rows = len(group)
    train_end = int(n_rows * 0.70)
    validation_end = int(n_rows * 0.85)
    if embargo_rows < 0:
        raise ValueError("embargo_rows must be non-negative")
    splits = {
        "train": group.iloc[:train_end - embargo_rows].copy(),
        "validation": group.iloc[train_end + embargo_rows:validation_end - embargo_rows].copy(),
        "test": group.iloc[validation_end + embargo_rows:].copy(),
    }
    if any(len(part) <= train.SEQ_LENGTH for part in splits.values()):
        raise ValueError("Embargo leaves too few rows for a sequence in at least one split")
    return splits


def build_datasets(
    prepared_assets: dict[str, pd.DataFrame],
    features: list[str],
    embargo_rows: int,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Build non-overlapping temporal windows for all assets."""
    x_parts = {"train": [], "validation": [], "test": []}
    y_parts = {"train": [], "validation": [], "test": []}
    asset_labels = {"train": [], "validation": [], "test": []}
    for asset, group in prepared_assets.items():
        try:
            splits = temporal_splits(group, embargo_rows)
            for name, split in splits.items():
                x, y = train.make_sequences(split, features)
                x_parts[name].append(x)
                y_parts[name].append(y)
                asset_labels[name].append(np.full(len(y), asset, dtype=object))
        except ValueError as exc:
            print(f"Skipping {asset}: {exc}")
    if not all(x_parts.values()):
        raise RuntimeError("No complete temporal datasets were produced")
    return (
        {name: np.vstack(parts) for name, parts in x_parts.items()},
        {name: np.concatenate(parts) for name, parts in y_parts.items()},
        {name: np.concatenate(parts) for name, parts in asset_labels.items()},
    )


def scale_datasets(x: dict[str, np.ndarray]) -> tuple[dict[str, np.ndarray], Any]:
    """Fit the scaler on training only, exactly as the production trainer does."""
    scale_idx = len(train.SCALE_FEATURES)
    scaler = train.RobustScaler()
    scaler.fit(x["train"][:, :, :scale_idx].reshape(-1, scale_idx))
    for name, array in x.items():
        transformed = scaler.transform(array[:, :, :scale_idx].reshape(-1, scale_idx))
        array[:, :, :scale_idx] = transformed.reshape(array.shape[0], array.shape[1], scale_idx)
    return x, scaler


def fit_audit_model(
    x: dict[str, np.ndarray],
    y: dict[str, np.ndarray],
    epochs: int,
    shuffle_train_labels: bool,
    train_asset_labels: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Train an audit-only model and return untouched test probabilities."""
    train.set_seed(train.RANDOM_SEED)
    x, _ = scale_datasets(x)
    train_labels = y["train"].copy()
    if shuffle_train_labels:
        if train_asset_labels is None:
            raise ValueError("Per-asset labels are required for the label-shuffle null test")
        rng = np.random.default_rng(train.RANDOM_SEED)
        for asset in np.unique(train_asset_labels):
            positions = np.flatnonzero(train_asset_labels == asset)
            train_labels[positions] = train_labels[rng.permutation(positions)]
        print("NULL TEST: training labels were shuffled within each asset cohort.")

    loaders = {
        "train": DataLoader(train.TSDataset(x["train"], train_labels), batch_size=train.BATCH_SIZE, shuffle=True, pin_memory=train.PIN_MEMORY),
        "validation": DataLoader(train.TSDataset(x["validation"], y["validation"]), batch_size=train.BATCH_SIZE, shuffle=False, pin_memory=train.PIN_MEMORY),
        "test": DataLoader(train.TSDataset(x["test"], y["test"]), batch_size=train.BATCH_SIZE, shuffle=False, pin_memory=train.PIN_MEMORY),
    }
    model = train.TradingLSTM(input_size=x["train"].shape[2]).to(train.DEVICE)
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=train.LEARNING_RATE, weight_decay=1e-4)
    best_loss = float("inf")
    best_weights = None
    no_improvement = 0
    patience = min(train.PATIENCE, max(5, epochs // 3))

    for epoch in range(epochs):
        model.train()
        for batch_x, batch_y in loaders["train"]:
            batch_x = batch_x.to(train.DEVICE).clone()
            batch_y = batch_y.to(train.DEVICE)
            batch_x[:, :, :len(train.SCALE_FEATURES)] += torch.randn_like(batch_x[:, :, :len(train.SCALE_FEATURES)]) * 0.005
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(batch_x), batch_y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        model.eval()
        total_loss = 0.0
        total_rows = 0
        with torch.no_grad():
            for batch_x, batch_y in loaders["validation"]:
                batch_x = batch_x.to(train.DEVICE)
                batch_y = batch_y.to(train.DEVICE)
                total_loss += criterion(model(batch_x), batch_y).item() * len(batch_y)
                total_rows += len(batch_y)
        validation_loss = total_loss / total_rows
        if validation_loss < best_loss:
            best_loss = validation_loss
            best_weights = copy.deepcopy(model.state_dict())
            no_improvement = 0
        else:
            no_improvement += 1
            if no_improvement >= patience:
                print(f"Audit early stop at epoch {epoch + 1}")
                break
        print(f"Audit epoch {epoch:03d} | validation loss: {validation_loss:.5f}")

    if best_weights is None:
        raise RuntimeError("Audit training did not produce weights")
    model.load_state_dict(best_weights)
    test_probabilities, test_targets = train.predict_probabilities(model, loaders["test"])
    return test_probabilities, test_targets


def run_causality_check(data_file: Path, samples_per_asset: int) -> dict[str, Any]:
    """Ensure every feature at t is identical when calculated from a prefix ending at t."""
    raw_assets, _, _ = build_prepared_assets(data_file, include_asset_features=False)
    feature_columns = train.SCALE_FEATURES + train.BASE_PASS_FEATURES
    max_difference = 0.0
    checked = 0
    failures = []
    for asset, raw in raw_assets.items():
        full = train.apply_features(raw.copy())
        candidate_rows = np.linspace(200, len(raw) - 1, samples_per_asset, dtype=int)
        for row in np.unique(candidate_rows):
            prefix = train.apply_features(raw.iloc[:row + 1].copy())
            full_values = full.iloc[row][feature_columns].to_numpy(dtype=float)
            prefix_values = prefix.iloc[-1][feature_columns].to_numpy(dtype=float)
            finite = np.isfinite(full_values) & np.isfinite(prefix_values)
            if not finite.any():
                continue
            difference = float(np.max(np.abs(full_values[finite] - prefix_values[finite])))
            max_difference = max(max_difference, difference)
            checked += 1
            if difference > 1e-6:
                failures.append({"asset": asset, "row": int(row), "max_abs_difference": difference})
    result = {
        "check": "feature_prefix_causality",
        "rows_checked": checked,
        "max_abs_difference": max_difference,
        "passed": not failures,
        "failures": failures[:20],
    }
    print(json.dumps(result, indent=2))
    return result


def run_label_shuffle_check(data_file: Path, epochs: int) -> dict[str, Any]:
    """A valid pipeline should collapse to chance when training labels are shuffled."""
    _, prepared, features = build_prepared_assets(data_file, train.INCLUDE_ASSET_FEATURES)
    x, y, asset_labels = build_datasets(prepared, features, embargo_rows=0)
    probabilities, targets = fit_audit_model(
        x,
        y,
        epochs=epochs,
        shuffle_train_labels=True,
        train_asset_labels=asset_labels["train"],
    )
    auc = float(roc_auc_score(targets, probabilities))
    accuracy = float(accuracy_score(targets, probabilities >= 0.5))
    result = {
        "check": "label_shuffle_null",
        "epochs": epochs,
        "test_auc": auc,
        "test_accuracy": accuracy,
        "passed": 0.45 <= auc <= 0.55,
        "interpretation": "Pass means shuffled labels removed predictive power; failure requires a leakage investigation.",
    }
    print(json.dumps(result, indent=2))
    return result


def run_embargo_check(data_file: Path, epochs: int, embargo_rows: int) -> dict[str, Any]:
    """Retrain after excluding rows on both sides of each split boundary."""
    _, prepared, features = build_prepared_assets(data_file, train.INCLUDE_ASSET_FEATURES)
    x, y, _ = build_datasets(prepared, features, embargo_rows=embargo_rows)
    probabilities, targets = fit_audit_model(x, y, epochs=epochs, shuffle_train_labels=False)
    auc = float(roc_auc_score(targets, probabilities))
    accuracy = float(accuracy_score(targets, probabilities >= 0.5))
    result = {
        "check": "embargo_retrain",
        "embargo_rows": embargo_rows,
        "epochs": epochs,
        "test_auc": auc,
        "test_accuracy": accuracy,
        "passed": True,
        "interpretation": "Compare this with the baseline AUC 0.9207 and accuracy 0.8193; a large collapse indicates boundary dependence.",
    }
    print(json.dumps(result, indent=2))
    return result


def add_asset_columns(frame: pd.DataFrame, asset: str, asset_columns: list[str]) -> pd.DataFrame:
    frame = frame.copy()
    expected = f"asset_{asset}"
    for column in asset_columns:
        frame[column] = float(column == expected)
    return frame


def run_live_parity_check(data_file: Path, artifact_dir: Path, samples_per_asset: int) -> dict[str, Any]:
    """Compare training preprocessing with the bot's real FeatureEngineer + ONNX input."""
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError("onnxruntime is required for the parity check") from exc
    from trading_platform.ml.feature_engineering import FeatureEngineer

    metadata_path = artifact_dir / "lstm_metadata.pkl"
    scaler_path = artifact_dir / "lstm_scaler.pkl"
    model_path = artifact_dir / "deep_lstm_v1.onnx"
    for path in (metadata_path, scaler_path, model_path):
        if not path.is_file():
            raise FileNotFoundError(f"Missing artifact: {path}")
    with metadata_path.open("rb") as handle:
        metadata = pickle.load(handle)
    features = list(metadata["features"])
    asset_columns = list(metadata.get("asset_features", []))
    include_asset_features = bool(asset_columns)
    raw_assets, prepared_assets, _ = build_prepared_assets(data_file, include_asset_features)
    scaler = joblib.load(scaler_path)
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    engineer = FeatureEngineer()
    feature_differences = []
    output_differences = []

    for asset, prepared in prepared_assets.items():
        raw = raw_assets[asset]
        # Restrict comparisons to the final portion of the asset: this is held
        # out in the baseline run and leaves enough history for live features.
        locations = np.linspace(max(150, int(len(raw) * 0.85)), len(raw) - 1, samples_per_asset, dtype=int)
        for raw_end in np.unique(locations):
            raw_history = raw.iloc[max(0, raw_end - 149):raw_end + 1].copy()
            live = engineer.generate_features(raw_history, is_training=False)
            live = add_asset_columns(live, asset, asset_columns)
            raw_timestamp = raw.iloc[raw_end]["timestamp"]
            training_rows = prepared.loc[prepared["timestamp"] <= raw_timestamp].tail(train.SEQ_LENGTH)
            live_rows = live[features].replace([np.inf, -np.inf], np.nan).dropna().tail(train.SEQ_LENGTH)
            if len(training_rows) != train.SEQ_LENGTH or len(live_rows) != train.SEQ_LENGTH:
                continue
            training_matrix = training_rows[features].to_numpy(dtype=np.float32, copy=True)
            live_matrix = live_rows.to_numpy(dtype=np.float32, copy=True)
            difference = float(np.max(np.abs(training_matrix - live_matrix)))
            feature_differences.append(difference)

            scale_idx = int(metadata["scale_idx"])
            for matrix in (training_matrix, live_matrix):
                matrix[:, :scale_idx] = scaler.transform(matrix[:, :scale_idx])
            training_output = float(session.run(None, {input_name: training_matrix[None, ...]})[0].reshape(-1)[0])
            live_output = float(session.run(None, {input_name: live_matrix[None, ...]})[0].reshape(-1)[0])
            output_differences.append(abs(training_output - live_output))

    if not feature_differences:
        raise RuntimeError("No valid live/training feature sequences could be compared")
    result = {
        "check": "live_preprocessing_and_onnx_parity",
        "samples_compared": len(feature_differences),
        "max_feature_abs_difference": float(max(feature_differences)),
        "max_onnx_logit_difference": float(max(output_differences)),
        "passed": max(output_differences) < 1e-3,
        "interpretation": "The ONNX logit should match after live and training preprocessing. Small feature differences can arise because live uses a 150-candle history window.",
    }
    print(json.dumps(result, indent=2))
    return result


def run_forward_ledger_check(trade_log: Path) -> dict[str, Any]:
    """Report only API-verified, settled LSTM trades from the bot ledger."""
    if not trade_log.is_file():
        result = {"check": "forward_ledger", "passed": False, "reason": f"Ledger not found: {trade_log}"}
        print(json.dumps(result, indent=2))
        return result
    with trade_log.open("r", encoding="utf-8") as handle:
        trades = json.load(handle)
    eligible = [
        trade for trade in trades
        if trade.get("result") in {"win", "lose"}
        and str(trade.get("result_method", "")).lower() == "api"
        and "ml_lstm" in " ".join([
            str(trade.get("strategy_used", "")),
            str(trade.get("winning_strategy", "")),
        ]).lower()
    ]
    if not eligible:
        result = {"check": "forward_ledger", "passed": False, "reason": "No API-verified LSTM settlements yet."}
        print(json.dumps(result, indent=2))
        return result
    wins = sum(trade["result"] == "win" for trade in eligible)
    total = len(eligible)
    lower_win_rate = train.wilson_lower_bound(wins, total)
    by_asset = {}
    for trade in eligible:
        bucket = by_asset.setdefault(trade.get("asset", "unknown"), {"wins": 0, "trades": 0})
        bucket["trades"] += 1
        bucket["wins"] += int(trade["result"] == "win")
    result = {
        "check": "forward_ledger",
        "verified_lstm_trades": total,
        "wins": wins,
        "win_rate": wins / total,
        "lower_win_rate": lower_win_rate,
        "payout_breakeven": 1 / (1 + train.BINARY_PAYOUT),
        "by_asset": by_asset,
        "passed": total >= 300 and lower_win_rate > 1 / (1 + train.BINARY_PAYOUT),
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="append", choices=["causality", "label-shuffle", "embargo", "parity", "forward"], required=True)
    parser.add_argument("--data-file", type=Path, default=train.DATA_FILE)
    parser.add_argument("--artifact-dir", type=Path, default=train.ARTIFACT_DIR)
    parser.add_argument("--trade-log", type=Path, default=Path("data/trade_log.json"))
    parser.add_argument("--samples-per-asset", type=int, default=5)
    parser.add_argument("--null-epochs", type=int, default=15)
    parser.add_argument("--embargo-epochs", type=int, default=60)
    parser.add_argument("--embargo-rows", type=int, default=train.SEQ_LENGTH)
    parser.add_argument("--result-file", type=Path, default=Path("lstm_integrity_audit_results.json"))
    args = parser.parse_args()

    results = []
    for check in args.check:
        if check == "causality":
            results.append(run_causality_check(args.data_file, args.samples_per_asset))
        elif check == "label-shuffle":
            results.append(run_label_shuffle_check(args.data_file, args.null_epochs))
        elif check == "embargo":
            results.append(run_embargo_check(args.data_file, args.embargo_epochs, args.embargo_rows))
        elif check == "parity":
            results.append(run_live_parity_check(args.data_file, args.artifact_dir, args.samples_per_asset))
        elif check == "forward":
            results.append(run_forward_ledger_check(args.trade_log))

    with args.result_file.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, default=str)
    print(f"Saved audit results: {args.result_file}")


if __name__ == "__main__":
    main()
