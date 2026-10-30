#!/usr/bin/env python3
"""Train a calibrated CatBoost accept/reject model from candidate research."""

from __future__ import annotations

import json
import math
import os
import pickle
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score


DB_FILE = Path(
    os.getenv("CANDIDATE_RESEARCH_DB", "candidate_research.sqlite")
)
ARTIFACT_DIR = Path(
    os.getenv("META_ARTIFACT_DIR", "candidate_meta_artifacts")
)

TRAIN_FRACTION = 0.55
EARLY_STOP_FRACTION = 0.10
CALIBRATION_FRACTION = 0.20
TEST_FRACTION = 0.15

BINARY_PAYOUT = 0.80
MIN_CONFIDENCE = 0.60
MIN_EDGE = 0.02
MIN_RESOLVED_ROWS = 3_000
MIN_HISTORY_DAYS = 60
MIN_CALIBRATION_TRADES = 300
MIN_CALIBRATION_DAYS = 10
MIN_TEST_TRADES = 300
MIN_TEST_DAYS = 7
COOLDOWN_SECONDS = 300
BOOTSTRAP_SAMPLES = 2_000
RANDOM_SEED = 42


def load_candidates(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Candidate database not found: {path}")
    with sqlite3.connect(path) as connection:
        rows = pd.read_sql_query(
            """
            SELECT candidate_key, asset, direction, decision_time,
                   expiry_time, duration_minutes, strategy, score,
                   confidence, confluence, regime, features_json, label
            FROM candidates
            WHERE label IN (0, 1) AND outcome IN ('win', 'loss')
            ORDER BY decision_time, candidate_key
            """,
            connection,
        )
    if len(rows) < MIN_RESOLVED_ROWS:
        raise ValueError(
            f"Need at least {MIN_RESOLVED_ROWS:,} resolved candidates; "
            f"found {len(rows):,}. Keep candidate research running."
        )
    days = int(rows["decision_time"].floordiv(86_400).nunique())
    if days < MIN_HISTORY_DAYS:
        raise ValueError(
            f"Need at least {MIN_HISTORY_DAYS} UTC days; found {days}."
        )
    return rows


def flatten_features(rows: pd.DataFrame) -> pd.DataFrame:
    decoded = []
    for raw in rows["features_json"]:
        try:
            decoded.append(json.loads(raw) if raw else {})
        except (TypeError, json.JSONDecodeError):
            decoded.append({})
    expanded = pd.json_normalize(decoded, sep=".")
    expanded.columns = [f"snapshot.{column}" for column in expanded.columns]

    base = rows[
        [
            "asset",
            "direction",
            "duration_minutes",
            "strategy",
            "score",
            "confidence",
            "confluence",
            "regime",
            "decision_time",
            "label",
        ]
    ].reset_index(drop=True)
    frame = pd.concat([base, expanded.reset_index(drop=True)], axis=1)
    decision_dt = pd.to_datetime(frame["decision_time"], unit="s", utc=True)
    frame["hour"] = decision_dt.dt.hour
    frame["day_of_week"] = decision_dt.dt.dayofweek
    frame["minute_bucket"] = decision_dt.dt.minute // 5

    # Lists/dicts become stable categorical strings; scalar numeric fields stay
    # numeric. No outcome, entry, settlement, or future candle is included.
    for column in frame.columns:
        if column in {"label", "decision_time"}:
            continue
        if pd.api.types.is_numeric_dtype(frame[column]):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        else:
            frame[column] = frame[column].map(
                lambda value: (
                    json.dumps(value, sort_keys=True)
                    if isinstance(value, (list, dict))
                    else str(value or "unknown")
                )
            )

    feature_columns = [
        column for column in frame.columns
        if column not in {"label", "decision_time"}
    ]
    useful = []
    for column in feature_columns:
        if frame[column].isna().mean() > 0.95:
            continue
        if frame[column].nunique(dropna=True) <= 1:
            continue
        useful.append(column)
    if len(useful) < 5:
        raise ValueError("Too few useful candidate features")
    # Asset is also required by the realistic execution simulator even if a
    # deliberately single-asset research run makes it constant.
    if "asset" not in useful:
        useful.insert(0, "asset")
    return frame[["decision_time", "label"] + useful]


def temporal_splits(frame: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    timeline = np.sort(frame["decision_time"].unique())
    cumulative = (
        TRAIN_FRACTION,
        TRAIN_FRACTION + EARLY_STOP_FRACTION,
        TRAIN_FRACTION + EARLY_STOP_FRACTION + CALIBRATION_FRACTION,
    )
    cutoffs = [
        timeline[min(len(timeline) - 1, int(len(timeline) * value) - 1)]
        for value in cumulative
    ]
    splits = {
        "train": frame.loc[frame["decision_time"] <= cutoffs[0]].copy(),
        "early_stop": frame.loc[
            (frame["decision_time"] > cutoffs[0])
            & (frame["decision_time"] <= cutoffs[1])
        ].copy(),
        "calibration": frame.loc[
            (frame["decision_time"] > cutoffs[1])
            & (frame["decision_time"] <= cutoffs[2])
        ].copy(),
        "test": frame.loc[frame["decision_time"] > cutoffs[2]].copy(),
    }
    if any(part.empty for part in splits.values()):
        raise ValueError("A temporal split is empty")
    for name, part in splits.items():
        print(
            f"{name:12s}: rows={len(part):,}, "
            f"days={part.decision_time.floordiv(86400).nunique()}, "
            f"win-rate={part.label.mean():.2%}"
        )
    return splits


def model_columns(frame: pd.DataFrame) -> Tuple[List[str], List[str]]:
    features = [
        column for column in frame.columns
        if column not in {"decision_time", "label"}
    ]
    categorical = [
        column for column in features
        if not pd.api.types.is_numeric_dtype(frame[column])
    ]
    return features, categorical


def prepare_x(
    frame: pd.DataFrame, features: List[str], categorical: List[str]
) -> pd.DataFrame:
    result = frame[features].copy()
    for column in categorical:
        result[column] = result[column].fillna("unknown").astype(str)
    return result


def fit_platt(raw_scores: np.ndarray, labels: np.ndarray):
    calibrator = LogisticRegression(
        solver="lbfgs", random_state=RANDOM_SEED
    )
    calibrator.fit(raw_scores.reshape(-1, 1), labels)
    return calibrator


def calibrated_probability(model, calibrator, pool: Pool) -> np.ndarray:
    raw = np.asarray(
        model.predict(pool, prediction_type="RawFormulaVal")
    ).reshape(-1)
    return calibrator.predict_proba(raw.reshape(-1, 1))[:, 1]


def executable_indices(
    probability: np.ndarray,
    assets: np.ndarray,
    times: np.ndarray,
    threshold: float,
) -> np.ndarray:
    candidate = np.flatnonzero(probability >= threshold)
    if candidate.size == 0:
        return candidate
    table = pd.DataFrame(
        {
            "index": candidate,
            "asset": assets[candidate],
            "time": times[candidate],
            "probability": probability[candidate],
        }
    )
    table["base"] = table["asset"].str.slice(0, 3)
    table = table.sort_values(
        ["time", "probability"], ascending=[True, False]
    ).drop_duplicates(["time", "base"], keep="first")
    accepted = []
    last_by_asset = {}
    for row in table.itertuples(index=False):
        previous = last_by_asset.get(row.asset)
        if previous is not None and row.time - previous < COOLDOWN_SECONDS:
            continue
        accepted.append(int(row.index))
        last_by_asset[row.asset] = int(row.time)
    return np.asarray(accepted, dtype=np.int64)


def expectancy(win_rate: float) -> float:
    return win_rate * BINARY_PAYOUT - (1.0 - win_rate)


def metrics(probability, labels, assets, times, threshold, seed):
    selected = executable_indices(probability, assets, times, threshold)
    if selected.size == 0:
        return {
            "threshold": threshold, "trades": 0, "days": 0,
            "coverage": 0.0, "win_rate": np.nan,
            "lower_win_rate": np.nan, "expectancy": np.nan,
            "lower_expectancy": np.nan,
        }
    wins = labels[selected].astype(float)
    selected_times = times[selected]
    days = selected_times // 86_400
    unique_days = np.unique(days)
    rng = np.random.default_rng(seed)
    daily_wins = np.asarray([wins[days == day].sum() for day in unique_days])
    daily_n = np.asarray([(days == day).sum() for day in unique_days])
    boot = np.empty(BOOTSTRAP_SAMPLES)
    for index in range(BOOTSTRAP_SAMPLES):
        chosen = rng.integers(0, len(unique_days), len(unique_days))
        boot[index] = daily_wins[chosen].sum() / daily_n[chosen].sum()
    win_rate = float(wins.mean())
    lower = float(np.quantile(boot, 0.025))
    return {
        "threshold": float(threshold),
        "trades": int(len(selected)),
        "days": int(len(unique_days)),
        "coverage": float(len(selected) / len(labels)),
        "win_rate": win_rate,
        "lower_win_rate": lower,
        "expectancy": expectancy(win_rate),
        "lower_expectancy": expectancy(lower),
    }


def choose_threshold(probability, labels, assets, times):
    breakeven = 1 / (1 + BINARY_PAYOUT)
    start = max(
        MIN_CONFIDENCE,
        math.ceil((breakeven + MIN_EDGE) * 100) / 100,
    )
    rows = [
        metrics(
            probability, labels, assets, times, threshold,
            RANDOM_SEED + index,
        )
        for index, threshold in enumerate(
            np.round(np.arange(start, 0.991, 0.01), 2)
        )
    ]
    table = pd.DataFrame(rows)
    eligible = table.loc[
        (table.trades >= MIN_CALIBRATION_TRADES)
        & (table.days >= MIN_CALIBRATION_DAYS)
        & table.lower_expectancy.notna()
    ]
    if eligible.empty:
        return start, table, False
    best = eligible.sort_values(
        ["lower_expectancy", "trades"], ascending=[False, False]
    ).iloc[0]
    return float(best.threshold), table, True


def clean_json(value):
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    return value


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_candidates(DB_FILE)
    frame = flatten_features(rows)
    splits = temporal_splits(frame)
    features, categorical = model_columns(splits["train"])
    cat_indices = [features.index(column) for column in categorical]

    pools = {}
    for name, part in splits.items():
        pools[name] = Pool(
            prepare_x(part, features, categorical),
            label=part["label"].astype(int),
            cat_features=cat_indices,
        )

    model = CatBoostClassifier(
        iterations=1_500,
        depth=6,
        learning_rate=0.03,
        loss_function="Logloss",
        eval_metric="AUC",
        random_seed=RANDOM_SEED,
        l2_leaf_reg=5,
        random_strength=0.5,
        verbose=50,
        allow_writing_files=False,
    )
    model.fit(
        pools["train"],
        eval_set=pools["early_stop"],
        early_stopping_rounds=100,
        use_best_model=True,
    )

    calibration_raw = np.asarray(
        model.predict(
            pools["calibration"], prediction_type="RawFormulaVal"
        )
    ).reshape(-1)
    calibration_labels = splits["calibration"]["label"].to_numpy(int)
    calibrator = fit_platt(calibration_raw, calibration_labels)
    calibration_probability = calibrator.predict_proba(
        calibration_raw.reshape(-1, 1)
    )[:, 1]
    cal_assets = splits["calibration"]["asset"].to_numpy(str)
    cal_times = splits["calibration"]["decision_time"].to_numpy(np.int64)
    threshold, threshold_table, threshold_passed = choose_threshold(
        calibration_probability,
        calibration_labels,
        cal_assets,
        cal_times,
    )
    calibration_metrics = metrics(
        calibration_probability, calibration_labels, cal_assets, cal_times,
        threshold, RANDOM_SEED,
    )

    test_probability = calibrated_probability(
        model, calibrator, pools["test"]
    )
    test_labels = splits["test"]["label"].to_numpy(int)
    test_assets = splits["test"]["asset"].to_numpy(str)
    test_times = splits["test"]["decision_time"].to_numpy(np.int64)
    test_metrics = metrics(
        test_probability, test_labels, test_assets, test_times,
        threshold, RANDOM_SEED + 10_000,
    )
    test_auc = float(roc_auc_score(test_labels, test_probability))
    test_accuracy = float(
        accuracy_score(test_labels, test_probability >= 0.5)
    )
    approved = bool(
        threshold_passed
        and np.isfinite(calibration_metrics["lower_expectancy"])
        and np.isfinite(test_metrics["lower_expectancy"])
        and calibration_metrics["lower_expectancy"] > 0
        and test_metrics["lower_expectancy"] > 0
        and test_metrics["trades"] >= MIN_TEST_TRADES
        and test_metrics["days"] >= MIN_TEST_DAYS
    )

    model.save_model(ARTIFACT_DIR / "candidate_meta_model.cbm")
    with (ARTIFACT_DIR / "candidate_calibrator.pkl").open("wb") as handle:
        pickle.dump(calibrator, handle)
    threshold_table.to_csv(
        ARTIFACT_DIR / "calibration_thresholds.csv", index=False
    )
    metadata = {
        "model_version": "candidate_meta_catboost_v1",
        "features": features,
        "categorical_features": categorical,
        "threshold": threshold,
        "threshold_selection_passed": threshold_passed,
        "payout": BINARY_PAYOUT,
        "calibration_metrics": calibration_metrics,
        "test_auc": test_auc,
        "test_accuracy": test_accuracy,
        "test_metrics": test_metrics,
        "deployment_approved": approved,
        "resolved_rows": len(frame),
    }
    with (ARTIFACT_DIR / "candidate_meta_metadata.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(clean_json(metadata), handle, indent=2)

    print("\n--- FINAL META-LABEL TEST ---")
    print(f"AUC: {test_auc:.4f}; accuracy: {test_accuracy:.2%}")
    print(f"Threshold: {threshold:.2%}; metrics={test_metrics}")
    print(f"deployment_approved={approved}")


if __name__ == "__main__":
    main()
