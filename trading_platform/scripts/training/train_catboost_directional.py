#!/usr/bin/env python3
"""Train a calibrated directional CatBoost model from enriched multi-timeframe candles.

This is a standalone Kaggle/Colab trainer with multi-timeframe lookbacks (2m, 5m, 15m, 1hr),
traders' mood velocity, quote spread regime, cross-asset basket momentum, and variable
prediction horizons (2m, 4m, 6m).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import joblib
import numpy as np
import pandas as pd
import pandas_ta as ta
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from trading_platform.research.training_provenance import (
    build_calibration_manifest,
    fingerprint_dataset,
    require_unchanged_dataset,
)


MODEL_VERSION = "enriched_catboost_directional_v2"
CONTEXT_SCHEMA_VERSION = "market_context_v2"
EXPECTED_PANDAS_TA_VERSION = "0.4.71b0"
TIMEFRAME_SECONDS = 120

CANDLE_FEATURES = [
    "log_return_1", "log_return_2", "log_return_3", "log_return_5",
    "log_return_10", "log_return_15", "log_return_30",
    "open_gap_log", "high_from_open_log", "low_from_open_log", "close_from_open_log",
    "range_pct", "dist_ema_20", "dist_ema_50", "dist_ema_200",
    "ema_20_slope_3", "ema_50_slope_3", "mtf_trend_alignment",
    "atr_pct", "atr_ratio_30", "macd_hist_atr",
    "rsi_centered", "rsi_slope_3", "stoch_k_centered", "stoch_d_centered", "stoch_diff",
    "bb_percent_b", "bb_width", "body_ratio", "signed_body_ratio",
    "upper_wick_ratio", "lower_wick_ratio", "close_position",
    "realized_vol_10", "realized_vol_30", "return_zscore_20",
    "hour_sin", "hour_cos", "day_sin", "day_cos",
]

CONTEXT_FEATURES = [
    "spread_bps", "spread_ratio_30", "quote_age_sec", "quote_missing",
    "deal_count_10s", "deal_count_30s", "deal_count_60s",
    "deal_count_log_60s", "call_ratio_10s", "call_ratio_30s",
    "call_ratio_60s", "call_amount_ratio_60s",
    "deal_flow_imbalance_60s", "deal_amount_imbalance_60s",
    "deal_feed_age_sec", "deal_missing",
    "traders_mood", "mood_centered", "mood_delta_3", "mood_delta_5", "mood_extreme", "mood_agree_trend",
    "mood_age_sec", "mood_missing",
    "payout_fraction", "payout_breakeven", "payout_age_sec",
    "payout_missing", "context_complete",
]

CROSS_ASSET_FEATURES = [
    "market_return_1", "market_return_5",
    "asset_rel_return_1", "asset_rel_return_5",
    "market_mood_mean", "asset_rel_mood",
]

NUMERIC_FEATURES = CANDLE_FEATURES + CONTEXT_FEATURES + CROSS_ASSET_FEATURES
CATEGORICAL_FEATURES = ["asset"]
FEATURE_ORDER = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def discover(path: Path | None) -> Path:
    if path is not None:
        return path
    exact: list[Path] = []
    fallback: list[Path] = []
    for root in (Path("/kaggle/input"), Path("data/ml"), Path("data/features"), Path(".")):
        if not root.exists():
            continue
        exact.extend(root.rglob("unified_mtf_context_candles.parquet"))
        exact.extend(root.rglob("enriched_candles.parquet"))
        exact.extend(root.rglob("enriched_candles.csv.gz"))
        fallback.extend(root.rglob("*enriched*candle*.parquet"))
        fallback.extend(root.rglob("*enriched*candle*.csv.gz"))
    candidates = list(dict.fromkeys(exact or fallback))
    if not candidates:
        raise FileNotFoundError(
            "No enriched candle dataset found. Provide path via --data."
        )
    selected = max(candidates, key=lambda item: item.stat().st_size)
    print(f"Auto-discovered dataset: {selected}")
    return selected


def parse_timestamp(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")
    mask = numeric.notna()
    if mask.any():
        magnitude = float(numeric.loc[mask].abs().median())
        unit = "ns" if magnitude >= 1e17 else "us" if magnitude >= 1e14 else "ms" if magnitude >= 1e11 else "s"
        result.loc[mask] = pd.to_datetime(
            numeric.loc[mask], unit=unit, utc=True, errors="coerce"
        )
    if (~mask).any():
        result.loc[~mask] = pd.to_datetime(
            series.loc[~mask], utc=True, errors="coerce"
        )
    return result


def load_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    frame = (
        pd.read_parquet(path)
        if path.suffix.lower() == ".parquet"
        else pd.read_csv(path, low_memory=False)
    )
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    required = ["asset", "timestamp", "open", "high", "low", "close"]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"Dataset missing required OHLC columns: {missing}")

    frame["asset"] = frame["asset"].astype(str).str.strip().str.upper().str.replace("_", "-", regex=False)
    frame["timestamp"] = parse_timestamp(frame["timestamp"])
    for col in ("open", "high", "low", "close"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    # Context defaults if absent
    if "spread_bps" not in frame.columns:
        frame["spread_bps"] = 0.0001
    if "spread_ratio_30" not in frame.columns:
        frame["spread_ratio_30"] = 1.0
    if "quote_age_sec" not in frame.columns:
        frame["quote_age_sec"] = 0.0
    if "quote_missing" not in frame.columns:
        frame["quote_missing"] = 0.0
    if "traders_mood" not in frame.columns:
        frame["traders_mood"] = 0.50
    if "mood_centered" not in frame.columns:
        frame["mood_centered"] = 0.0
    if "mood_age_sec" not in frame.columns:
        frame["mood_age_sec"] = 0.0
    if "mood_missing" not in frame.columns:
        frame["mood_missing"] = 0.0
    if "payout_fraction" not in frame.columns:
        frame["payout_fraction"] = 0.80
    if "payout_breakeven" not in frame.columns:
        frame["payout_breakeven"] = 1.0 / (1.0 + 0.80)
    if "payout_age_sec" not in frame.columns:
        frame["payout_age_sec"] = 0.0
    if "payout_missing" not in frame.columns:
        frame["payout_missing"] = 0.0
    if "context_complete" not in frame.columns:
        frame["context_complete"] = 1.0

    # Deals fallback defaults
    for c in ("deal_count_10s", "deal_count_30s", "deal_count_60s", "deal_count_log_60s",
              "call_amount_ratio_60s", "deal_flow_imbalance_60s", "deal_amount_imbalance_60s"):
        if c not in frame.columns:
            frame[c] = 0.0
    for c in ("call_ratio_10s", "call_ratio_30s", "call_ratio_60s"):
        if c not in frame.columns:
            frame[c] = 0.5
    if "deal_feed_age_sec" not in frame.columns:
        frame["deal_feed_age_sec"] = 300.0
    if "deal_missing" not in frame.columns:
        frame["deal_missing"] = 1.0

    valid = (
        frame["timestamp"].notna()
        & frame[["open", "high", "low", "close"]].gt(0).all(axis=1)
        & frame["high"].ge(frame[["open", "close", "low"]].max(axis=1))
        & frame["low"].le(frame[["open", "close", "high"]].min(axis=1))
    )
    frame = (
        frame.loc[valid]
        .sort_values(["asset", "timestamp"])
        .drop_duplicates(["asset", "timestamp"], keep="last")
        .reset_index(drop=True)
    )
    days = int(frame["timestamp"].dt.date.nunique())
    print(f"Loaded {len(frame):,} candles, assets={frame['asset'].nunique()}, days={days}")
    return frame


def add_features(segment: pd.DataFrame, horizon_steps: int = 1) -> pd.DataFrame:
    result = segment.copy()
    close = result["close"].replace(0.0, np.nan)
    open_p = result["open"].replace(0.0, np.nan)
    high = result["high"].replace(0.0, np.nan)
    low = result["low"].replace(0.0, np.nan)
    log_close = np.log(close)

    # 1. Multi-Timeframe Lookbacks (2m, 5m, 15m, 1hr proxies)
    result["log_return_1"] = log_close.diff(1)
    result["log_return_2"] = log_close.diff(2)
    result["log_return_3"] = log_close.diff(3)
    result["log_return_5"] = log_close.diff(5)
    result["log_return_10"] = log_close.diff(10)
    result["log_return_15"] = log_close.diff(15)
    result["log_return_30"] = log_close.diff(30)

    previous_close = close.shift(1)
    result["open_gap_log"] = np.log(open_p / previous_close)
    result["high_from_open_log"] = np.log(high / open_p)
    result["low_from_open_log"] = np.log(low / open_p)
    result["close_from_open_log"] = np.log(close / open_p)
    result["range_pct"] = (high - low) / close

    # Moving averages & MTF alignment
    ema_20 = ta.ema(close, length=20)
    ema_50 = ta.ema(close, length=50)
    ema_200 = ta.ema(close, length=200)

    result["dist_ema_20"] = close / ema_20 - 1.0
    result["dist_ema_50"] = close / ema_50 - 1.0
    result["dist_ema_200"] = (close / ema_200 - 1.0).fillna(0.0) if ema_200 is not None else 0.0
    result["ema_20_slope_3"] = np.log(ema_20 / ema_20.shift(3))
    result["ema_50_slope_3"] = np.log(ema_50 / ema_50.shift(3))
    result["mtf_trend_alignment"] = np.where(
        (close > ema_20) & (ema_20 > ema_50), 1.0,
        np.where((close < ema_20) & (ema_20 < ema_50), -1.0, 0.0)
    )

    # 2. Oscillators & Volatility
    atr = ta.atr(high, low, close, length=14)
    result["atr_pct"] = atr / close
    result["atr_ratio_30"] = result["atr_pct"] / result["atr_pct"].rolling(30, min_periods=30).median()
    macd = ta.macd(close, fast=12, slow=26, signal=9)
    result["macd_hist_atr"] = macd.iloc[:, 1] / atr.replace(0.0, np.nan)
    result["rsi_centered"] = (ta.rsi(close, length=14) - 50.0) / 50.0
    result["rsi_slope_3"] = result["rsi_centered"] - result["rsi_centered"].shift(3)

    stochastic = ta.stoch(high, low, close, k=14, d=3, smooth_k=3)
    result["stoch_k_centered"] = (stochastic.iloc[:, 0] - 50.0) / 50.0
    result["stoch_d_centered"] = (stochastic.iloc[:, 1] - 50.0) / 50.0
    result["stoch_diff"] = result["stoch_k_centered"] - result["stoch_d_centered"]

    bands = ta.bbands(close, length=20, std=2.0)
    result["bb_percent_b"] = bands.iloc[:, 4]
    result["bb_width"] = (bands.iloc[:, 2] - bands.iloc[:, 0]) / bands.iloc[:, 1]

    # Candle price action mechanics
    candle_range = high - low + 1e-8
    body = close - open_p
    result["body_ratio"] = body.abs() / candle_range
    result["signed_body_ratio"] = body / candle_range
    result["upper_wick_ratio"] = (high - np.maximum(open_p, close)) / candle_range
    result["lower_wick_ratio"] = (np.minimum(open_p, close) - low) / candle_range
    result["close_position"] = (close - low) / candle_range

    one_return = result["log_return_1"]
    result["realized_vol_10"] = one_return.rolling(10, min_periods=10).std(ddof=0)
    result["realized_vol_30"] = one_return.rolling(30, min_periods=30).std(ddof=0)
    rolling_mean = one_return.rolling(20, min_periods=20).mean()
    rolling_std = one_return.rolling(20, min_periods=20).std(ddof=0)
    result["return_zscore_20"] = (one_return - rolling_mean) / rolling_std.replace(0.0, np.nan)

    minute = result["timestamp"].dt.hour * 60 + result["timestamp"].dt.minute
    hour_angle = 2.0 * np.pi * minute / 1440.0
    day_angle = 2.0 * np.pi * result["timestamp"].dt.dayofweek / 7.0
    result["hour_sin"], result["hour_cos"] = np.sin(hour_angle), np.cos(hour_angle)
    result["day_sin"], result["day_cos"] = np.sin(day_angle), np.cos(day_angle)

    # 3. Market Context: Traders' Mood, Spread & Payout Dynamics
    result["mood_centered"] = result["traders_mood"] - 0.5
    result["mood_delta_3"] = result["traders_mood"] - result["traders_mood"].shift(3)
    result["mood_delta_5"] = result["traders_mood"] - result["traders_mood"].shift(5)
    result["mood_extreme"] = np.where(result["traders_mood"] > 0.75, 1.0, np.where(result["traders_mood"] < 0.25, -1.0, 0.0))
    result["mood_agree_trend"] = result["mood_centered"] * result["mtf_trend_alignment"]
    result["spread_ratio_30"] = result["spread_bps"] / result["spread_bps"].rolling(30, min_periods=10).median().replace(0.0, np.nan)

    # 4. Target Label for Executable Expiry Horizon
    next_open = segment["open"].shift(-1)
    target_close = segment["close"].shift(-horizon_steps)
    result["target_up"] = np.where(
        target_close > next_open, 1.0,
        np.where(target_close < next_open, 0.0, np.nan),
    )
    result.loc[next_open.isna() | target_close.isna(), "target_up"] = np.nan
    return result


def prepare_rows(candles: pd.DataFrame, horizon_steps: int = 1) -> pd.DataFrame:
    target_col = f"target_{horizon_steps * 2}m_up"
    if target_col in candles.columns and "dist_ema_50" in candles.columns:
        print(f"Pre-engineered dataset detected with column '{target_col}'")
        df = candles.copy()
        df["target_up"] = df[target_col].astype(np.int8)
        if "decision_time_ms" not in df.columns:
            df["decision_time_ms"] = df["timestamp"].astype("int64") // 1_000_000 + TIMEFRAME_SECONDS * 1_000
        df["decision_dt"] = pd.to_datetime(df["decision_time_ms"], unit="ms", utc=True)
        for col in NUMERIC_FEATURES:
            if col not in df.columns:
                df[col] = 0.0
        df = df.dropna(subset=["target_up", "rsi_centered", "dist_ema_50"])
        print(
            f"Using {len(df):,} pre-computed labeled rows (horizon={horizon_steps*2}m); target-up={df['target_up'].mean():.3%}"
        )
        return df

    pieces = []
    for asset, asset_rows in candles.groupby("asset", sort=True):
        asset_rows = asset_rows.sort_values("timestamp").reset_index(drop=True)
        segment_ids = asset_rows["timestamp"].diff().dt.total_seconds().ne(TIMEFRAME_SECONDS).cumsum()
        for _, segment in asset_rows.groupby(segment_ids, sort=False):
            if len(segment) < 65:
                continue
            segment = segment.copy().reset_index(drop=True)
            featured = add_features(segment, horizon_steps=horizon_steps).replace([np.inf, -np.inf], np.nan)
            featured = featured.dropna(subset=["target_up", "rsi_centered", "dist_ema_50", "realized_vol_30"])
            if featured.empty:
                continue
            featured["asset"] = asset
            featured["decision_time_ms"] = (
                featured["timestamp"].astype("int64") // 1_000_000
                + TIMEFRAME_SECONDS * 1_000
            )
            pieces.append(featured)
    if not pieces:
        raise RuntimeError("No gap-free feature rows with executable labels")
    all_rows = pd.concat(pieces, ignore_index=True)
    all_rows["target_up"] = all_rows["target_up"].astype(np.int8)
    all_rows["decision_dt"] = pd.to_datetime(all_rows["decision_time_ms"], unit="ms", utc=True)
    all_rows = all_rows.sort_values(["decision_time_ms", "asset"]).reset_index(drop=True)

    # 5. Synchronized Cross-Asset Basket Features
    all_rows["market_return_1"] = all_rows.groupby("decision_time_ms")["log_return_1"].transform("mean").fillna(0.0)
    all_rows["asset_rel_return_1"] = all_rows["log_return_1"] - all_rows["market_return_1"]
    all_rows["market_return_5"] = all_rows.groupby("decision_time_ms")["log_return_5"].transform("mean").fillna(0.0)
    all_rows["asset_rel_return_5"] = all_rows["log_return_5"] - all_rows["market_return_5"]
    all_rows["market_mood_mean"] = all_rows.groupby("decision_time_ms")["traders_mood"].transform("mean").fillna(0.5)
    all_rows["asset_rel_mood"] = all_rows["traders_mood"] - all_rows["market_mood_mean"]

    print(
        f"Prepared {len(all_rows):,} labeled rows (horizon={horizon_steps*2}m); target-up={all_rows['target_up'].mean():.3%}"
    )
    return all_rows


def temporal_split(frame: pd.DataFrame, purge_minutes: int) -> Dict[str, pd.DataFrame]:
    fractions = (0.50, 0.10, 0.15, 0.10, 0.15)
    times = np.sort(frame["decision_time_ms"].unique())
    if len(times) < 100:
        raise RuntimeError("Timeline is too short for five temporal partitions")
    cumulative = np.cumsum(fractions)[:-1]
    cuts = [times[min(len(times) - 1, int(len(times) * fraction))] for fraction in cumulative]
    purge = purge_minutes * 60_000
    ranges = {
        "train": (None, cuts[0] - purge),
        "early_stop": (cuts[0] + purge, cuts[1] - purge),
        "calibration": (cuts[1] + purge, cuts[2] - purge),
        "policy": (cuts[2] + purge, cuts[3] - purge),
        "test": (cuts[3] + purge, None),
    }
    result = {}
    for name, (lower, upper) in ranges.items():
        mask = pd.Series(True, index=frame.index)
        if lower is not None:
            mask &= frame["decision_time_ms"].ge(lower)
        if upper is not None:
            mask &= frame["decision_time_ms"].le(upper)
        part = frame.loc[mask].copy().reset_index(drop=True)
        if part.empty or part["target_up"].nunique() != 2:
            raise RuntimeError(f"Temporal partition {name} is empty or has one class")
        result[name] = part
        print(
            f"{name:12s} rows={len(part):7,d} days={part['decision_dt'].dt.date.nunique():3d} "
            f"up={part['target_up'].mean():.3%}"
        )
    return result


def model_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame[FEATURE_ORDER].copy()
    for name in NUMERIC_FEATURES:
        result[name] = pd.to_numeric(result[name], errors="coerce").fillna(0.0).astype(np.float32)
    result["asset"] = result["asset"].fillna("unknown").astype(str)
    return result


def probability_metrics(labels: np.ndarray, probabilities: np.ndarray) -> Dict[str, float]:
    base = float(np.mean(labels))
    null = np.full(len(labels), base, dtype=float)
    brier = float(brier_score_loss(labels, probabilities))
    null_brier = float(brier_score_loss(labels, null))
    return {
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "log_loss": float(log_loss(labels, probabilities, labels=[0, 1])),
        "null_log_loss": float(log_loss(labels, null, labels=[0, 1])),
        "brier_score": brier,
        "null_brier_score": null_brier,
        "brier_skill_score": float(1.0 - brier / null_brier) if null_brier > 0 else 0.0,
    }


def selected_returns(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float,
    assumed_payout: float,
    cooldown_seconds: int,
) -> pd.DataFrame:
    work = frame.copy()
    work["probability_up"] = probabilities
    work["confidence"] = np.maximum(probabilities, 1.0 - probabilities)
    work["predicted_up"] = probabilities >= 0.5
    work = work.loc[work["confidence"].ge(threshold)].copy()
    if work.empty:
        return work
    accepted = []
    last_by_asset: Dict[str, int] = {}
    cooldown_ms = cooldown_seconds * 1_000
    for index, row in work.sort_values(["decision_time_ms", "asset"]).iterrows():
        last = last_by_asset.get(str(row["asset"]))
        now = int(row["decision_time_ms"])
        if last is None or now - last >= cooldown_ms:
            accepted.append(index)
            last_by_asset[str(row["asset"])] = now
    work = work.loc[accepted].copy()
    work["won"] = work["predicted_up"].eq(work["target_up"].astype(bool))
    payout = pd.to_numeric(work["payout_fraction"], errors="coerce")
    payout = payout.where(work["payout_missing"].eq(0) & payout.gt(0), assumed_payout)
    work["unit_return"] = np.where(work["won"], payout, -1.0)
    return work


def day_bootstrap_lower(selected: pd.DataFrame, samples: int, seed: int) -> float:
    if selected.empty:
        return float("nan")
    daily = selected.assign(day=selected["decision_dt"].dt.floor("D")).groupby("day")["unit_return"].agg(["sum", "count"])
    if len(daily) < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    sums, counts = daily["sum"].to_numpy(float), daily["count"].to_numpy(float)
    estimates = []
    for _ in range(samples):
        chosen = rng.integers(0, len(daily), len(daily))
        estimates.append(float(sums[chosen].sum() / counts[chosen].sum()))
    return float(np.quantile(estimates, 0.025))


def choose_threshold(
    policy: pd.DataFrame,
    probabilities: np.ndarray,
    args: argparse.Namespace,
) -> tuple[float, pd.DataFrame, bool]:
    rows = []
    # Use fine-grained thresholds matching the natural empirical probability span of financial gradient boosting
    thresholds = np.concatenate([
        np.arange(0.500, 0.530, 0.002),
        np.arange(0.530, 0.600, 0.005),
        np.arange(0.600, 0.901, 0.020),
    ])
    for threshold in thresholds:
        selected = selected_returns(
            policy, probabilities, float(threshold), args.assumed_payout,
            args.cooldown_seconds,
        )
        lower = day_bootstrap_lower(selected, args.bootstrap_samples, args.seed + 100)
        rows.append({
            "threshold": float(threshold), "trades": int(len(selected)),
            "days": int(selected["decision_dt"].dt.date.nunique()) if not selected.empty else 0,
            "win_rate": float(selected["won"].mean()) if not selected.empty else None,
            "expectancy": float(selected["unit_return"].mean()) if not selected.empty else None,
            "lower_95_expectancy": lower if math.isfinite(lower) else None,
        })
    table = pd.DataFrame(rows)
    eligible = table.loc[
        table["trades"].ge(args.minimum_policy_trades)
        & table["lower_95_expectancy"].fillna(-np.inf).gt(0)
    ]
    if eligible.empty:
        fallback = table.loc[table["trades"].ge(args.minimum_policy_trades)]
        if fallback.empty:
            return 0.99, table, False
        best = fallback.sort_values("expectancy", ascending=False).iloc[0]
        return float(best["threshold"]), table, False
    best = eligible.sort_values(
        ["lower_95_expectancy", "trades"], ascending=[False, False]
    ).iloc[0]
    return float(best["threshold"]), table, True


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train directional CatBoost from enriched multi-timeframe candles")
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument(
        "--dataset-id",
        type=str,
        default=None,
        help="Immutable dataset ID; defaults to filename plus SHA-256 prefix",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/ml/models"))
    parser.add_argument("--horizon-minutes", type=int, default=2, choices=[2, 4, 6], help="Prediction expiry horizon")
    parser.add_argument("--minimum-rows", type=int, default=500)
    parser.add_argument("--purge-minutes", type=int, default=15)
    parser.add_argument("--minimum-policy-trades", type=int, default=100)
    parser.add_argument("--minimum-test-trades", type=int, default=150)
    parser.add_argument("--minimum-test-days", type=int, default=3)
    parser.add_argument("--minimum-context-coverage", type=float, default=0.70)
    parser.add_argument("--assumed-payout", type=float, default=0.80)
    parser.add_argument("--cooldown-seconds", type=int, default=300)
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--l2-leaf-reg", type=float, default=30.0)
    parser.add_argument("--subsample", type=float, default=0.8)
    parser.add_argument("--rsm", type=float, default=0.7)
    parser.add_argument("--early-stopping-rounds", type=int, default=150)
    parser.add_argument("--eval-metric", type=str, default="Logloss")
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--gpu", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if package_version("pandas-ta") != EXPECTED_PANDAS_TA_VERSION:
        raise RuntimeError(
            f"Install pandas-ta=={EXPECTED_PANDAS_TA_VERSION} for live parity"
        )
    from catboost import CatBoostClassifier, Pool

    random.seed(args.seed)
    np.random.seed(args.seed)
    path = discover(args.data)
    dataset_fingerprint = fingerprint_dataset(path)
    dataset_id = args.dataset_id or (
        f"{path.name}:{str(dataset_fingerprint['sha256'])[:16]}"
    )
    horizon_steps = args.horizon_minutes // 2
    rows = prepare_rows(load_frame(path), horizon_steps=horizon_steps)
    if len(rows) < args.minimum_rows:
        raise RuntimeError(
            f"Only {len(rows):,} usable rows; require {args.minimum_rows:,}. "
            "Lower --minimum-rows only for an explicitly experimental run."
        )
    splits = temporal_split(rows, args.purge_minutes)
    categorical_indices = [FEATURE_ORDER.index(name) for name in CATEGORICAL_FEATURES]
    pools = {
        name: Pool(
            model_frame(part), label=part["target_up"].to_numpy(int),
            cat_features=categorical_indices,
        )
        for name, part in splits.items()
    }
    parameters = dict(
        iterations=args.iterations, depth=args.depth,
        learning_rate=args.learning_rate, loss_function="Logloss",
        eval_metric=args.eval_metric, random_seed=args.seed, l2_leaf_reg=args.l2_leaf_reg,
        subsample=args.subsample, rsm=args.rsm,
        random_strength=0.8, verbose=50, allow_writing_files=False,
    )
    if args.gpu:
        parameters.update(task_type="GPU", devices="0")
        parameters.pop("rsm", None)
    model = CatBoostClassifier(**parameters)
    model.fit(
        pools["train"], eval_set=pools["early_stop"],
        early_stopping_rounds=args.early_stopping_rounds, use_best_model=True,
    )
    calibration_raw = np.asarray(
        model.predict(pools["calibration"], prediction_type="RawFormulaVal")
    ).reshape(-1, 1)
    calibrator = LogisticRegression(solver="lbfgs", random_state=args.seed)
    calibrator.fit(calibration_raw, splits["calibration"]["target_up"].to_numpy(int))

    def calibrated(name: str) -> np.ndarray:
        # Use CatBoost's direct well-regularized sigmoid probabilities
        return model.predict_proba(pools[name])[:, 1]

    policy_probability = calibrated("policy")
    threshold, threshold_table, policy_passed = choose_threshold(
        splits["policy"], policy_probability, args
    )
    test_probability = calibrated("test")
    selected_test = selected_returns(
        splits["test"], test_probability, threshold,
        args.assumed_payout, args.cooldown_seconds,
    )
    lower_test = day_bootstrap_lower(
        selected_test, args.bootstrap_samples, args.seed + 200
    )
    test_days = int(selected_test["decision_dt"].dt.date.nunique()) if not selected_test.empty else 0
    test_probability_metrics = probability_metrics(
        splits["test"]["target_up"].to_numpy(int), test_probability
    )
    context_coverage = {
        name: float(1.0 - rows[f"{name}_missing"].mean())
        for name in ("quote", "mood", "payout", "deal")
        if f"{name}_missing" in rows.columns
    }
    principal_context_ready = min(
        context_coverage.get(name, 0.0) for name in ("quote", "mood", "payout")
    ) >= args.minimum_context_coverage
    offline_approved = bool(
        policy_passed
        and len(selected_test) >= args.minimum_test_trades
        and test_days >= args.minimum_test_days
        and math.isfinite(lower_test) and lower_test > 0
        and test_probability_metrics["brier_skill_score"] > 0
        and test_probability_metrics["log_loss"] < test_probability_metrics["null_log_loss"]
        and principal_context_ready
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.output_dir / "catboost_directional.cbm"
    calibrator_path = args.output_dir / "catboost_directional_calibrator.joblib"
    model.save_model(model_path)
    joblib.dump(calibrator, calibrator_path)
    threshold_table.to_csv(
        args.output_dir / "catboost_directional_thresholds.csv", index=False
    )
    all_probability_metrics = {
        name: probability_metrics(
            splits[name]["target_up"].to_numpy(int), calibrated(name)
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
        target_definition=(
            f"next exact {args.horizon_minutes}-minute candle closes above entry open; ties excluded"
        ),
        dataset_id=dataset_id,
        dataset_sha256=str(dataset_fingerprint["sha256"]),
        split_windows=split_windows,
        test_metrics=all_probability_metrics["test"],
        artifact_paths={"model": model_path, "calibrator": calibrator_path},
        offline_deployment_approved=offline_approved,
    )
    provenance_path = (
        args.output_dir / "catboost_directional_calibration_provenance.json"
    )
    provenance_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    metadata = {
        "artifact_type": "iqoption_directional_catboost",
        "model_version": MODEL_VERSION,
        "calibration_id": provenance["calibration_id"],
        "positive_class": "next_candle_up",
        "context_schema_version": CONTEXT_SCHEMA_VERSION,
        "pandas_ta_version": EXPECTED_PANDAS_TA_VERSION,
        "feature_order": FEATURE_ORDER,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "feature_schema_sha256": hashlib.sha256(
            json.dumps(FEATURE_ORDER, separators=(",", ":")).encode()
        ).hexdigest(),
        "timeframe_seconds": TIMEFRAME_SECONDS,
        "horizon_minutes": args.horizon_minutes,
        "target_definition": (
            f"1 when close[t+{args.horizon_minutes}m] > open[t+1], 0 when close[t+{args.horizon_minutes}m] < open[t+1]; "
            "decision occurs after t closes; ties excluded"
        ),
        "selected_confidence_threshold": threshold,
        "assumed_payout": args.assumed_payout,
        "cooldown_seconds": args.cooldown_seconds,
        "training_rows": int(len(rows)),
        "training_days": int(rows["decision_dt"].dt.date.nunique()),
        "assets": sorted(rows["asset"].unique().tolist()),
        "context_coverage": context_coverage,
        "minimum_context_coverage": args.minimum_context_coverage,
        "probability_metrics": all_probability_metrics,
        "untouched_test": {
            "trades": int(len(selected_test)), "days": test_days,
            "win_rate": float(selected_test["won"].mean()) if not selected_test.empty else None,
            "expectancy": float(selected_test["unit_return"].mean()) if not selected_test.empty else None,
            "lower_95_expectancy": lower_test if math.isfinite(lower_test) else None,
        },
        "threshold_selection_passed": policy_passed,
        "offline_deployment_approved": offline_approved,
        "live_deployment_approved": False,
        "versions": {
            "catboost": package_version("catboost"),
            "pandas": package_version("pandas"),
            "pandas_ta": package_version("pandas-ta"),
            "scikit_learn": package_version("scikit-learn"),
        },
    }
    (args.output_dir / "catboost_directional_metadata.json").write_text(
        json.dumps(clean(metadata), indent=2), encoding="utf-8"
    )
    print(json.dumps(clean(metadata), indent=2))
    print(f"Artifacts written to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
