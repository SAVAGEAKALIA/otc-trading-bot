#!/usr/bin/env python3
"""Train a calibrated CatBoost accept/reject gate on enriched candidates.

Input is produced by build_ml_feature_dataset.py.  This model never predicts
CALL versus PUT; direction and originating strategy are inputs, and class 1
means that the supplied candidate won.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from trading_platform.research.training_provenance import (
    build_calibration_manifest,
    fingerprint_dataset,
    require_unchanged_dataset,
)

# Kept explicit in this transitional trainer for artifact compatibility. The
# trainer imports shared provenance code from the authoritative platform
# package, and a later research-CLI slice will centralize this feature schema.
CONTEXT_SCHEMA_VERSION = "market_context_v2"
MODEL_VERSION = "enriched_catboost_gate_v1"
CONTEXT_FEATURES = [
    "spread_bps", "quote_age_sec", "quote_missing",
    "deal_count_10s", "deal_count_30s", "deal_count_60s",
    "deal_count_log_60s", "call_ratio_10s", "call_ratio_30s",
    "call_ratio_60s", "call_amount_ratio_60s",
    "deal_flow_imbalance_60s", "deal_amount_imbalance_60s",
    "deal_feed_age_sec", "deal_missing", "traders_mood",
    "mood_centered", "mood_age_sec", "mood_missing",
    "payout_fraction", "payout_breakeven", "payout_age_sec",
    "payout_missing", "context_complete",
]


CANDLE_FEATURES = [
    "log_return_1", "log_return_2", "log_return_3", "log_return_5",
    "log_return_10", "open_gap_log", "high_from_open_log",
    "low_from_open_log", "close_from_open_log", "range_pct",
    "dist_ema_20", "dist_ema_50", "ema_20_slope_3",
    "ema_50_slope_3", "atr_pct", "atr_ratio_30", "macd_hist_atr",
    "rsi_centered", "stoch_k_centered", "bb_percent_b", "body_ratio",
    "signed_body_ratio", "upper_wick_ratio", "lower_wick_ratio",
    "close_position", "realized_vol_10", "realized_vol_30",
    "return_zscore_20", "hour_sin", "hour_cos", "day_sin", "day_cos",
]
CANDIDATE_FEATURES = [
    "strategy_score", "strategy_confidence", "confluence",
    "duration_minutes", "direction_sign",
]
NUMERIC_FEATURES = CANDLE_FEATURES + CONTEXT_FEATURES + CANDIDATE_FEATURES
CATEGORICAL_FEATURES = [
    "asset", "direction", "strategy", "regime", "trend_5m", "trend_15m",
]


def load_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def discover(path: Path | None) -> Path:
    if path is not None:
        return path
    candidates = []
    for root in (Path("/kaggle/input"), Path("data/ml/enriched"), Path(".")):
        if root.exists():
            candidates.extend(root.rglob("enriched_candidates.parquet"))
            candidates.extend(root.rglob("enriched_candidates.csv.gz"))
    if not candidates:
        raise FileNotFoundError(
            "No enriched candidate dataset found. Run build_ml_feature_dataset.py first."
        )
    return max(candidates, key=lambda item: item.stat().st_size)


def validate_frame(
    frame: pd.DataFrame,
    minimum_rows: int,
    minimum_days: int,
    require_payout: bool,
    minimum_context_coverage: float,
) -> pd.DataFrame:
    required = {
        "decision_time_ms", "label", *NUMERIC_FEATURES, *CATEGORICAL_FEATURES,
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Candidate dataset is missing features: {missing}")
    result = frame.copy()
    result["decision_time_ms"] = pd.to_numeric(
        result["decision_time_ms"], errors="coerce"
    )
    result["label"] = pd.to_numeric(result["label"], errors="coerce")
    result = result.loc[result["label"].isin([0, 1])].copy()
    result["label"] = result["label"].astype(np.int8)
    result["decision_dt"] = pd.to_datetime(
        result["decision_time_ms"], unit="ms", utc=True, errors="coerce"
    )
    result = result.dropna(subset=["decision_dt"])
    if require_payout:
        result = result.loc[
            result["payout_missing"].eq(0)
            & result["payout_fraction"].gt(0)
        ].copy()
    result = (
        result.sort_values(["decision_time_ms", "asset", "strategy"])
        .drop_duplicates(
            ["decision_time_ms", "asset", "direction", "strategy"],
            keep="last",
        )
        .reset_index(drop=True)
    )
    days = result["decision_dt"].dt.date.nunique()
    context_coverage = {
        name: float(1.0 - result[f"{name}_missing"].mean())
        for name in ("quote", "mood", "payout")
    }
    if len(result) < minimum_rows:
        raise RuntimeError(
            "CatBoost data is not ready: "
            f"rows={len(result):,}/{minimum_rows:,}, days={days}. "
            "Keep the harvester and candidate research ledger running."
        )
    if minimum_days > 0 and days < minimum_days:
        raise RuntimeError(
            "CatBoost data is below the optional operator-supplied minimum: "
            f"days={days}/{minimum_days}. Set --minimum-days 0 to disable "
            "this pre-training check."
        )
    if days < 30:
        print(
            "WARNING: candidate history spans only "
            f"{days} day(s). Training will continue, but short-history "
            "results are less reliable and still face untouched-test gates."
        )
    if min(context_coverage.values()) < minimum_context_coverage:
        raise RuntimeError(
            "CatBoost context is not ready: "
            + ", ".join(
                f"{name}={coverage:.1%}"
                for name, coverage in context_coverage.items()
            )
            + f"; each must be at least {minimum_context_coverage:.1%}."
        )
    if result["label"].nunique() != 2:
        raise ValueError("Both winning and losing candidates are required")
    return result


def temporal_split(frame: pd.DataFrame, purge_minutes: int) -> Dict[str, pd.DataFrame]:
    fractions = (0.50, 0.10, 0.15, 0.10, 0.15)
    unique_times = np.sort(frame["decision_time_ms"].unique())
    if len(unique_times) < 100:
        raise RuntimeError("Candidate timeline is too short for five temporal partitions")
    cuts = [unique_times[min(len(unique_times) - 1, int(len(unique_times) * sum(fractions[:i])))] for i in range(1, 5)]
    purge = purge_minutes * 60_000
    ranges = {
        "train": (None, cuts[0] - purge),
        "early_stop": (cuts[0] + purge, cuts[1] - purge),
        "calibration": (cuts[1] + purge, cuts[2] - purge),
        "policy": (cuts[2] + purge, cuts[3] - purge),
        "test": (cuts[3] + purge, None),
    }
    splits: Dict[str, pd.DataFrame] = {}
    for name, (lower, upper) in ranges.items():
        selected = pd.Series(True, index=frame.index)
        if lower is not None:
            selected &= frame["decision_time_ms"].ge(lower)
        if upper is not None:
            selected &= frame["decision_time_ms"].le(upper)
        part = frame.loc[selected].copy()
        if part.empty or part["label"].nunique() != 2:
            raise RuntimeError(f"Temporal split {name} is empty or has one class")
        splits[name] = part
        print(
            f"{name:12s} rows={len(part):7,d} days={part['decision_dt'].dt.date.nunique():3d} "
            f"win={part['label'].mean():.3%}"
        )
    return splits


def model_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame[NUMERIC_FEATURES + CATEGORICAL_FEATURES].copy()
    for column in NUMERIC_FEATURES:
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(np.float32)
    for column in CATEGORICAL_FEATURES:
        result[column] = result[column].fillna("unknown").astype(str)
    return result.replace([np.inf, -np.inf], np.nan)


def probability_metrics(labels: np.ndarray, probabilities: np.ndarray) -> Dict[str, float]:
    return {
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "log_loss": float(log_loss(labels, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(labels, probabilities)),
    }


def selected_returns(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float,
    assumed_payout: float,
) -> pd.DataFrame:
    selected = frame.loc[probabilities >= threshold].copy()
    selected["probability"] = probabilities[probabilities >= threshold]
    payout = pd.to_numeric(selected["payout_fraction"], errors="coerce")
    payout = payout.where(selected["payout_missing"].eq(0), assumed_payout)
    selected["unit_return"] = np.where(selected["label"].eq(1), payout, -1.0)
    return selected


def day_bootstrap_lower_expectancy(
    selected: pd.DataFrame,
    samples: int,
    seed: int,
) -> float:
    if selected.empty:
        return float("nan")
    daily = selected.assign(day=selected["decision_dt"].dt.floor("D")).groupby("day")["unit_return"].agg(["sum", "count"])
    if len(daily) < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    values = []
    sums = daily["sum"].to_numpy(float)
    counts = daily["count"].to_numpy(float)
    for _ in range(samples):
        chosen = rng.integers(0, len(daily), len(daily))
        values.append(float(sums[chosen].sum() / counts[chosen].sum()))
    return float(np.quantile(values, 0.025))


def choose_threshold(
    policy: pd.DataFrame,
    probabilities: np.ndarray,
    assumed_payout: float,
    minimum_trades: int,
    bootstrap_samples: int,
    seed: int,
) -> tuple[float, pd.DataFrame]:
    rows = []
    for threshold in np.arange(0.50, 0.901, 0.01):
        selected = selected_returns(policy, probabilities, float(threshold), assumed_payout)
        lower = day_bootstrap_lower_expectancy(selected, bootstrap_samples, seed)
        rows.append(
            {
                "threshold": float(threshold),
                "trades": int(len(selected)),
                "days": int(selected["decision_dt"].dt.date.nunique()) if not selected.empty else 0,
                "win_rate": float(selected["label"].mean()) if not selected.empty else None,
                "expectancy": float(selected["unit_return"].mean()) if not selected.empty else None,
                "lower_95_expectancy": lower if math.isfinite(lower) else None,
            }
        )
    table = pd.DataFrame(rows)
    eligible = table.loc[
        table["trades"].ge(minimum_trades)
        & table["lower_95_expectancy"].fillna(-np.inf).gt(0)
    ]
    if eligible.empty:
        fallback = table.loc[table["trades"].ge(minimum_trades)]
        chosen = fallback.sort_values("expectancy", ascending=False).head(1)
        return (float(chosen.iloc[0]["threshold"]) if not chosen.empty else 0.99), table
    best = eligible.sort_values(
        ["lower_95_expectancy", "trades"], ascending=[False, False]
    ).iloc[0]
    return float(best["threshold"]), table


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train enriched CatBoost candidate gate")
    parser.add_argument("--data", type=Path)
    parser.add_argument(
        "--dataset-id",
        help="Immutable dataset ID; defaults to filename plus SHA-256 prefix",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/ml/models"))
    parser.add_argument("--minimum-rows", type=int, default=2_000)
    parser.add_argument(
        "--minimum-days",
        type=int,
        default=0,
        help="Optional pre-training calendar minimum; 0 disables it (default)",
    )
    parser.add_argument("--minimum-context-coverage", type=float, default=0.70)
    parser.add_argument("--minimum-policy-trades", type=int, default=250)
    parser.add_argument("--minimum-test-trades", type=int, default=300)
    parser.add_argument("--minimum-test-days", type=int, default=14)
    parser.add_argument("--purge-minutes", type=int, default=30)
    parser.add_argument("--assumed-payout", type=float, default=0.80)
    parser.add_argument("--allow-missing-payout", action="store_true")
    parser.add_argument("--iterations", type=int, default=1500)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--gpu", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    try:
        from catboost import CatBoostClassifier, Pool
    except ImportError as exc:
        raise RuntimeError("Install CatBoost first: pip install catboost") from exc

    path = discover(args.data)
    print(f"Loading {path}")
    dataset_fingerprint = fingerprint_dataset(path)
    dataset_id = args.dataset_id or (
        f"{path.name}:{str(dataset_fingerprint['sha256'])[:16]}"
    )
    frame = validate_frame(
        load_frame(path), args.minimum_rows, args.minimum_days,
        require_payout=not args.allow_missing_payout,
        minimum_context_coverage=args.minimum_context_coverage,
    )
    splits = temporal_split(frame, args.purge_minutes)
    feature_order = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    categorical_indices = [feature_order.index(name) for name in CATEGORICAL_FEATURES]
    pools = {
        name: Pool(
            model_frame(part),
            label=part["label"].to_numpy(int),
            cat_features=categorical_indices,
        )
        for name, part in splits.items()
    }
    parameters = dict(
        iterations=args.iterations, depth=args.depth,
        learning_rate=args.learning_rate, loss_function="Logloss",
        eval_metric="AUC", random_seed=args.seed, l2_leaf_reg=7.0,
        random_strength=0.5, verbose=50, allow_writing_files=False,
    )
    if args.gpu:
        parameters.update(task_type="GPU", devices="0")
    model = CatBoostClassifier(**parameters)
    model.fit(
        pools["train"], eval_set=pools["early_stop"],
        early_stopping_rounds=120, use_best_model=True,
    )

    calibration_raw = np.asarray(
        model.predict(pools["calibration"], prediction_type="RawFormulaVal")
    ).reshape(-1, 1)
    calibrator = LogisticRegression(solver="lbfgs", random_state=args.seed)
    calibrator.fit(calibration_raw, splits["calibration"]["label"].to_numpy(int))

    def calibrated(name: str) -> np.ndarray:
        raw = np.asarray(
            model.predict(pools[name], prediction_type="RawFormulaVal")
        ).reshape(-1, 1)
        return calibrator.predict_proba(raw)[:, 1]

    policy_probability = calibrated("policy")
    threshold, threshold_table = choose_threshold(
        splits["policy"], policy_probability, args.assumed_payout,
        args.minimum_policy_trades, args.bootstrap_samples, args.seed + 100,
    )
    test_probability = calibrated("test")
    selected_test = selected_returns(
        splits["test"], test_probability, threshold, args.assumed_payout
    )
    lower_test = day_bootstrap_lower_expectancy(
        selected_test, args.bootstrap_samples, args.seed + 200
    )
    test_days = selected_test["decision_dt"].dt.date.nunique() if not selected_test.empty else 0
    offline_approved = bool(
        len(selected_test) >= args.minimum_test_trades
        and test_days >= args.minimum_test_days
        and math.isfinite(lower_test)
        and lower_test > 0
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.output_dir / "catboost_gate.cbm"
    calibrator_path = args.output_dir / "catboost_calibrator.joblib"
    metadata_path = args.output_dir / "catboost_gate_metadata.json"
    model.save_model(model_path)
    joblib.dump(calibrator, calibrator_path)
    threshold_table.to_csv(args.output_dir / "catboost_policy_thresholds.csv", index=False)
    all_probability_metrics = {
        name: probability_metrics(
            splits[name]["label"].to_numpy(int), calibrated(name)
        )
        for name in ("calibration", "policy", "test")
    }
    require_unchanged_dataset(path, dataset_fingerprint)
    split_windows = {
        name: (
            part["decision_dt"].min().to_pydatetime(),
            part["decision_dt"].max().to_pydatetime(),
            len(part),
        )
        for name, part in splits.items()
    }
    provenance = build_calibration_manifest(
        model_version=MODEL_VERSION,
        method="platt_logistic",
        target_definition="candidate_wins_at_fixed_expiry",
        dataset_id=dataset_id,
        dataset_sha256=str(dataset_fingerprint["sha256"]),
        split_windows=split_windows,
        test_metrics=all_probability_metrics["test"],
        artifact_paths={"model": model_path, "calibrator": calibrator_path},
        offline_deployment_approved=offline_approved,
    )
    provenance_path = args.output_dir / "catboost_gate_calibration_provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    metadata = {
        "artifact_type": "iqoption_candidate_meta_gate",
        "model_version": MODEL_VERSION,
        "calibration_id": provenance["calibration_id"],
        "context_schema_version": CONTEXT_SCHEMA_VERSION,
        "positive_class": "candidate_wins",
        "feature_order": feature_order,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "feature_schema_sha256": hashlib.sha256(
            json.dumps(feature_order, separators=(",", ":")).encode()
        ).hexdigest(),
        "selected_threshold": threshold,
        "assumed_payout": args.assumed_payout,
        "minimum_context_coverage": args.minimum_context_coverage,
        "training_rows": int(len(frame)),
        "training_days": int(frame["decision_dt"].dt.date.nunique()),
        "context_coverage": {
            name: float(1.0 - frame[f"{name}_missing"].mean())
            for name in ("quote", "mood", "payout", "deal")
        },
        "probability_metrics": all_probability_metrics,
        "untouched_test": {
            "trades": int(len(selected_test)),
            "days": int(test_days),
            "win_rate": float(selected_test["label"].mean()) if not selected_test.empty else None,
            "expectancy": float(selected_test["unit_return"].mean()) if not selected_test.empty else None,
            "lower_95_expectancy": lower_test if math.isfinite(lower_test) else None,
        },
        "offline_deployment_approved": offline_approved,
        "live_deployment_approved": False,
    }
    metadata_path.write_text(json.dumps(clean(metadata), indent=2), encoding="utf-8")
    print(json.dumps(clean(metadata), indent=2))
    print(f"Artifacts written to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
