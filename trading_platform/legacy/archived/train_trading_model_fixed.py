"""Train the OTC LSTM with causally aligned labels and purged temporal splits.

This script is compatible with the live FeatureEngineer and MLLSTMStrategy:
it preserves the 90 x 32 (when asset features are enabled) feature schema and
exports logits, a RobustScaler, and metadata.

The important differences from the earlier script are:
1. A window ending at candle t is paired with the label for t -> t+1.
2. Each asset is split by time before windows are generated. Windows never
   overlap between train, validation, and test sets.
3. Trade thresholds are chosen on validation data using payout-aware,
   confidence-bound expectancy rather than all-row macro F1.
"""

from __future__ import annotations

import copy
import gc
import pickle
import random
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pandas_ta as ta
import torch
import torch.nn as nn
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
from sklearn.preprocessing import RobustScaler
from torch.utils.data import DataLoader, Dataset


# =============================================================================
# 1. EXPERIMENT CONFIGURATION
# =============================================================================
DATA_FILE = Path("candles_export.csv")
ARTIFACT_DIR = Path("lstm_temporal_v2_artifacts")

SEQ_LENGTH = 90
BATCH_SIZE = 1024
EPOCHS = 100
LEARNING_RATE = 5e-4
PATIENCE = 20
RANDOM_SEED = 42

# Keep this equal to the setting used by the deployed model unless you intend
# to retrain and deploy a model with a different schema. True produces the
# same 32 columns used by the current artifact (17 base + 15 asset one-hots).
INCLUDE_ASSET_FEATURES = True
SINGLE_ASSET_FILTER: str | None = None  # Example: "AUDUSD-OTC"

# Set this to the broker payout you will actually receive, as a decimal.
# An 80% payout needs a win rate above 55.56% just to break even.
BINARY_PAYOUT = 0.80
MIN_ACTIONABLE_VALIDATION_TRADES = 1_000
THRESHOLD_GRID = np.round(np.arange(0.50, 0.91, 0.01), 2)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
PIN_MEMORY = DEVICE.type == "cuda"

SCALE_FEATURES = [
    "open_pct", "high_pct", "low_pct", "close_pct", "dist_ema_20",
    "atr_pct", "macd_hist", "roc_10",
]
BASE_PASS_FEATURES = [
    "rsi_14", "body_ratio", "upper_wick_ratio", "lower_wick_ratio",
    "close_position", "stoch_k", "bb_percent_b", "hour_of_day",
    "day_of_week",
]


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def parse_timestamps(values: pd.Series) -> pd.Series:
    """Parse common epoch units or ISO timestamps without silently guessing."""
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        maximum = float(numeric.abs().max())
        unit = "ns" if maximum >= 1e17 else "us" if maximum >= 1e14 else "ms" if maximum >= 1e11 else "s"
        parsed = pd.to_datetime(numeric, unit=unit, utc=True)
    else:
        parsed = pd.to_datetime(values, utc=True, errors="coerce")
    if parsed.isna().any():
        raise ValueError("timestamp contains values that cannot be parsed")
    return parsed


def apply_features(group: pd.DataFrame) -> pd.DataFrame:
    """Generate the exact causal feature columns used by live inference."""
    group = group.copy()
    group["ema_20"] = ta.ema(group["close"], length=20)
    group["dist_ema_20"] = (group["close"] - group["ema_20"]) / group["ema_20"]
    group["rsi_14"] = ta.rsi(group["close"], length=14) / 100.0
    group["atr_14"] = ta.atr(group["high"], group["low"], group["close"], length=14)
    group["atr_pct"] = group["atr_14"] / group["close"]
    group["roc_10"] = group["close"].pct_change(periods=10) * 100.0
    group["hour_of_day"] = group["timestamp"].dt.hour / 24.0
    group["day_of_week"] = group["timestamp"].dt.dayofweek / 7.0

    macd_df = ta.macd(group["close"], fast=12, slow=26, signal=9)
    stoch_df = ta.stoch(group["high"], group["low"], group["close"], k=14, d=3)
    bbands_df = ta.bbands(group["close"], length=20, std=2)
    if macd_df is None or stoch_df is None or bbands_df is None:
        raise ValueError("Not enough rows to calculate pandas-ta indicators")

    # These positional selections intentionally match the deployed feature
    # engine and the original training script.
    group["macd_hist"] = macd_df.iloc[:, 1]
    group["stoch_k"] = stoch_df.iloc[:, 0] / 100.0
    group["bb_percent_b"] = bbands_df.iloc[:, 4]

    group["candle_range"] = group["high"] - group["low"] + 1e-8
    group["body_size"] = (group["close"] - group["open"]).abs()
    group["body_ratio"] = group["body_size"] / group["candle_range"]
    group["upper_wick"] = np.where(
        group["close"] >= group["open"],
        group["high"] - group["close"],
        group["high"] - group["open"],
    )
    group["lower_wick"] = np.where(
        group["close"] >= group["open"],
        group["open"] - group["low"],
        group["close"] - group["low"],
    )
    group["upper_wick_ratio"] = group["upper_wick"] / group["candle_range"]
    group["lower_wick_ratio"] = group["lower_wick"] / group["candle_range"]
    group["close_position"] = (group["close"] - group["low"]) / group["candle_range"]

    for column in ("open", "high", "low", "close"):
        group[f"{column}_pct"] = group[column].pct_change()

    return group


def make_sequences(split: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Create windows wholly contained in one temporal split.

    `target[t]` is whether close[t + 1] > close[t]. Therefore a window ending
    at t must receive target[t], not target[t + 1]. The last possible window
    has no next-candle label and is removed.
    """
    if len(split) <= SEQ_LENGTH:
        raise ValueError(f"Need > {SEQ_LENGTH} usable rows; got {len(split)}")

    x_rows = split[features].to_numpy(dtype=np.float32, copy=True)
    y_rows = split["target"].to_numpy(dtype=np.float32, copy=True)

    windows = sliding_window_view(x_rows, window_shape=SEQ_LENGTH, axis=0)
    windows = np.moveaxis(windows, -1, 1)

    x = np.ascontiguousarray(windows[:-1])
    y = y_rows[SEQ_LENGTH - 1:-1].copy()
    if len(x) != len(y):
        raise RuntimeError(f"Sequence/label mismatch: {len(x)} windows vs {len(y)} labels")
    return x, y


def wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    """Conservative 95% lower confidence bound for a binary win rate."""
    if total <= 0:
        return 0.0
    p = wins / total
    denominator = 1.0 + z * z / total
    centre = p + z * z / (2.0 * total)
    spread = z * np.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return float((centre - spread) / denominator)


def trade_metrics(prob_call: np.ndarray, target: np.ndarray, threshold: float) -> dict[str, float]:
    """Evaluate only the two-sided high-confidence trades used by the bot."""
    probability = np.asarray(prob_call, dtype=float).reshape(-1)
    actual = np.asarray(target, dtype=int).reshape(-1)
    selected = (probability >= threshold) | (probability <= 1.0 - threshold)
    n = int(selected.sum())
    if n == 0:
        return {"threshold": threshold, "trades": 0, "coverage": 0.0, "win_rate": np.nan,
                "lower_win_rate": np.nan, "expectancy": np.nan, "lower_expectancy": np.nan}

    predicted = (probability[selected] >= 0.5).astype(int)
    wins = int((predicted == actual[selected]).sum())
    win_rate = wins / n
    lower_win_rate = wilson_lower_bound(wins, n)
    return {
        "threshold": float(threshold),
        "trades": n,
        "coverage": n / len(actual),
        "win_rate": win_rate,
        "lower_win_rate": lower_win_rate,
        "expectancy": win_rate * BINARY_PAYOUT - (1.0 - win_rate),
        "lower_expectancy": lower_win_rate * BINARY_PAYOUT - (1.0 - lower_win_rate),
    }


def choose_threshold(validation_probabilities: np.ndarray, validation_targets: np.ndarray) -> tuple[float, pd.DataFrame]:
    rows = [trade_metrics(validation_probabilities, validation_targets, threshold) for threshold in THRESHOLD_GRID]
    table = pd.DataFrame(rows)
    eligible = table[table["trades"] >= MIN_ACTIONABLE_VALIDATION_TRADES].copy()
    if eligible.empty:
        raise RuntimeError(
            "No threshold produced the required validation trade count. "
            "Do not lower the requirement blindly; collect more history instead."
        )

    best = eligible.sort_values(
        ["lower_expectancy", "trades"], ascending=[False, False]
    ).iloc[0]
    return float(best["threshold"]), table


class TSDataset(Dataset):
    def __init__(self, x: np.ndarray, y: np.ndarray):
        self.x = torch.from_numpy(x)
        self.y = torch.from_numpy(y).unsqueeze(1)

    def __len__(self) -> int:
        return len(self.x)

    def __getitem__(self, index: int):
        return self.x[index], self.y[index]


class TradingLSTM(nn.Module):
    def __init__(self, input_size: int, hidden_size: int = 64, num_layers: int = 2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size, hidden_size, num_layers, batch_first=True, dropout=0.1
        )
        self.fc1 = nn.Linear(hidden_size, 32)
        self.dropout = nn.Dropout(0.1)
        self.fc2 = nn.Linear(32, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output, _ = self.lstm(x)
        output = self.fc1(output[:, -1, :])
        output = torch.relu(output)
        return self.fc2(self.dropout(output))


def predict_probabilities(model: nn.Module, loader: DataLoader) -> tuple[np.ndarray, np.ndarray]:
    probabilities, targets = [], []
    model.eval()
    with torch.no_grad():
        for batch_x, batch_y in loader:
            logits = model(batch_x.to(DEVICE))
            probabilities.append(torch.sigmoid(logits).cpu().numpy().reshape(-1))
            targets.append(batch_y.numpy().reshape(-1))
    return np.concatenate(probabilities), np.concatenate(targets)


def main() -> None:
    set_seed(RANDOM_SEED)
    print(f"Hardware: {DEVICE.type.upper()}")
    print(f"Asset identity features: {'INCLUDED' if INCLUDE_ASSET_FEATURES else 'EXCLUDED'}")
    print(f"Payout assumption: {BINARY_PAYOUT:.0%}; breakeven: {1 / (1 + BINARY_PAYOUT):.2%}")

    if not DATA_FILE.is_file():
        raise FileNotFoundError(f"CSV not found: {DATA_FILE.resolve()}")
    df = pd.read_csv(DATA_FILE).copy()
    df = df.rename(columns={"max": "high", "min": "low"})
    required = {"asset", "timestamp", "open", "high", "low", "close"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

    if SINGLE_ASSET_FILTER is not None:
        df = df.loc[df["asset"] == SINGLE_ASSET_FILTER].copy()
    if df.empty:
        raise ValueError("No rows remain after applying the asset filter")

    df["timestamp"] = parse_timestamps(df["timestamp"])
    for column in ("open", "high", "low", "close"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if df[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("OHLC columns contain non-numeric values")
    df = df.sort_values(["asset", "timestamp"]).drop_duplicates(["asset", "timestamp"], keep="last")
    df = df.reset_index(drop=True)

    assets = sorted(df["asset"].unique())
    asset_features = [f"asset_{asset}" for asset in assets]
    if INCLUDE_ASSET_FEATURES:
        for asset, column in zip(assets, asset_features):
            df[column] = (df["asset"] == asset).astype(np.float32)
    else:
        asset_features = []
    features = SCALE_FEATURES + BASE_PASS_FEATURES + asset_features
    print(f"Assets: {len(assets)} | feature count: {len(features)}")

    split_x = {"train": [], "validation": [], "test": []}
    split_y = {"train": [], "validation": [], "test": []}
    test_assets = []
    split_calendar = []

    for asset, raw_group in df.groupby("asset", sort=True):
        group = raw_group.sort_values("timestamp").copy()
        next_close = group["close"].shift(-1)
        group["target"] = np.where(
            next_close.notna(), (next_close > group["close"]).astype(np.float32), np.nan
        )
        group = apply_features(group)
        group = group.replace([np.inf, -np.inf], np.nan).dropna(subset=features + ["target"])
        group = group.reset_index(drop=True)

        n_rows = len(group)
        train_end = int(n_rows * 0.70)
        validation_end = int(n_rows * 0.85)
        raw_splits = {
            "train": group.iloc[:train_end].copy(),
            "validation": group.iloc[train_end:validation_end].copy(),
            "test": group.iloc[validation_end:].copy(),
        }
        if any(len(part) <= SEQ_LENGTH for part in raw_splits.values()):
            print(f"Skipping {asset}: a temporal split has <= {SEQ_LENGTH} usable rows")
            continue

        # Windows are created separately per split. This purges the 89 shared
        # candles that existed at the old train/validation/test boundaries.
        try:
            for split_name, split_frame in raw_splits.items():
                x_asset, y_asset = make_sequences(split_frame, features)
                split_x[split_name].append(x_asset)
                split_y[split_name].append(y_asset)
                if split_name == "test":
                    test_assets.append(np.full(len(y_asset), asset, dtype=object))
        except ValueError as exc:
            print(f"Skipping {asset}: {exc}")
            continue

        split_calendar.append({
            "asset": asset,
            "train_end": raw_splits["train"]["timestamp"].iloc[-1],
            "validation_start": raw_splits["validation"]["timestamp"].iloc[0],
            "test_start": raw_splits["test"]["timestamp"].iloc[0],
            "test_end": raw_splits["test"]["timestamp"].iloc[-1],
        })
        print(
            f"{asset}: usable={n_rows:,}, train={len(split_y['train'][-1]):,}, "
            f"validation={len(split_y['validation'][-1]):,}, test={len(split_y['test'][-1]):,}"
        )
        del group, raw_splits
        gc.collect()

    if not all(split_x.values()):
        raise RuntimeError("No asset produced train, validation, and test sequences")

    x_train = np.vstack(split_x["train"])
    y_train = np.concatenate(split_y["train"])
    x_validation = np.vstack(split_x["validation"])
    y_validation = np.concatenate(split_y["validation"])
    x_test = np.vstack(split_x["test"])
    y_test = np.concatenate(split_y["test"])
    test_asset_labels = np.concatenate(test_assets)
    del split_x, split_y, df
    gc.collect()

    print("\nTemporal split calendar (first rows):")
    print(pd.DataFrame(split_calendar).sort_values("test_start").head(20).to_string(index=False))
    print(
        f"\nSequence counts: train={len(y_train):,}, validation={len(y_validation):,}, "
        f"test={len(y_test):,}"
    )
    print(f"Train target-up rate: {y_train.mean():.3%}")
    print(f"Validation target-up rate: {y_validation.mean():.3%}")
    print(f"Test target-up rate: {y_test.mean():.3%}")

    # Fit only on the training split. Validation and test never influence the
    # scaler's median or interquartile range.
    scale_idx = len(SCALE_FEATURES)
    scaler = RobustScaler()
    scaler.fit(x_train[:, :, :scale_idx].reshape(-1, scale_idx))

    def scale_in_place(x: np.ndarray) -> np.ndarray:
        scaled = scaler.transform(x[:, :, :scale_idx].reshape(-1, scale_idx))
        x[:, :, :scale_idx] = scaled.reshape(x.shape[0], x.shape[1], scale_idx)
        return x

    x_train = scale_in_place(x_train)
    x_validation = scale_in_place(x_validation)
    x_test = scale_in_place(x_test)

    train_loader = DataLoader(TSDataset(x_train, y_train), batch_size=BATCH_SIZE, shuffle=True, pin_memory=PIN_MEMORY)
    validation_loader = DataLoader(TSDataset(x_validation, y_validation), batch_size=BATCH_SIZE, shuffle=False, pin_memory=PIN_MEMORY)
    test_loader = DataLoader(TSDataset(x_test, y_test), batch_size=BATCH_SIZE, shuffle=False, pin_memory=PIN_MEMORY)

    model = TradingLSTM(input_size=len(features)).to(DEVICE)
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)

    print("\n--- Starting LSTM Training ---")
    best_validation_loss = float("inf")
    best_weights = None
    no_improvement = 0
    for epoch in range(EPOCHS):
        model.train()
        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(DEVICE)
            batch_y = batch_y.to(DEVICE)
            # Apply noise to a copy so the underlying dataset is unchanged.
            batch_x = batch_x.clone()
            batch_x[:, :, :scale_idx] += torch.randn_like(batch_x[:, :, :scale_idx]) * 0.005
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(batch_x), batch_y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        model.eval()
        validation_loss_sum = 0.0
        validation_items = 0
        with torch.no_grad():
            for batch_x, batch_y in validation_loader:
                batch_x = batch_x.to(DEVICE)
                batch_y = batch_y.to(DEVICE)
                validation_loss_sum += criterion(model(batch_x), batch_y).item() * len(batch_y)
                validation_items += len(batch_y)
        validation_loss = validation_loss_sum / validation_items

        if validation_loss < best_validation_loss:
            best_validation_loss = validation_loss
            best_weights = copy.deepcopy(model.state_dict())
            no_improvement = 0
        else:
            no_improvement += 1
            if no_improvement >= PATIENCE:
                print(f"Early stopping at epoch {epoch + 1}")
                break
        if epoch % 5 == 0:
            print(f"Epoch {epoch:03d} | validation loss: {validation_loss:.5f}")

    if best_weights is None:
        raise RuntimeError("Training did not produce a valid model")
    model.load_state_dict(best_weights)

    validation_probabilities, validation_targets = predict_probabilities(model, validation_loader)
    best_threshold, threshold_table = choose_threshold(validation_probabilities, validation_targets)
    print("\n--- Validation threshold selection (payout-aware) ---")
    print(threshold_table.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    selected_validation = threshold_table.loc[threshold_table["threshold"] == best_threshold].iloc[0]
    print(
        f"Selected threshold: {best_threshold:.2f} | validation trades: "
        f"{int(selected_validation['trades']):,} | lower-bound expectancy: "
        f"{selected_validation['lower_expectancy']:.3f} per stake"
    )
    if selected_validation["lower_expectancy"] <= 0:
        print("WARNING: no validation threshold has positive lower-bound expectancy. Do not deploy this model live.")

    test_probabilities, test_targets = predict_probabilities(model, test_loader)
    all_direction_predictions = (test_probabilities >= 0.5).astype(int)
    print("\n--- Final untouched test evaluation ---")
    print(f"All-row directional accuracy at 0.50: {accuracy_score(test_targets, all_direction_predictions):.2%}")
    try:
        print(f"All-row ROC AUC: {roc_auc_score(test_targets, test_probabilities):.4f}")
    except ValueError as exc:
        print(f"All-row ROC AUC unavailable: {exc}")

    selected_test = trade_metrics(test_probabilities, test_targets, best_threshold)
    print(
        f"Actionable test cohort at {best_threshold:.2f}: trades={int(selected_test['trades']):,}, "
        f"coverage={selected_test['coverage']:.2%}, win rate={selected_test['win_rate']:.2%}, "
        f"expectancy={selected_test['expectancy']:.3f}/stake, "
        f"95% lower-bound expectancy={selected_test['lower_expectancy']:.3f}/stake"
    )

    actionable = (test_probabilities >= best_threshold) | (test_probabilities <= 1.0 - best_threshold)
    if actionable.any():
        print("\nActionable-test classification report:")
        print(classification_report(
            test_targets[actionable],
            (test_probabilities[actionable] >= 0.5).astype(int),
            digits=4,
        ))

    print("\n--- Per-asset untouched test breakdown ---")
    per_asset_rows = []
    for asset in np.unique(test_asset_labels):
        mask = test_asset_labels == asset
        if mask.sum() < 20:
            continue
        metrics = trade_metrics(test_probabilities[mask], test_targets[mask], best_threshold)
        try:
            auc = roc_auc_score(test_targets[mask], test_probabilities[mask])
        except ValueError:
            auc = np.nan
        per_asset_rows.append({
            "asset": asset,
            "rows": int(mask.sum()),
            "all_row_accuracy": accuracy_score(test_targets[mask], (test_probabilities[mask] >= 0.5).astype(int)),
            "roc_auc": auc,
            "actionable_trades": int(metrics["trades"]),
            "actionable_win_rate": metrics["win_rate"],
            "actionable_expectancy": metrics["expectancy"],
        })
    print(pd.DataFrame(per_asset_rows).sort_values("roc_auc", ascending=False).to_string(index=False))

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path = ARTIFACT_DIR / "deep_lstm_v1.onnx"
    scaler_path = ARTIFACT_DIR / "lstm_scaler.pkl"
    metadata_path = ARTIFACT_DIR / "lstm_metadata.pkl"
    model.eval()
    dummy_input = torch.randn(1, SEQ_LENGTH, len(features), device=DEVICE)
    torch.onnx.export(
        model,
        dummy_input,
        onnx_path,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch_size"}, "output": {0: "batch_size"}},
    )
    joblib.dump(scaler, scaler_path)
    with metadata_path.open("wb") as handle:
        pickle.dump({
            "scale_idx": scale_idx,
            "features": features,
            "asset_features": asset_features,
            "threshold": best_threshold,
            "output_type": "logit",
            "sequence_length": SEQ_LENGTH,
            "binary_payout": BINARY_PAYOUT,
            "split_method": "per_asset_temporal_split_before_windowing",
        }, handle)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "input_size": len(features),
            "sequence_length": SEQ_LENGTH,
        },
        ARTIFACT_DIR / "lstm_model_state.pt",
    )
    print(f"\nSaved ONNX model: {onnx_path}")
    print(f"Saved scaler: {scaler_path}")
    print(f"Saved metadata: {metadata_path}")
    print(f"Saved PyTorch state: {ARTIFACT_DIR / 'lstm_model_state.pt'}")


if __name__ == "__main__":
    main()
