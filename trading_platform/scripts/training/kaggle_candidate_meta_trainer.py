#!/usr/bin/env python3
"""
Kaggle-ready IQ Option candidate meta-model trainer.

Purpose
-------
This script does NOT train another unconditional next-candle predictor.
It replays several causal, pre-declared trading setups over historical IQ
Option candles and trains a calibrated CatBoost model to answer:

    "Given that strategy S proposed direction D now, should we accept it?"

The script is standalone. Upload the IQ Option candle CSV to a Kaggle
dataset, paste this file into a notebook cell (or upload and run it), and
execute it. The expected source schema includes:

    asset, timeframe, timestamp, open, close, min, max, volume

Aliases such as high/low/from/at are also accepted.

Important limitations
---------------------
* Historical entry is proxied by the next exact 2-minute candle open.
* It cannot reproduce broker acknowledgement latency, rejected orders,
  changing payout, or the actual accepted strike.
* A successful artifact is for PRACTICE evaluation first, never automatic
  real-money deployment.
* The generated model is a new candidate gate. It must not replace the
  current LSTM file.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import time
import warnings
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)


# =============================================================================
# USER CONFIGURATION
# =============================================================================


@dataclass(frozen=True)
class Config:
    # Leave as None to automatically choose the largest candle-like CSV below
    # /kaggle/input. You can instead use a precise path such as:
    # "/kaggle/input/my-iq-data/candles_export.csv"
    data_path: Optional[str] = None

    output_dir: str = "/kaggle/working/candidate_meta_artifacts"

    entry_timeframe_seconds: int = 120
    higher_timeframes_seconds: Tuple[int, int] = (300, 900)
    expiry_minutes: int = 2
    binary_payout: float = 0.80

    # Native IQ 5m/15m bars are required by default. A 2m series cannot
    # reconstruct exact 5m OHLC boundaries because 5 is not divisible by 2.
    require_native_higher_timeframes: bool = True

    # Global chronological partitions. Threshold policy and final test are
    # separate so the untouched test is not used to choose the threshold.
    train_fraction: float = 0.50
    early_stop_fraction: float = 0.10
    calibration_fraction: float = 0.15
    policy_fraction: float = 0.10
    test_fraction: float = 0.15
    purge_minutes: int = 30

    # Candidate/execution simulation.
    cooldown_seconds_per_asset: int = 300
    minimum_policy_trades: int = 250
    minimum_test_trades: int = 300
    minimum_policy_days: int = 10
    minimum_test_days: int = 14
    bootstrap_samples: int = 2_000
    threshold_step: float = 0.01
    maximum_threshold: float = 0.85

    # CatBoost. CPU is deterministic and normally adequate on Kaggle.
    use_gpu: bool = False
    iterations: int = 1_500
    depth: int = 7
    learning_rate: float = 0.03
    early_stopping_rounds: int = 120

    random_seed: int = 42
    save_generated_candidates: bool = True

    # If CatBoost is absent, Kaggle will normally be able to install its wheel.
    auto_install_catboost: bool = True

    # Set a positive value only for a quick pipeline test. Leave as None for
    # real training. Sampling always keeps the earliest N rows per asset/TF,
    # so this is not suitable for model evaluation.
    smoke_rows_per_asset_timeframe: Optional[int] = None


CFG = Config()


# Columns that the model may use. Raw price levels, outcome prices, and labels
# are intentionally absent.
BASE_NUMERIC_FEATURES = [
    "log_return_1",
    "log_return_2",
    "log_return_3",
    "log_return_5",
    "log_return_10",
    "open_gap_log",
    "high_from_open_log",
    "low_from_open_log",
    "close_from_open_log",
    "range_pct",
    "body_ratio",
    "signed_body_ratio",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "spread",
    "deal_count",
    "call_count",
    "put_count",
    "call_ratio",
    "traders_mood",
    "close_position",
    "dist_ema_20",
    "dist_ema_50",
    "ema_20_slope_3",
    "ema_50_slope_3",
    "rsi_14",
    "stoch_k",
    "stoch_d",
    "bb_percent_b",
    "bb_width",
    "atr_pct",
    "atr_ratio_30",
    "macd_hist_atr",
    "adx_14",
    "realized_vol_10",
    "realized_vol_30",
    "return_zscore_20",
    "trend_efficiency_10",
    "range_compression_10_50",
    "hour_sin",
    "hour_cos",
    "day_sin",
    "day_cos",
]


def set_reproducible(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)


def ensure_catboost(auto_install: bool):
    if importlib.util.find_spec("catboost") is None:
        if not auto_install:
            raise RuntimeError(
                "CatBoost is missing. In a Kaggle cell run: "
                "!pip install -q catboost"
            )
        print("CatBoost is missing; installing it for this Kaggle session...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "catboost"]
        )
    from catboost import CatBoostClassifier, Pool

    return CatBoostClassifier, Pool


def discover_data_path(configured: Optional[str]) -> Path:
    if configured:
        result = Path(configured)
        if not result.is_file():
            raise FileNotFoundError(f"Configured data file does not exist: {result}")
        return result

    roots = [Path("/kaggle/input"), Path("data/ml"), Path(".")]
    candidates: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        candidates.extend(root.rglob("*.csv"))

    if not candidates:
        raise FileNotFoundError(
            "No CSV found. Upload candles_export.csv to Kaggle or set "
            "CFG.data_path to its exact path."
        )

    def score(path: Path) -> Tuple[int, int]:
        name = path.name.lower()
        candle_score = int("candle" in name) + int("export" in name)
        return candle_score, path.stat().st_size

    selected = max(candidates, key=score)
    print(f"Auto-selected candle data: {selected}")
    return selected


def timestamp_to_utc(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_share = float(numeric.notna().mean())
    if numeric_share >= 0.99:
        maximum = float(numeric.abs().max())
        unit = (
            "ns"
            if maximum >= 1e17
            else "us"
            if maximum >= 1e14
            else "ms"
            if maximum >= 1e11
            else "s"
        )
        return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(series, utc=True, errors="coerce")


def load_and_validate_candles(path: Path, cfg: Config) -> pd.DataFrame:
    print(f"Reading {path} ({path.stat().st_size / 1024**2:.1f} MiB)...")
    frame = pd.read_csv(path, low_memory=False)
    aliases = {
        "asset": ("symbol", "instrument"),
        "timeframe": ("interval", "size", "period"),
        "timestamp": ("from", "at", "time", "datetime", "date"),
        "open": ("o",),
        "high": ("max", "h"),
        "low": ("min", "l"),
        "close": ("c",),
        "volume": ("v",),
    }
    lower_to_original = {str(column).lower(): column for column in frame.columns}
    rename: Dict[str, str] = {}
    for target, alternatives in aliases.items():
        if target in lower_to_original:
            rename[lower_to_original[target]] = target
            continue
        for alternative in alternatives:
            if alternative in lower_to_original:
                rename[lower_to_original[alternative]] = target
                break
    frame = frame.rename(columns=rename)

    required = {"asset", "timeframe", "timestamp", "open", "high", "low", "close"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(
            f"Missing required candle columns: {missing}. Found: "
            f"{list(frame.columns)}"
        )

    frame = frame[list(required) + (["volume"] if "volume" in frame else [])].copy()
    frame["asset"] = (
        frame["asset"].astype(str).str.strip().str.upper().str.replace("_", "-", regex=False)
    )
    frame["timeframe"] = pd.to_numeric(frame["timeframe"], errors="coerce")
    frame["timestamp"] = timestamp_to_utc(frame["timestamp"])
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    needed_timeframes = {cfg.entry_timeframe_seconds, *cfg.higher_timeframes_seconds}
    frame = frame.loc[frame["timeframe"].isin(needed_timeframes)].copy()
    frame = frame.dropna(
        subset=["asset", "timeframe", "timestamp", "open", "high", "low", "close"]
    )
    frame["timeframe"] = frame["timeframe"].astype(np.int32)

    positive = (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
    valid_range = (
        frame["high"] >= frame[["open", "close", "low"]].max(axis=1)
    ) & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
    rejected = int((~(positive & valid_range)).sum())
    if rejected:
        print(f"Dropping {rejected:,} invalid OHLC rows.")
    frame = frame.loc[positive & valid_range]
    frame = (
        frame.sort_values(["asset", "timeframe", "timestamp"])
        .drop_duplicates(["asset", "timeframe", "timestamp"], keep="last")
        .reset_index(drop=True)
    )

    if cfg.smoke_rows_per_asset_timeframe:
        frame = (
            frame.groupby(["asset", "timeframe"], group_keys=False)
            .head(cfg.smoke_rows_per_asset_timeframe)
            .reset_index(drop=True)
        )

    if frame.empty:
        raise ValueError("No usable rows remain after normalization.")

    counts = (
        frame.groupby(["timeframe"])["asset"]
        .agg(rows="size", assets="nunique")
        .reset_index()
    )
    print("\nNormalized candle inventory:")
    print(counts.to_string(index=False))
    available = set(frame["timeframe"].unique().tolist())
    if cfg.entry_timeframe_seconds not in available:
        raise ValueError(
            f"Entry timeframe {cfg.entry_timeframe_seconds}s is missing."
        )
    missing_higher = set(cfg.higher_timeframes_seconds).difference(available)
    if missing_higher and cfg.require_native_higher_timeframes:
        raise ValueError(
            "Native higher timeframes are required but missing: "
            f"{sorted(missing_higher)}. Fetch them from IQ Option; exact 5m "
            "candles cannot be reconstructed from 2m bars."
        )
    return frame


def wilder_average(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(
        alpha=1.0 / length, adjust=False, min_periods=length
    ).mean()


def compute_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    average_gain = wilder_average(gain, length)
    average_loss = wilder_average(loss, length)
    rs = average_gain / average_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.where(average_loss.ne(0.0), 100.0).where(
        average_gain.ne(0.0), 0.0
    )


def compute_true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def compute_adx(frame: pd.DataFrame, true_range: pd.Series, length: int = 14):
    up_move = frame["high"].diff()
    down_move = -frame["low"].diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=frame.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=frame.index,
    )
    atr = wilder_average(true_range, length)
    plus_di = 100.0 * wilder_average(plus_dm, length) / atr.replace(0.0, np.nan)
    minus_di = 100.0 * wilder_average(minus_dm, length) / atr.replace(0.0, np.nan)
    dx = (
        100.0
        * (plus_di - minus_di).abs()
        / (plus_di + minus_di).replace(0.0, np.nan)
    )
    return wilder_average(dx, length), plus_di, minus_di, atr


def add_causal_features(raw: pd.DataFrame, timeframe: int) -> pd.DataFrame:
    """Create features using the current completed bar and earlier bars only."""
    frame = raw.sort_values("timestamp").copy().reset_index(drop=True)
    open_price = frame["open"].replace(0.0, np.nan)
    close = frame["close"].replace(0.0, np.nan)
    log_close = np.log(close)
    previous_close = close.shift(1)

    for horizon in (1, 2, 3, 5, 10):
        frame[f"log_return_{horizon}"] = log_close.diff(horizon)

    frame["open_gap_log"] = np.log(open_price / previous_close)
    frame["high_from_open_log"] = np.log(frame["high"] / open_price)
    frame["low_from_open_log"] = np.log(frame["low"] / open_price)
    frame["close_from_open_log"] = np.log(close / open_price)
    frame["range_pct"] = (frame["high"] - frame["low"]) / close

    candle_range = (frame["high"] - frame["low"]).replace(0.0, np.nan)
    signed_body = frame["close"] - frame["open"]
    frame["body_ratio"] = signed_body.abs() / candle_range
    frame["signed_body_ratio"] = signed_body / candle_range
    frame["upper_wick_ratio"] = (
        frame["high"] - frame[["open", "close"]].max(axis=1)
    ) / candle_range
    frame["lower_wick_ratio"] = (
        frame[["open", "close"]].min(axis=1) - frame["low"]
    ) / candle_range
    frame["close_position"] = (frame["close"] - frame["low"]) / candle_range

    ema_12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema_20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
    ema_26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    ema_50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
    frame["dist_ema_20"] = (close - ema_20) / ema_20
    frame["dist_ema_50"] = (close - ema_50) / ema_50
    frame["low_dist_ema_20"] = (frame["low"] - ema_20) / ema_20
    frame["high_dist_ema_20"] = (frame["high"] - ema_20) / ema_20
    frame["ema_20_slope_3"] = np.log(ema_20 / ema_20.shift(3))
    frame["ema_50_slope_3"] = np.log(ema_50 / ema_50.shift(3))

    frame["rsi_14"] = compute_rsi(close, 14) / 100.0
    low_14 = frame["low"].rolling(14, min_periods=14).min()
    high_14 = frame["high"].rolling(14, min_periods=14).max()
    stoch_k = 100.0 * (close - low_14) / (high_14 - low_14).replace(0.0, np.nan)
    frame["stoch_k"] = stoch_k / 100.0
    frame["stoch_d"] = stoch_k.rolling(3, min_periods=3).mean() / 100.0

    rolling_mean_20 = close.rolling(20, min_periods=20).mean()
    rolling_std_20 = close.rolling(20, min_periods=20).std(ddof=0)
    bb_upper = rolling_mean_20 + 2.0 * rolling_std_20
    bb_lower = rolling_mean_20 - 2.0 * rolling_std_20
    frame["bb_percent_b"] = (
        (close - bb_lower) / (bb_upper - bb_lower).replace(0.0, np.nan)
    )
    frame["bb_width"] = (bb_upper - bb_lower) / rolling_mean_20

    true_range = compute_true_range(frame)
    adx, plus_di, minus_di, atr = compute_adx(frame, true_range, 14)
    frame["atr_pct"] = atr / close
    frame["atr_ratio_30"] = frame["atr_pct"] / frame["atr_pct"].rolling(
        30, min_periods=30
    ).median()
    frame["adx_14"] = adx / 100.0
    frame["plus_di_14"] = plus_di / 100.0
    frame["minus_di_14"] = minus_di / 100.0

    macd = ema_12 - ema_26
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    frame["macd_hist_atr"] = (macd - macd_signal) / atr.replace(0.0, np.nan)

    one_return = frame["log_return_1"]
    frame["realized_vol_10"] = one_return.rolling(10, min_periods=10).std(ddof=0)
    frame["realized_vol_30"] = one_return.rolling(30, min_periods=30).std(ddof=0)
    return_mean = one_return.rolling(20, min_periods=20).mean()
    return_std = one_return.rolling(20, min_periods=20).std(ddof=0)
    frame["return_zscore_20"] = (
        one_return - return_mean
    ) / return_std.replace(0.0, np.nan)

    absolute_path = close.diff().abs().rolling(10, min_periods=10).sum()
    frame["trend_efficiency_10"] = (
        close.diff(10).abs() / absolute_path.replace(0.0, np.nan)
    )
    range_average_10 = frame["range_pct"].rolling(10, min_periods=10).mean()
    range_average_50 = frame["range_pct"].rolling(50, min_periods=50).mean()
    frame["range_compression_10_50"] = (
        range_average_10 / range_average_50.replace(0.0, np.nan)
    )

    # These are used only by pre-declared candidate rules. shift(1) ensures
    # today's breakout boundary was known before the current candle formed.
    frame["previous_high_20"] = frame["high"].rolling(
        20, min_periods=20
    ).max().shift(1)
    frame["previous_low_20"] = frame["low"].rolling(
        20, min_periods=20
    ).min().shift(1)
    frame["previous_compression"] = frame["range_compression_10_50"].shift(1)

    minute_of_day = frame["timestamp"].dt.hour * 60 + frame["timestamp"].dt.minute
    hour_angle = 2.0 * np.pi * minute_of_day / 1440.0
    day_angle = 2.0 * np.pi * frame["timestamp"].dt.dayofweek / 7.0
    frame["hour_sin"] = np.sin(hour_angle)
    frame["hour_cos"] = np.cos(hour_angle)
    frame["day_sin"] = np.sin(day_angle)
    frame["day_cos"] = np.cos(day_angle)

    # A bar becomes usable only at its close, never at its opening timestamp.
    frame["available_time"] = frame["timestamp"] + pd.to_timedelta(
        timeframe, unit="s"
    )
    return frame.replace([np.inf, -np.inf], np.nan)


def prefix_higher_timeframe(
    frame: pd.DataFrame, timeframe: int
) -> pd.DataFrame:
    selected = ["available_time"] + [
        column for column in BASE_NUMERIC_FEATURES if column in frame.columns
    ]
    result = frame[selected].copy()
    return result.rename(
        columns={
            column: f"tf{timeframe}_{column}"
            for column in selected
            if column != "available_time"
        }
    )


def align_asset_timeframes(
    asset_frame: pd.DataFrame, asset: str, cfg: Config
) -> pd.DataFrame:
    entry_raw = asset_frame.loc[
        asset_frame["timeframe"].eq(cfg.entry_timeframe_seconds)
    ]
    if entry_raw.empty:
        return pd.DataFrame()
    entry = add_causal_features(entry_raw, cfg.entry_timeframe_seconds)
    entry["decision_time_dt"] = entry["available_time"]

    for timeframe in cfg.higher_timeframes_seconds:
        higher_raw = asset_frame.loc[asset_frame["timeframe"].eq(timeframe)]
        if higher_raw.empty:
            for feature in BASE_NUMERIC_FEATURES:
                entry[f"tf{timeframe}_{feature}"] = np.nan
            continue
        higher = prefix_higher_timeframe(
            add_causal_features(higher_raw, timeframe), timeframe
        ).sort_values("available_time")
        entry = pd.merge_asof(
            entry.sort_values("decision_time_dt"),
            higher,
            left_on="decision_time_dt",
            right_on="available_time",
            direction="backward",
            allow_exact_matches=True,
        )
        entry = entry.drop(columns=["available_time_y"], errors="ignore")
        if "available_time_x" in entry:
            entry = entry.rename(columns={"available_time_x": "available_time"})

    entry["asset"] = asset
    return entry.sort_values("timestamp").reset_index(drop=True)


def add_execution_proxy(frame: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    duration_seconds = cfg.expiry_minutes * 60
    if duration_seconds % cfg.entry_timeframe_seconds:
        raise ValueError(
            "expiry_minutes must produce a duration divisible by the entry "
            "timeframe. For 120s bars use 2, 4, 6, ... minutes."
        )
    steps = duration_seconds // cfg.entry_timeframe_seconds
    result = frame.copy()
    result["entry_price_proxy"] = result["open"].shift(-1)
    result["settlement_price_proxy"] = result["close"].shift(-steps)
    next_start = result["timestamp"].shift(-1)
    settlement_start = result["timestamp"].shift(-steps)
    expected_entry_start = result["timestamp"] + pd.to_timedelta(
        cfg.entry_timeframe_seconds, unit="s"
    )
    expected_settlement_start = result["timestamp"] + pd.to_timedelta(
        duration_seconds, unit="s"
    )
    result["execution_path_valid"] = (
        next_start.eq(expected_entry_start)
        & settlement_start.eq(expected_settlement_start)
    )
    result["decision_time"] = (
        result["decision_time_dt"].astype("int64") // 1_000_000_000
    ).astype("int64")
    result["expiry_time"] = result["decision_time"] + duration_seconds
    return result


def mask_score(condition: pd.Series, raw_score: pd.Series) -> pd.Series:
    return raw_score.where(condition, np.nan).clip(0.0, 1.0)


def declared_candidate_rules(frame: pd.DataFrame) -> List[Tuple[str, str, pd.Series]]:
    """
    Return a fixed family of causal setup rules.

    These rules are intentionally declared once before testing. Do not keep
    changing them after seeing final-test results; doing so consumes the test
    set and creates backtest overfitting.
    """
    rsi = frame["rsi_14"]
    adx = frame["adx_14"]
    body = frame["body_ratio"]
    signed_body = frame["signed_body_ratio"]
    macd = frame["macd_hist_atr"]
    ret_z = frame["return_zscore_20"]

    trend_up = (
        frame["dist_ema_50"].gt(0)
        & frame["ema_20_slope_3"].gt(0)
        & frame["ema_50_slope_3"].gt(0)
    )
    trend_down = (
        frame["dist_ema_50"].lt(0)
        & frame["ema_20_slope_3"].lt(0)
        & frame["ema_50_slope_3"].lt(0)
    )

    pullback_call = (
        trend_up
        & frame["low_dist_ema_20"].le(0)
        & frame["dist_ema_20"].gt(0)
        & rsi.between(0.45, 0.72)
        & adx.gt(0.15)
    )
    pullback_put = (
        trend_down
        & frame["high_dist_ema_20"].ge(0)
        & frame["dist_ema_20"].lt(0)
        & rsi.between(0.28, 0.55)
        & adx.gt(0.15)
    )
    pullback_strength = (
        0.35 * adx.clip(0, 1)
        + 0.35 * frame["trend_efficiency_10"].clip(0, 1)
        + 0.30 * body.clip(0, 1)
    )

    cascade_call = (
        trend_up
        & frame["log_return_1"].gt(0)
        & frame["log_return_2"].gt(0)
        & frame["log_return_3"].gt(0)
        & macd.gt(0)
        & rsi.between(0.50, 0.78)
        & body.between(0.20, 0.85)
    )
    cascade_put = (
        trend_down
        & frame["log_return_1"].lt(0)
        & frame["log_return_2"].lt(0)
        & frame["log_return_3"].lt(0)
        & macd.lt(0)
        & rsi.between(0.22, 0.50)
        & body.between(0.20, 0.85)
    )
    cascade_strength = (
        0.30 * adx.clip(0, 1)
        + 0.30 * frame["trend_efficiency_10"].clip(0, 1)
        + 0.20 * body.clip(0, 1)
        + 0.20 * (macd.abs() / 0.25).clip(0, 1)
    )

    breakout_call = (
        frame["close"].gt(frame["previous_high_20"])
        & signed_body.gt(0.35)
        & frame["close_position"].gt(0.75)
        & frame["atr_ratio_30"].between(0.75, 2.25)
    )
    breakout_put = (
        frame["close"].lt(frame["previous_low_20"])
        & signed_body.lt(-0.35)
        & frame["close_position"].lt(0.25)
        & frame["atr_ratio_30"].between(0.75, 2.25)
    )
    breakout_distance_call = (
        (frame["close"] - frame["previous_high_20"])
        / frame["close"].replace(0.0, np.nan)
    )
    breakout_distance_put = (
        (frame["previous_low_20"] - frame["close"])
        / frame["close"].replace(0.0, np.nan)
    )
    breakout_strength_call = (
        0.45 * body.clip(0, 1)
        + 0.30 * frame["close_position"].clip(0, 1)
        + 0.25 * (breakout_distance_call / frame["atr_pct"]).clip(0, 1)
    )
    breakout_strength_put = (
        0.45 * body.clip(0, 1)
        + 0.30 * (1.0 - frame["close_position"]).clip(0, 1)
        + 0.25 * (breakout_distance_put / frame["atr_pct"]).clip(0, 1)
    )

    compressed = frame["previous_compression"].lt(0.80)
    compression_call = (
        compressed
        & breakout_call
        & frame["range_compression_10_50"].gt(
            frame["previous_compression"] * 1.05
        )
    )
    compression_put = (
        compressed
        & breakout_put
        & frame["range_compression_10_50"].gt(
            frame["previous_compression"] * 1.05
        )
    )
    compression_strength = (
        0.45 * (1.0 - frame["previous_compression"]).clip(0, 1)
        + 0.35 * body.clip(0, 1)
        + 0.20 * frame["atr_ratio_30"].clip(0, 1)
    )

    mean_reversion_call = (
        frame["bb_percent_b"].lt(-0.05)
        & rsi.lt(0.32)
        & frame["lower_wick_ratio"].gt(0.20)
        & frame["close_position"].gt(0.25)
        & adx.lt(0.35)
    )
    mean_reversion_put = (
        frame["bb_percent_b"].gt(1.05)
        & rsi.gt(0.68)
        & frame["upper_wick_ratio"].gt(0.20)
        & frame["close_position"].lt(0.75)
        & adx.lt(0.35)
    )
    mean_reversion_strength_call = (
        0.35 * ((0.32 - rsi) / 0.32).clip(0, 1)
        + 0.35 * frame["lower_wick_ratio"].clip(0, 1)
        + 0.30 * (-frame["bb_percent_b"]).clip(0, 1)
    )
    mean_reversion_strength_put = (
        0.35 * ((rsi - 0.68) / 0.32).clip(0, 1)
        + 0.35 * frame["upper_wick_ratio"].clip(0, 1)
        + 0.30 * (frame["bb_percent_b"] - 1.0).clip(0, 1)
    )

    exhaustion_call = (
        ret_z.lt(-1.75)
        & frame["lower_wick_ratio"].gt(0.30)
        & frame["close_position"].gt(0.45)
        & rsi.lt(0.42)
    )
    exhaustion_put = (
        ret_z.gt(1.75)
        & frame["upper_wick_ratio"].gt(0.30)
        & frame["close_position"].lt(0.55)
        & rsi.gt(0.58)
    )
    exhaustion_strength_call = (
        0.40 * (-ret_z / 3.0).clip(0, 1)
        + 0.35 * frame["lower_wick_ratio"].clip(0, 1)
        + 0.25 * (1.0 - rsi).clip(0, 1)
    )
    exhaustion_strength_put = (
        0.40 * (ret_z / 3.0).clip(0, 1)
        + 0.35 * frame["upper_wick_ratio"].clip(0, 1)
        + 0.25 * rsi.clip(0, 1)
    )

    return [
        ("trend_pullback", "call", mask_score(pullback_call, pullback_strength)),
        ("trend_pullback", "put", mask_score(pullback_put, pullback_strength)),
        ("momentum_cascade", "call", mask_score(cascade_call, cascade_strength)),
        ("momentum_cascade", "put", mask_score(cascade_put, cascade_strength)),
        ("range_breakout", "call", mask_score(breakout_call, breakout_strength_call)),
        ("range_breakout", "put", mask_score(breakout_put, breakout_strength_put)),
        (
            "compression_breakout",
            "call",
            mask_score(compression_call, compression_strength),
        ),
        (
            "compression_breakout",
            "put",
            mask_score(compression_put, compression_strength),
        ),
        (
            "bb_mean_reversion",
            "call",
            mask_score(mean_reversion_call, mean_reversion_strength_call),
        ),
        (
            "bb_mean_reversion",
            "put",
            mask_score(mean_reversion_put, mean_reversion_strength_put),
        ),
        (
            "exhaustion_fade",
            "call",
            mask_score(exhaustion_call, exhaustion_strength_call),
        ),
        (
            "exhaustion_fade",
            "put",
            mask_score(exhaustion_put, exhaustion_strength_put),
        ),
    ]


def model_feature_columns(cfg: Config) -> Tuple[List[str], List[str]]:
    numeric = list(BASE_NUMERIC_FEATURES)
    for timeframe in cfg.higher_timeframes_seconds:
        numeric.extend(f"tf{timeframe}_{name}" for name in BASE_NUMERIC_FEATURES)
    numeric.extend(
        [
            "strategy_score",
            "mtf_direction_alignment",
            "mtf_trend_strength",
            "payout_breakeven",
        ]
    )
    categorical = ["asset", "direction", "strategy", "volatility_regime"]
    return numeric, categorical


def classify_volatility(frame: pd.DataFrame) -> pd.Series:
    ratio = frame["atr_ratio_30"]
    return pd.Series(
        np.select(
            [ratio.lt(0.75), ratio.lt(1.25), ratio.lt(1.75)],
            ["low", "normal", "high"],
            default="extreme",
        ),
        index=frame.index,
        dtype="object",
    ).where(ratio.notna(), "unknown")


def generate_asset_candidates(
    aligned: pd.DataFrame, cfg: Config
) -> pd.DataFrame:
    frame = add_execution_proxy(aligned, cfg)
    frame["volatility_regime"] = classify_volatility(frame)

    # Compact MTF summary available to every setup. Distances and slopes were
    # aligned using only higher-timeframe candles closed by decision time.
    signs: List[pd.Series] = [
        np.sign(frame["ema_20_slope_3"]).fillna(0.0)
    ]
    strengths: List[pd.Series] = [
        frame["trend_efficiency_10"].fillna(0.0)
    ]
    for timeframe in cfg.higher_timeframes_seconds:
        signs.append(
            np.sign(frame[f"tf{timeframe}_ema_20_slope_3"]).fillna(0.0)
        )
        strengths.append(
            frame[f"tf{timeframe}_trend_efficiency_10"].fillna(0.0)
        )
    sign_table = pd.concat(signs, axis=1)
    strength_table = pd.concat(strengths, axis=1)

    numeric_features, categorical_features = model_feature_columns(cfg)
    common = [
        "decision_time",
        "expiry_time",
        "entry_price_proxy",
        "settlement_price_proxy",
        "execution_path_valid",
        *[name for name in numeric_features if name in frame.columns],
        *[name for name in categorical_features if name in frame.columns],
    ]
    pieces: List[pd.DataFrame] = []
    breakeven = 1.0 / (1.0 + cfg.binary_payout)

    for strategy, direction, score in declared_candidate_rules(frame):
        selected = score.notna() & frame["execution_path_valid"]
        if not selected.any():
            continue
        piece = frame.loc[selected, common].copy()
        piece["strategy"] = strategy
        piece["direction"] = direction
        piece["strategy_score"] = score.loc[selected].astype(float)
        direction_sign = 1.0 if direction == "call" else -1.0
        piece["mtf_direction_alignment"] = (
            sign_table.loc[selected].mul(direction_sign).mean(axis=1)
        )
        piece["mtf_trend_strength"] = strength_table.loc[selected].mean(axis=1)
        piece["payout_breakeven"] = breakeven
        call_won = piece["settlement_price_proxy"].gt(
            piece["entry_price_proxy"]
        )
        tied = piece["settlement_price_proxy"].eq(piece["entry_price_proxy"])
        piece["label"] = (
            call_won if direction == "call" else ~call_won
        ).astype(np.int8)
        piece["outcome"] = np.where(
            tied, "tie", np.where(piece["label"].eq(1), "win", "loss")
        )
        piece.loc[tied, "label"] = -1
        pieces.append(piece)

    if not pieces:
        return pd.DataFrame()
    candidates = pd.concat(pieces, ignore_index=True)
    candidates = candidates.loc[candidates["label"].isin([0, 1])].copy()
    candidates["label"] = candidates["label"].astype(np.int8)
    return candidates.sort_values(["decision_time", "asset", "strategy"])


def build_candidates(candles: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    pieces: List[pd.DataFrame] = []
    assets = sorted(candles["asset"].unique().tolist())
    print(f"\nGenerating causal candidates for {len(assets)} assets...")
    started = time.time()
    for index, asset in enumerate(assets, 1):
        asset_frame = candles.loc[candles["asset"].eq(asset)]
        aligned = align_asset_timeframes(asset_frame, asset, cfg)
        candidate = generate_asset_candidates(aligned, cfg)
        if not candidate.empty:
            pieces.append(candidate)
        print(
            f"[{index:02d}/{len(assets):02d}] {asset}: "
            f"{len(candidate):,} candidates"
        )
    if not pieces:
        raise ValueError(
            "No candidates were produced. Check candle history length and schema."
        )
    result = pd.concat(pieces, ignore_index=True).sort_values(
        ["decision_time", "asset", "strategy"]
    )
    print(
        f"Generated {len(result):,} resolved non-tie candidates in "
        f"{time.time() - started:.1f}s."
    )
    print("\nCandidate inventory:")
    print(
        result.groupby(["strategy", "direction"])["label"]
        .agg(candidates="size", win_rate="mean")
        .to_string()
    )
    return result.reset_index(drop=True)


def temporal_split(
    frame: pd.DataFrame, cfg: Config
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, int]]:
    fractions = np.asarray(
        [
            cfg.train_fraction,
            cfg.early_stop_fraction,
            cfg.calibration_fraction,
            cfg.policy_fraction,
            cfg.test_fraction,
        ],
        dtype=float,
    )
    if not np.isclose(fractions.sum(), 1.0):
        raise ValueError(f"Temporal split fractions must sum to 1, got {fractions.sum()}")

    timeline = np.sort(frame["decision_time"].unique())
    if len(timeline) < 100:
        raise ValueError("Too few unique timestamps for strict temporal splitting.")
    cumulative = np.cumsum(fractions)[:-1]
    cutoffs = [
        int(timeline[min(len(timeline) - 1, max(0, int(len(timeline) * q) - 1))])
        for q in cumulative
    ]
    purge = cfg.purge_minutes * 60
    names = ["train", "early_stop", "calibration", "policy", "test"]
    lower = [-np.inf] + [cutoff + purge for cutoff in cutoffs]
    upper = [cutoff - purge for cutoff in cutoffs] + [np.inf]
    parts: Dict[str, pd.DataFrame] = {}
    for name, low, high in zip(names, lower, upper):
        mask = frame["decision_time"].gt(low) & frame["decision_time"].le(high)
        part = frame.loc[mask].copy()
        if part.empty:
            raise ValueError(
                f"Temporal partition {name!r} is empty. Reduce purge_minutes "
                "only if this is a very small smoke test."
            )
        parts[name] = part
        date_min = pd.to_datetime(part["decision_time"].min(), unit="s", utc=True)
        date_max = pd.to_datetime(part["decision_time"].max(), unit="s", utc=True)
        print(
            f"{name:12s} rows={len(part):8,d}  "
            f"win_rate={part.label.mean():.3%}  {date_min} -> {date_max}"
        )
    return parts, {
        "train_end": cutoffs[0],
        "early_stop_end": cutoffs[1],
        "calibration_end": cutoffs[2],
        "policy_end": cutoffs[3],
        "purge_seconds": purge,
    }


def prepare_model_frame(
    frame: pd.DataFrame,
    numeric_features: Sequence[str],
    categorical_features: Sequence[str],
) -> pd.DataFrame:
    result = frame[list(numeric_features) + list(categorical_features)].copy()
    for column in numeric_features:
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(
            np.float32
        )
    for column in categorical_features:
        result[column] = result[column].fillna("unknown").astype(str)
    return result.replace([np.inf, -np.inf], np.nan)


def expected_calibration_error(
    labels: np.ndarray, probability: np.ndarray, bins: int = 10
) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    assignments = np.digitize(probability, edges[1:-1], right=True)
    error = 0.0
    for index in range(bins):
        selected = assignments == index
        if selected.any():
            error += (
                selected.mean()
                * abs(labels[selected].mean() - probability[selected].mean())
            )
    return float(error)


def probability_metrics(labels: np.ndarray, probability: np.ndarray) -> Dict[str, float]:
    labels = np.asarray(labels, dtype=int)
    probability = np.asarray(probability, dtype=float).clip(1e-7, 1 - 1e-7)
    return {
        "roc_auc": float(roc_auc_score(labels, probability)),
        "accuracy_at_0_5": float(accuracy_score(labels, probability >= 0.5)),
        "log_loss": float(log_loss(labels, probability)),
        "brier_score": float(brier_score_loss(labels, probability)),
        "ece_10_bins": expected_calibration_error(labels, probability, 10),
        "base_win_rate": float(labels.mean()),
    }


def accepted_indices(
    probability: np.ndarray,
    assets: np.ndarray,
    times: np.ndarray,
    threshold: float,
    cooldown_seconds: int,
) -> np.ndarray:
    indices = np.flatnonzero(probability >= threshold)
    if indices.size == 0:
        return indices
    table = pd.DataFrame(
        {
            "index": indices,
            "asset": assets[indices],
            "time": times[indices],
            "probability": probability[indices],
        }
    )
    # Multiple strategies can propose the same asset/direction at one time.
    # Keep only the model's strongest candidate for that asset and timestamp.
    table = (
        table.sort_values(
            ["time", "asset", "probability"],
            ascending=[True, True, False],
        )
        .drop_duplicates(["time", "asset"], keep="first")
        .sort_values(["time", "probability"], ascending=[True, False])
    )
    accepted: List[int] = []
    last_time: Dict[str, int] = {}
    for row in table.itertuples(index=False):
        previous = last_time.get(row.asset)
        if previous is not None and row.time - previous < cooldown_seconds:
            continue
        accepted.append(int(row.index))
        last_time[row.asset] = int(row.time)
    return np.asarray(accepted, dtype=np.int64)


def expectancy(win_rate: float, payout: float) -> float:
    return win_rate * payout - (1.0 - win_rate)


def block_bootstrap_lower_win_rate(
    wins: np.ndarray,
    timestamps: np.ndarray,
    samples: int,
    seed: int,
) -> float:
    days = timestamps // 86_400
    unique_days = np.unique(days)
    if len(unique_days) < 2:
        return float("nan")
    daily_wins = np.asarray([wins[days == day].sum() for day in unique_days])
    daily_count = np.asarray([(days == day).sum() for day in unique_days])
    rng = np.random.default_rng(seed)
    boot = np.empty(samples, dtype=float)
    for index in range(samples):
        chosen = rng.integers(0, len(unique_days), len(unique_days))
        boot[index] = daily_wins[chosen].sum() / daily_count[chosen].sum()
    return float(np.quantile(boot, 0.025))


def trading_metrics(
    probability: np.ndarray,
    labels: np.ndarray,
    assets: np.ndarray,
    timestamps: np.ndarray,
    threshold: float,
    cfg: Config,
    seed: int,
) -> Dict[str, float]:
    selected = accepted_indices(
        probability,
        assets,
        timestamps,
        threshold,
        cfg.cooldown_seconds_per_asset,
    )
    if selected.size == 0:
        return {
            "threshold": float(threshold),
            "trades": 0,
            "days": 0,
            "coverage": 0.0,
            "win_rate": None,
            "lower_95_win_rate": None,
            "expectancy_per_unit": None,
            "lower_95_expectancy_per_unit": None,
        }
    wins = labels[selected].astype(float)
    selected_times = timestamps[selected]
    lower = block_bootstrap_lower_win_rate(
        wins, selected_times, cfg.bootstrap_samples, seed
    )
    win_rate = float(wins.mean())
    return {
        "threshold": float(threshold),
        "trades": int(len(selected)),
        "days": int(np.unique(selected_times // 86_400).size),
        "coverage": float(len(selected) / len(labels)),
        "win_rate": win_rate,
        "lower_95_win_rate": lower if math.isfinite(lower) else None,
        "expectancy_per_unit": expectancy(win_rate, cfg.binary_payout),
        "lower_95_expectancy_per_unit": (
            expectancy(lower, cfg.binary_payout)
            if math.isfinite(lower)
            else None
        ),
    }


def choose_policy_threshold(
    probability: np.ndarray,
    labels: np.ndarray,
    assets: np.ndarray,
    timestamps: np.ndarray,
    cfg: Config,
) -> Tuple[float, pd.DataFrame, bool]:
    breakeven = 1.0 / (1.0 + cfg.binary_payout)
    start = math.ceil(breakeven / cfg.threshold_step) * cfg.threshold_step
    thresholds = np.arange(
        start,
        cfg.maximum_threshold + cfg.threshold_step / 2,
        cfg.threshold_step,
    )
    rows = [
        trading_metrics(
            probability,
            labels,
            assets,
            timestamps,
            float(threshold),
            cfg,
            cfg.random_seed + index,
        )
        for index, threshold in enumerate(thresholds)
    ]
    table = pd.DataFrame(rows)
    eligible = table.loc[
        table["trades"].ge(cfg.minimum_policy_trades)
        & table["days"].ge(cfg.minimum_policy_days)
        & table["lower_95_expectancy_per_unit"].notna()
        & table["lower_95_expectancy_per_unit"].gt(0.0)
    ]
    if eligible.empty:
        # Still return the theoretical breakeven threshold, but explicitly
        # mark the policy as failed. The artifact must not be live-approved.
        return float(start), table, False
    best = eligible.sort_values(
        ["lower_95_expectancy_per_unit", "trades"],
        ascending=[False, False],
    ).iloc[0]
    return float(best["threshold"]), table, True


def clean_json(value):
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def save_candidate_data(frame: pd.DataFrame, output: Path) -> str:
    parquet_path = output / "offline_candidates.parquet"
    try:
        frame.to_parquet(parquet_path, index=False)
        return str(parquet_path)
    except (ImportError, ModuleNotFoundError):
        csv_path = output / "offline_candidates.csv.gz"
        print("pyarrow is unavailable; saving candidates as compressed CSV.")
        frame.to_csv(csv_path, index=False, compression="gzip")
        return str(csv_path)


def fit_and_evaluate(
    candidates: pd.DataFrame,
    cfg: Config,
    output: Path,
) -> Dict[str, object]:
    CatBoostClassifier, Pool = ensure_catboost(cfg.auto_install_catboost)
    splits, split_cutoffs = temporal_split(candidates, cfg)
    numeric_features, categorical_features = model_feature_columns(cfg)
    feature_columns = numeric_features + categorical_features
    categorical_indices = [
        feature_columns.index(column) for column in categorical_features
    ]

    pools = {}
    for name, part in splits.items():
        pools[name] = Pool(
            prepare_model_frame(part, numeric_features, categorical_features),
            label=part["label"].astype(int),
            cat_features=categorical_indices,
        )

    parameters = dict(
        iterations=cfg.iterations,
        depth=cfg.depth,
        learning_rate=cfg.learning_rate,
        loss_function="Logloss",
        eval_metric="AUC",
        random_seed=cfg.random_seed,
        l2_leaf_reg=7.0,
        random_strength=0.5,
        verbose=50,
        allow_writing_files=False,
        thread_count=-1,
    )
    if cfg.use_gpu:
        parameters.update(task_type="GPU", devices="0")

    model = CatBoostClassifier(**parameters)
    print("\nTraining CatBoost candidate gate...")
    model.fit(
        pools["train"],
        eval_set=pools["early_stop"],
        early_stopping_rounds=cfg.early_stopping_rounds,
        use_best_model=True,
    )

    # Platt calibration uses its own period, never the policy or test periods.
    calibration_raw = np.asarray(
        model.predict(pools["calibration"], prediction_type="RawFormulaVal")
    ).reshape(-1, 1)
    calibrator = LogisticRegression(
        solver="lbfgs", random_state=cfg.random_seed
    )
    calibrator.fit(
        calibration_raw, splits["calibration"]["label"].to_numpy(dtype=int)
    )

    def calibrated(name: str) -> np.ndarray:
        raw = np.asarray(
            model.predict(pools[name], prediction_type="RawFormulaVal")
        ).reshape(-1, 1)
        return calibrator.predict_proba(raw)[:, 1]

    calibration_probability = calibrated("calibration")
    policy_probability = calibrated("policy")
    policy = splits["policy"]
    threshold, threshold_table, policy_passed = choose_policy_threshold(
        policy_probability,
        policy["label"].to_numpy(dtype=int),
        policy["asset"].to_numpy(dtype=str),
        policy["decision_time"].to_numpy(dtype=np.int64),
        cfg,
    )
    policy_trade_metrics = trading_metrics(
        policy_probability,
        policy["label"].to_numpy(dtype=int),
        policy["asset"].to_numpy(dtype=str),
        policy["decision_time"].to_numpy(dtype=np.int64),
        threshold,
        cfg,
        cfg.random_seed + 10_000,
    )

    test = splits["test"]
    test_probability = calibrated("test")
    test_labels = test["label"].to_numpy(dtype=int)
    test_trade_metrics = trading_metrics(
        test_probability,
        test_labels,
        test["asset"].to_numpy(dtype=str),
        test["decision_time"].to_numpy(dtype=np.int64),
        threshold,
        cfg,
        cfg.random_seed + 20_000,
    )

    probability_report = {
        "calibration": probability_metrics(
            splits["calibration"]["label"].to_numpy(dtype=int),
            calibration_probability,
        ),
        "policy": probability_metrics(
            policy["label"].to_numpy(dtype=int), policy_probability
        ),
        "test": probability_metrics(test_labels, test_probability),
    }

    lower_test_expectancy = test_trade_metrics.get(
        "lower_95_expectancy_per_unit"
    )
    deployment_approved = bool(
        policy_passed
        and lower_test_expectancy is not None
        and lower_test_expectancy > 0.0
        and test_trade_metrics["trades"] >= cfg.minimum_test_trades
        and test_trade_metrics["days"] >= cfg.minimum_test_days
    )

    model_path = output / "candidate_meta_model.cbm"
    calibrator_path = output / "candidate_calibrator.joblib"
    model.save_model(model_path)
    joblib.dump(calibrator, calibrator_path)
    threshold_table.to_csv(output / "policy_thresholds.csv", index=False)

    importance = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": model.get_feature_importance(pools["train"]),
        }
    ).sort_values("importance", ascending=False)
    importance.to_csv(output / "feature_importance.csv", index=False)

    predictions = test[
        [
            "decision_time",
            "expiry_time",
            "asset",
            "strategy",
            "direction",
            "strategy_score",
            "label",
        ]
    ].copy()
    predictions["probability_win"] = test_probability
    predictions["accepted"] = False
    selected = accepted_indices(
        test_probability,
        test["asset"].to_numpy(dtype=str),
        test["decision_time"].to_numpy(dtype=np.int64),
        threshold,
        cfg.cooldown_seconds_per_asset,
    )
    predictions.iloc[
        selected, predictions.columns.get_loc("accepted")
    ] = True
    predictions.to_csv(output / "untouched_test_predictions.csv", index=False)

    accepted_test = predictions.loc[predictions["accepted"]]
    if accepted_test.empty:
        breakdown = pd.DataFrame()
    else:
        breakdown = (
            accepted_test.groupby(["asset", "strategy"])
            .agg(
                trades=("label", "size"),
                win_rate=("label", "mean"),
                mean_probability=("probability_win", "mean"),
            )
            .reset_index()
            .sort_values(["trades", "win_rate"], ascending=[False, False])
        )
    breakdown.to_csv(output / "accepted_test_breakdown.csv", index=False)

    metadata = {
        "artifact_type": "iqoption_candidate_meta_gate",
        "model_version": "candidate_meta_catboost_offline_v2",
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "training_mode": "offline_strategy_replay",
        "entry_proxy": "next_exact_2m_candle_open",
        "settlement_proxy": "exact_expiry_candle_close",
        "practice_only": True,
        "broker_execution_verified": False,
        "config": asdict(cfg),
        "features": feature_columns,
        "numeric_features": numeric_features,
        "categorical_features": categorical_features,
        "candidate_strategies": sorted(candidates["strategy"].unique().tolist()),
        "assets": sorted(candidates["asset"].unique().tolist()),
        "resolved_candidates": len(candidates),
        "split_cutoffs": split_cutoffs,
        "selected_threshold": threshold,
        "policy_threshold_passed": policy_passed,
        "probability_metrics": probability_report,
        "policy_trading_metrics": policy_trade_metrics,
        "untouched_test_trading_metrics": test_trade_metrics,
        "offline_deployment_approved": deployment_approved,
        "live_deployment_approved": False,
        "limitations": [
            "No broker acknowledgement/accepted-strike simulation",
            "No rejected-order simulation",
            "No historical payout variation unless encoded in source data",
            "Must be validated in IQ Option PRACTICE mode",
        ],
    }
    with (output / "candidate_meta_metadata.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(clean_json(metadata), handle, indent=2)

    print("\n================ UNTOUCHED FINAL TEST ================")
    print(json.dumps(clean_json(probability_report["test"]), indent=2))
    print("\nPayout-aware accepted-trade result:")
    print(json.dumps(clean_json(test_trade_metrics), indent=2))
    print(f"\noffline_deployment_approved={deployment_approved}")
    print("live_deployment_approved=False (PRACTICE verification is still required)")
    return metadata


def write_readme(output: Path, metadata: Dict[str, object]) -> None:
    approved = metadata["offline_deployment_approved"]
    threshold = metadata["selected_threshold"]
    text = f"""IQ OPTION CANDIDATE META-GATE
================================

Offline approval: {approved}
Selected probability threshold: {threshold:.2%}
Live approval: False

Files
-----
candidate_meta_model.cbm
    CatBoost accept/reject model.

candidate_calibrator.joblib
    Platt probability calibrator. Apply it to CatBoost RawFormulaVal output.

candidate_meta_metadata.json
    Exact feature order, categorical fields, threshold, splits and results.

policy_thresholds.csv
    Payout-aware threshold selection performed before the untouched test.

untouched_test_predictions.csv
    Every candidate and prediction in the final test period.

accepted_test_breakdown.csv
    Accepted test performance by asset and strategy.

feature_importance.csv
    CatBoost feature importance.

Deployment rule
---------------
Do not rename this artifact to deep_lstm_v1.onnx. It is a separate candidate
gate and requires a matching live feature adapter. Even if offline approval is
True, use it in IQ Option PRACTICE mode first because historical candles cannot
reproduce order acknowledgement, the accepted strike, rejection, or payout
changes.
"""
    (output / "README_ARTIFACT.txt").write_text(text, encoding="utf-8")


def zip_artifacts(output: Path) -> Path:
    archive = output.parent / "candidate_meta_artifacts.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.iterdir()):
            # The replay ledger can be hundreds of megabytes and is useful for
            # research, but it is not required for live inference. Keep the
            # downloadable model bundle small.
            is_candidate_ledger = path.name.startswith("offline_candidates.")
            if path.is_file() and not is_candidate_ledger:
                bundle.write(path, arcname=path.name)
    return archive


def main() -> None:
    warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)
    set_reproducible(CFG.random_seed)
    output = Path(CFG.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("IQ OPTION OFFLINE CANDIDATE META-MODEL TRAINER")
    print("=" * 72)
    print(f"Payout assumption: {CFG.binary_payout:.0%}")
    print(
        f"Breakeven win rate: {1 / (1 + CFG.binary_payout):.2%}"
    )
    print(
        "Historical result is a paper-entry proxy; final deployment remains "
        "PRACTICE-only."
    )

    path = discover_data_path(CFG.data_path)
    candles = load_and_validate_candles(path, CFG)
    candidates = build_candidates(candles, CFG)
    if CFG.save_generated_candidates:
        saved = save_candidate_data(candidates, output)
        print(f"Saved generated candidate ledger: {saved}")

    metadata = fit_and_evaluate(candidates, CFG, output)
    write_readme(output, metadata)
    archive = zip_artifacts(output)
    print(f"\nArtifacts: {output}")
    print(f"Download this archive from Kaggle Output: {archive}")


if __name__ == "__main__":
    main()
