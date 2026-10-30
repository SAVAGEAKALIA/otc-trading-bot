#!/usr/bin/env python3
"""
Train the OTC LSTM v4 with causal labels, stationary engineered features,
calibrated probabilities, and an untouched final test set.

Expected input
--------------
The default input is the enriched dataset produced by
``build_ml_feature_dataset.py`` with these columns:

    asset, timeframe, timestamp, open, high, low, close

``max``/``min`` are accepted as aliases for ``high``/``low``.
Timestamp values may be Unix seconds, Unix milliseconds, or parseable dates.

Important target definition
---------------------------
For a decision after candle t closes, the target is:

    close[t + one 2-minute candle] > open[t + one 2-minute candle]

The exported model is therefore appropriate only when live execution and
settlement match that horizon. The training script cannot compensate for a
late scan, a delayed order acknowledgement, or a different broker expiry.

Artifacts are written to ``lstm_stationary_v4_artifacts``. The ONNX model embeds
the temperature calibration, so a live client can apply sigmoid to its single
logit output exactly as before.
"""

from __future__ import annotations

import bisect
import copy
from datetime import UTC, datetime
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import pickle
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
import pandas_ta as ta
import torch
import torch.nn as nn
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    classification_report,
    log_loss,
    roc_auc_score,
)
from sklearn.preprocessing import RobustScaler
from torch.utils.data import DataLoader, Dataset

from trading_platform.research.training_provenance import (
    build_calibration_manifest,
    fingerprint_dataset,
    require_unchanged_dataset,
)


# ---------------------------------------------------------------------------
# Configuration: edit this section when running on a free cloud notebook.
# ---------------------------------------------------------------------------

DATA_FILE = Path(
    os.getenv(
        "TRAINING_DATA_FILE",
        "data/ml/enriched/enriched_candles.parquet",
    )
)
ARTIFACT_DIR = Path(
    os.getenv("TRAINING_ARTIFACT_DIR", "lstm_stationary_v4_artifacts")
)

TARGET_TIMEFRAME_SECONDS = 120
SEQUENCE_LENGTH = 90

# The calibration partition must span enough independent UTC days for the
# daily-block bootstrap and MIN_ACTIONABLE_CALIBRATION_DAYS gate. With roughly
# four months of history, 20% provides about 24 calibration days.
TRAIN_FRACTION = 0.55
EARLY_STOP_FRACTION = 0.10
CALIBRATION_FRACTION = 0.20
TEST_FRACTION = 0.15

BATCH_SIZE = 1024
EPOCHS = 100
LEARNING_RATE = 5e-4
WEIGHT_DECAY = 1e-5
EARLY_STOP_PATIENCE = 20
MIN_IMPROVEMENT = 1e-5
TRAINING_NOISE_STD = 0.005

RANDOM_SEED = 42
NUM_WORKERS = 0

INCLUDE_ASSET_FEATURES = True
SINGLE_ASSET_FILTER: Optional[str] = None

# An 80% net payout needs 55.56% wins merely to break even:
# p * 0.80 - (1 - p) > 0.
BINARY_PAYOUT = 0.80
MIN_PROBABILITY_EDGE = 0.02
MIN_DEPLOYMENT_CONFIDENCE = 0.65

# Selection safety requirements apply to the separate calibration split.
MIN_ACTIONABLE_CALIBRATION_TRADES = 500
MIN_ACTIONABLE_CALIBRATION_DAYS = 10
BOOTSTRAP_SAMPLES = 1_000

# Mirrors the bot's opportunity constraints more closely than evaluating
# every overlapping sequence as if every one could become a trade.
SCANNER_COOLDOWN_SECONDS = 300
DEDUPLICATE_BASE_CURRENCY_PER_TIMESTAMP = True

ONNX_OPSET = 17
ONNX_PARITY_TOLERANCE = 1e-4
EXPECTED_PANDAS_TA_VERSION = "0.4.71b0"

CONTEXT_CONTINUOUS_FEATURES = [
    "spread_bps",
    "quote_age_sec",
    "deal_count_10s",
    "deal_count_30s",
    "deal_count_60s",
    "deal_count_log_60s",
    "call_ratio_10s",
    "call_ratio_30s",
    "call_ratio_60s",
    "call_amount_ratio_60s",
    "deal_flow_imbalance_60s",
    "deal_amount_imbalance_60s",
    "deal_feed_age_sec",
    "traders_mood",
    "mood_centered",
    "mood_age_sec",
    "payout_fraction",
    "payout_breakeven",
    "payout_age_sec",
]
CONTEXT_FLAG_FEATURES = [
    "quote_missing",
    "deal_missing",
    "mood_missing",
    "payout_missing",
    "context_complete",
]


SCALE_FEATURES = [
    # Multi-horizon log returns are stationary across different price scales.
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
    "dist_ema_20",
    "dist_ema_50",
    "ema_20_slope_3",
    "ema_50_slope_3",
    "atr_pct",
    "atr_ratio_30",
    "macd_hist_atr",
    "rsi_centered",
    "stoch_k_centered",
    "bb_percent_b",
    "body_ratio",
    "signed_body_ratio",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "close_position",
    "realized_vol_10",
    "realized_vol_30",
    "return_zscore_20",
    *CONTEXT_CONTINUOUS_FEATURES,
    "hour_sin",
    "hour_cos",
    "day_sin",
    "day_cos",
]

BASE_PASS_FEATURES: List[str] = CONTEXT_FLAG_FEATURES
BASE_FEATURES = SCALE_FEATURES + BASE_PASS_FEATURES


def validate_configuration() -> None:
    fractions = [
        TRAIN_FRACTION,
        EARLY_STOP_FRACTION,
        CALIBRATION_FRACTION,
        TEST_FRACTION,
    ]
    if not math.isclose(sum(fractions), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"Split fractions must add to 1.0; got {sum(fractions)}")
    if TARGET_TIMEFRAME_SECONDS <= 0:
        raise ValueError("TARGET_TIMEFRAME_SECONDS must be positive")
    if SEQUENCE_LENGTH < 2:
        raise ValueError("SEQUENCE_LENGTH must be at least 2")
    if not 0.0 < BINARY_PAYOUT <= 1.0:
        raise ValueError("BINARY_PAYOUT must be in (0, 1]")
    installed_pandas_ta = package_version("pandas-ta")
    if installed_pandas_ta != EXPECTED_PANDAS_TA_VERSION:
        raise RuntimeError(
            "Training/live indicator parity requires "
            f"pandas-ta=={EXPECTED_PANDAS_TA_VERSION}; "
            f"found {installed_pandas_ta or 'not installed'}"
        )


def set_reproducible_seed(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def parse_timestamp(series: pd.Series) -> pd.Series:
    """Return UTC pandas timestamps from Unix or string timestamps."""
    numeric = pd.to_numeric(series, errors="coerce")
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")

    numeric_mask = numeric.notna()
    if numeric_mask.any():
        median_abs = float(numeric.loc[numeric_mask].abs().median())
        if median_abs >= 1e17:
            unit = "ns"
        elif median_abs >= 1e14:
            unit = "us"
        elif median_abs >= 1e11:
            unit = "ms"
        else:
            unit = "s"
        parsed.loc[numeric_mask] = pd.to_datetime(
            numeric.loc[numeric_mask], unit=unit, utc=True, errors="coerce"
        )

    string_mask = ~numeric_mask
    if string_mask.any():
        parsed.loc[string_mask] = pd.to_datetime(
            series.loc[string_mask], utc=True, errors="coerce"
        )
    return parsed


def package_version(name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def load_candles(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Training data not found: {path.resolve()}\n"
            "Set TRAINING_DATA_FILE or place candles_export.csv beside this script."
        )

    print(f"Loading {path} ...")
    frame = (
        pd.read_parquet(path)
        if path.suffix.lower() == ".parquet"
        else pd.read_csv(path, low_memory=False)
    )
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    frame = frame.rename(columns={"max": "high", "min": "low"})

    required = {
        "asset",
        "timeframe",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Missing required CSV columns: {missing}")

    missing_context = sorted(set(BASE_PASS_FEATURES + CONTEXT_CONTINUOUS_FEATURES).difference(frame.columns))
    if missing_context:
        raise ValueError(
            "This enriched LSTM trainer requires harvester context columns. "
            f"Missing: {missing_context}. Run build_ml_feature_dataset.py first."
        )

    frame["asset"] = frame["asset"].astype(str).str.strip().str.upper()
    if SINGLE_ASSET_FILTER:
        requested_asset = SINGLE_ASSET_FILTER.strip().upper()
        frame = frame.loc[frame["asset"] == requested_asset].copy()

    frame["timeframe"] = pd.to_numeric(frame["timeframe"], errors="coerce")
    observed_timeframes = sorted(
        int(value) for value in frame["timeframe"].dropna().unique()
    )
    frame = frame.loc[
        frame["timeframe"] == TARGET_TIMEFRAME_SECONDS
    ].copy()
    if frame.empty:
        raise ValueError(
            f"No {TARGET_TIMEFRAME_SECONDS}-second rows found. "
            f"Observed timeframes: {observed_timeframes}"
        )
    print(
        f"Timeframe filter: kept only {TARGET_TIMEFRAME_SECONDS}s rows; "
        f"observed={observed_timeframes}"
    )

    frame["timestamp"] = parse_timestamp(frame["timestamp"])
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in CONTEXT_CONTINUOUS_FEATURES + CONTEXT_FLAG_FEATURES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    invalid_required = frame[
        ["asset", "timestamp", "open", "high", "low", "close"]
    ].isna().any(axis=1)
    invalid_ohlc = (
        (frame["open"] <= 0)
        | (frame["high"] <= 0)
        | (frame["low"] <= 0)
        | (frame["close"] <= 0)
        | (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    invalid_count = int((invalid_required | invalid_ohlc).sum())
    if invalid_count:
        print(f"Discarding {invalid_count:,} malformed candle rows.")
        frame = frame.loc[~(invalid_required | invalid_ohlc)].copy()

    frame = frame.sort_values(["asset", "timestamp"], kind="mergesort")
    duplicate_mask = frame.duplicated(["asset", "timestamp"], keep="last")
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count:
        print(
            f"Discarding {duplicate_count:,} duplicate asset/timestamp rows "
            "(keeping the last occurrence)."
        )
        frame = frame.loc[~duplicate_mask].copy()

    if frame.empty:
        raise ValueError("No valid candles remain after validation")

    counts = frame.groupby("asset", sort=True).size()
    print(
        f"Validated {len(frame):,} candles across {len(counts)} assets "
        f"({counts.min():,} to {counts.max():,} rows each)."
    )
    context_days = frame["timestamp"].dt.floor("D").nunique()
    quote_coverage = float(1.0 - frame["quote_missing"].mean())
    mood_coverage = float(1.0 - frame["mood_missing"].mean())
    payout_coverage = float(1.0 - frame["payout_missing"].mean())
    print(
        "Context coverage: "
        f"days={context_days}, quote={quote_coverage:.1%}, "
        f"mood={mood_coverage:.1%}, payout={payout_coverage:.1%}"
    )
    if context_days < 30:
        print(
            "WARNING: enriched history spans only "
            f"{context_days} UTC day(s). Training will continue, but the "
            "post-training deployment checks remain unchanged."
        )
    if min(quote_coverage, mood_coverage, payout_coverage) < 0.70:
        raise RuntimeError(
            "Enriched LSTM data is not ready: require 70% coverage for "
            "quote, mood, and payout feeds."
        )
    return frame.reset_index(drop=True)


def add_live_compatible_features(segment: pd.DataFrame) -> pd.DataFrame:
    """
    Build the stationary v4 features reproduced by the live feature engine.

    Each call receives one uninterrupted 2-minute candle segment, so rolling
    indicators never bridge a missing candle.
    """
    result = segment.copy()

    close = result["close"].replace(0.0, np.nan)
    open_price = result["open"].replace(0.0, np.nan)
    log_close = np.log(close)
    for horizon in (1, 2, 3, 5, 10):
        result[f"log_return_{horizon}"] = log_close.diff(horizon)

    previous_close = close.shift(1)
    result["open_gap_log"] = np.log(open_price.div(previous_close))
    result["high_from_open_log"] = np.log(result["high"].div(open_price))
    result["low_from_open_log"] = np.log(result["low"].div(open_price))
    result["close_from_open_log"] = np.log(close.div(open_price))
    result["range_pct"] = (
        result["high"] - result["low"]
    ).div(close)

    ema_20 = ta.ema(result["close"], length=20)
    ema_50 = ta.ema(result["close"], length=50)
    result["dist_ema_20"] = result["close"].div(ema_20).sub(1.0)
    result["dist_ema_50"] = result["close"].div(ema_50).sub(1.0)
    result["ema_20_slope_3"] = np.log(ema_20.div(ema_20.shift(3)))
    result["ema_50_slope_3"] = np.log(ema_50.div(ema_50.shift(3)))

    atr_14 = ta.atr(
        result["high"], result["low"], result["close"], length=14
    )
    result["atr_pct"] = atr_14.div(close)
    result["atr_ratio_30"] = result["atr_pct"].div(
        result["atr_pct"].rolling(30, min_periods=30).median()
    )

    macd = ta.macd(
        result["close"], fast=12, slow=26, signal=9
    )
    if macd is None or macd.shape[1] < 2:
        raise RuntimeError("pandas-ta failed to calculate MACD")
    result["macd_hist_atr"] = macd.iloc[:, 1].div(
        atr_14.replace(0.0, np.nan)
    )
    result["rsi_centered"] = (
        ta.rsi(result["close"], length=14).sub(50.0).div(50.0)
    )

    candle_range = result["high"] - result["low"] + 1e-8
    body = result["close"] - result["open"]
    result["body_ratio"] = body.abs().div(candle_range)
    result["signed_body_ratio"] = body.div(candle_range)
    result["upper_wick_ratio"] = (
        result["high"] - result[["open", "close"]].max(axis=1)
    ).div(candle_range)
    result["lower_wick_ratio"] = (
        result[["open", "close"]].min(axis=1) - result["low"]
    ).div(candle_range)
    result["close_position"] = (
        result["close"] - result["low"]
    ).div(candle_range)

    stochastic = ta.stoch(
        result["high"],
        result["low"],
        result["close"],
        k=14,
        d=3,
        smooth_k=3,
    )
    if stochastic is None or stochastic.shape[1] < 1:
        raise RuntimeError("pandas-ta failed to calculate stochastic oscillator")
    result["stoch_k_centered"] = (
        stochastic.iloc[:, 0].sub(50.0).div(50.0)
    )

    bands = ta.bbands(result["close"], length=20, std=2.0)
    if bands is None or bands.shape[1] < 5:
        raise RuntimeError("pandas-ta failed to calculate Bollinger Bands")
    result["bb_percent_b"] = bands.iloc[:, 4]

    one_bar_return = result["log_return_1"]
    result["realized_vol_10"] = one_bar_return.rolling(
        10, min_periods=10
    ).std(ddof=0)
    result["realized_vol_30"] = one_bar_return.rolling(
        30, min_periods=30
    ).std(ddof=0)
    rolling_mean = one_bar_return.rolling(20, min_periods=20).mean()
    rolling_std = one_bar_return.rolling(20, min_periods=20).std(ddof=0)
    result["return_zscore_20"] = one_bar_return.sub(rolling_mean).div(
        rolling_std.replace(0.0, np.nan)
    )

    minute_of_day = (
        result["timestamp"].dt.hour * 60 + result["timestamp"].dt.minute
    )
    hour_angle = 2.0 * np.pi * minute_of_day / 1440.0
    day_angle = 2.0 * np.pi * result["timestamp"].dt.dayofweek / 7.0
    result["hour_sin"] = np.sin(hour_angle)
    result["hour_cos"] = np.cos(hour_angle)
    result["day_sin"] = np.sin(day_angle)
    result["day_cos"] = np.cos(day_angle)

    feature_values = result[BASE_FEATURES].replace([np.inf, -np.inf], np.nan)
    result.loc[:, BASE_FEATURES] = feature_values
    return result


def prepare_feature_rows(
    candles: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[str], pd.DataFrame]:
    """
    Calculate features within gap-free segments and create per-asset splits.

    Ties are not mislabeled as PUT. They receive a missing target and can still
    be used as historical input rows, but never as supervised endpoints.
    """
    assets = sorted(candles["asset"].unique().tolist())
    asset_features = [f"asset_{asset}" for asset in assets]
    feature_columns = BASE_FEATURES + (
        asset_features if INCLUDE_ASSET_FEATURES else []
    )

    prepared_parts: List[pd.DataFrame] = []
    split_calendar_rows: List[Dict[str, object]] = []
    segment_number = 0

    # Use one calendar for the whole universe. Per-asset positional cutoffs can
    # otherwise let later rows from a long-history asset leak into training
    # while an earlier row from a shorter-history asset is being evaluated.
    timeline = pd.DatetimeIndex(
        candles["timestamp"].dropna().unique()
    ).sort_values()
    if len(timeline) < 4 * (SEQUENCE_LENGTH + 2):
        raise ValueError("The shared market timeline is too short for four splits")
    train_position = max(0, int(len(timeline) * TRAIN_FRACTION) - 1)
    stop_position = max(
        train_position + 1,
        int(len(timeline) * (TRAIN_FRACTION + EARLY_STOP_FRACTION)) - 1,
    )
    calibration_position = max(
        stop_position + 1,
        int(
            len(timeline)
            * (
                TRAIN_FRACTION
                + EARLY_STOP_FRACTION
                + CALIBRATION_FRACTION
            )
        )
        - 1,
    )
    global_train_end = timeline[train_position]
    global_stop_end = timeline[stop_position]
    global_calibration_end = timeline[calibration_position]
    print(
        "Shared temporal cutoffs: "
        f"train≤{global_train_end}, "
        f"early-stop≤{global_stop_end}, "
        f"calibration≤{global_calibration_end}, then test"
    )

    for asset in assets:
        asset_rows = candles.loc[candles["asset"] == asset].copy()
        asset_rows = asset_rows.sort_values("timestamp").reset_index(drop=True)
        cadence = asset_rows["timestamp"].diff().dt.total_seconds()
        raw_segment_ids = cadence.ne(TARGET_TIMEFRAME_SECONDS).cumsum()

        featured_segments: List[pd.DataFrame] = []
        gap_count = max(0, int(raw_segment_ids.nunique()) - 1)
        if gap_count:
            print(f"{asset}: detected {gap_count} timestamp gap(s).")

        for _, raw_segment in asset_rows.groupby(raw_segment_ids, sort=False):
            if len(raw_segment) < SEQUENCE_LENGTH + 35:
                continue
            raw_segment = raw_segment.copy().reset_index(drop=True)

            # A label belongs to the current row and looks exactly one candle
            # forward inside this uninterrupted segment.
            # A decision is made only after the current candle closes.  The
            # executable paper entry is the next exact candle open and the
            # two-minute settlement is that candle's close.
            next_open = raw_segment["open"].shift(-1)
            next_close = raw_segment["close"].shift(-1)
            raw_segment["target"] = np.where(
                next_close > next_open,
                1.0,
                np.where(next_close < next_open, 0.0, np.nan),
            )
            raw_segment.loc[
                next_open.isna() | next_close.isna(), "target"
            ] = np.nan

            featured = add_live_compatible_features(raw_segment)
            featured = featured.dropna(subset=BASE_FEATURES).copy()
            if len(featured) < SEQUENCE_LENGTH + 2:
                continue

            # Feature warm-up removes only a prefix. This defensive recheck
            # guarantees that a future change cannot introduce an interior gap.
            post_feature_cadence = (
                featured["timestamp"].diff().dt.total_seconds()
            )
            post_ids = post_feature_cadence.ne(
                TARGET_TIMEFRAME_SECONDS
            ).cumsum()
            for _, contiguous in featured.groupby(post_ids, sort=False):
                if len(contiguous) < SEQUENCE_LENGTH + 2:
                    continue
                contiguous = contiguous.copy().reset_index(drop=True)
                contiguous["segment_id"] = segment_number
                segment_number += 1
                featured_segments.append(contiguous)

        if not featured_segments:
            print(f"{asset}: skipped; not enough contiguous feature rows.")
            continue

        asset_frame = pd.concat(featured_segments, ignore_index=True)
        row_count = len(asset_frame)
        timestamp_values = asset_frame["timestamp"]
        split_names = np.full(row_count, "test", dtype=object)
        split_names[
            timestamp_values.le(global_calibration_end).to_numpy()
        ] = "calibration"
        split_names[timestamp_values.le(global_stop_end).to_numpy()] = (
            "early_stop"
        )
        split_names[timestamp_values.le(global_train_end).to_numpy()] = "train"
        asset_frame["split"] = split_names

        minimum_rows = SEQUENCE_LENGTH + 2
        split_lengths = [
            int((asset_frame["split"] == name).sum())
            for name in ("train", "early_stop", "calibration", "test")
        ]
        if min(split_lengths) < minimum_rows:
            print(
                f"{asset}: skipped; temporal splits are too short: "
                f"{split_lengths}"
            )
            continue

        # The final row of every segment/split must not use a target belonging
        # to another segment or temporal partition.
        group_last_indices = (
            asset_frame.groupby(["segment_id", "split"], sort=False)
            .tail(1)
            .index
        )
        asset_frame.loc[group_last_indices, "target"] = np.nan

        if INCLUDE_ASSET_FEATURES:
            for column in asset_features:
                asset_frame[column] = 0.0
            asset_frame[f"asset_{asset}"] = 1.0

        boundaries: Dict[str, Tuple[pd.Timestamp, pd.Timestamp]] = {}
        for split_name in ("train", "early_stop", "calibration", "test"):
            split_rows = asset_frame.loc[asset_frame["split"] == split_name]
            boundaries[split_name] = (
                split_rows["timestamp"].min(),
                split_rows["timestamp"].max(),
            )

        split_calendar_rows.append(
            {
                "asset": asset,
                "usable_rows": row_count,
                "train_start": boundaries["train"][0],
                "train_end": boundaries["train"][1],
                "early_stop_start": boundaries["early_stop"][0],
                "early_stop_end": boundaries["early_stop"][1],
                "calibration_start": boundaries["calibration"][0],
                "calibration_end": boundaries["calibration"][1],
                "test_start": boundaries["test"][0],
                "test_end": boundaries["test"][1],
            }
        )
        counts_text = ", ".join(
            f"{name}={int((asset_frame['split'] == name).sum()):,}"
            for name in ("train", "early_stop", "calibration", "test")
        )
        print(f"{asset}: usable={row_count:,}, {counts_text}")
        prepared_parts.append(asset_frame)

    if not prepared_parts:
        raise ValueError("No assets have enough clean, contiguous data")

    prepared = pd.concat(prepared_parts, ignore_index=True)
    active_assets = sorted(prepared["asset"].unique().tolist())
    if INCLUDE_ASSET_FEATURES:
        active_asset_features = [f"asset_{asset}" for asset in active_assets]
        unused = sorted(set(asset_features).difference(active_asset_features))
        if unused:
            prepared = prepared.drop(columns=unused, errors="ignore")
        feature_columns = BASE_FEATURES + active_asset_features

    calendar = pd.DataFrame(split_calendar_rows)
    calendar = calendar.loc[calendar["asset"].isin(active_assets)].copy()
    return prepared, feature_columns, calendar


@dataclass
class SequenceBlock:
    asset: str
    split: str
    values: np.ndarray
    targets: np.ndarray
    timestamps: np.ndarray
    valid_ends: np.ndarray


def build_sequence_blocks(
    prepared: pd.DataFrame,
    feature_columns: Sequence[str],
) -> Dict[str, List[SequenceBlock]]:
    blocks: Dict[str, List[SequenceBlock]] = {
        "train": [],
        "early_stop": [],
        "calibration": [],
        "test": [],
    }

    grouped = prepared.groupby(
        ["asset", "segment_id", "split"], sort=False
    )
    for (asset, _, split_name), group in grouped:
        group = group.sort_values("timestamp").reset_index(drop=True)
        if len(group) < SEQUENCE_LENGTH:
            continue

        cadence = (
            group["timestamp"].diff().dt.total_seconds().iloc[1:].to_numpy()
        )
        if cadence.size and not np.all(
            cadence == TARGET_TIMEFRAME_SECONDS
        ):
            raise RuntimeError(
                f"Internal error: {asset}/{split_name} block crosses a gap"
            )

        values = group[list(feature_columns)].to_numpy(dtype=np.float32)
        targets = group["target"].to_numpy(dtype=np.float32)
        timestamps = (
            group["timestamp"].astype("int64").to_numpy(dtype=np.int64)
            // 1_000_000_000
        )
        candidate_ends = np.arange(
            SEQUENCE_LENGTH - 1, len(group), dtype=np.int64
        )
        valid_ends = candidate_ends[
            np.isfinite(targets[candidate_ends])
        ]
        if valid_ends.size == 0:
            continue

        blocks[str(split_name)].append(
            SequenceBlock(
                asset=str(asset),
                split=str(split_name),
                values=values,
                targets=targets,
                timestamps=timestamps,
                valid_ends=valid_ends,
            )
        )

    missing_splits = [
        name for name, split_blocks in blocks.items() if not split_blocks
    ]
    if missing_splits:
        raise ValueError(f"No valid sequence blocks for: {missing_splits}")
    return blocks


def fit_and_apply_scaler(
    blocks: Dict[str, List[SequenceBlock]],
) -> RobustScaler:
    """
    Fit on unique training rows, not millions of repeated overlapping windows.
    """
    scale_count = len(SCALE_FEATURES)
    training_rows = np.concatenate(
        [block.values[:, :scale_count] for block in blocks["train"]], axis=0
    )
    if not np.isfinite(training_rows).all():
        raise ValueError("Non-finite training features reached the scaler")

    scaler = RobustScaler()
    scaler.fit(training_rows)
    del training_rows
    gc.collect()

    for split_blocks in blocks.values():
        for block in split_blocks:
            transformed = scaler.transform(
                block.values[:, :scale_count]
            ).astype(np.float32)
            block.values[:, :scale_count] = transformed
            if not np.isfinite(block.values).all():
                raise ValueError(
                    f"Non-finite scaled features in {block.asset}/{block.split}"
                )
    return scaler


class LazySequenceDataset(Dataset):
    """Create overlapping windows on demand without materializing them."""

    def __init__(self, blocks: Sequence[SequenceBlock]) -> None:
        self.blocks = list(blocks)
        self.cumulative: List[int] = []
        running_total = 0
        for block in self.blocks:
            running_total += int(block.valid_ends.size)
            self.cumulative.append(running_total)

    def __len__(self) -> int:
        return self.cumulative[-1] if self.cumulative else 0

    def __getitem__(self, index: int) -> Tuple[torch.Tensor, torch.Tensor]:
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)

        block_index = bisect.bisect_right(self.cumulative, index)
        previous_total = (
            self.cumulative[block_index - 1] if block_index else 0
        )
        local_index = index - previous_total
        block = self.blocks[block_index]
        end = int(block.valid_ends[local_index])
        start = end - SEQUENCE_LENGTH + 1
        features = torch.from_numpy(block.values[start : end + 1])
        target = torch.tensor(block.targets[end], dtype=torch.float32)
        return features, target

    def metadata_arrays(self) -> Tuple[np.ndarray, np.ndarray]:
        assets: List[str] = []
        timestamps: List[np.ndarray] = []
        for block in self.blocks:
            assets.extend([block.asset] * int(block.valid_ends.size))
            timestamps.append(block.timestamps[block.valid_ends])
        return (
            np.asarray(assets, dtype=object),
            np.concatenate(timestamps).astype(np.int64),
        )


class TradingLSTM(nn.Module):
    def __init__(
        self,
        input_size: int,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.10,
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc1 = nn.Linear(hidden_size, 32)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)
        self.fc2 = nn.Linear(32, 1)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        output, _ = self.lstm(inputs)
        last_step = output[:, -1, :]
        return self.fc2(self.dropout(self.relu(self.fc1(last_step)))).squeeze(-1)


class TemperatureScaledModel(nn.Module):
    """Embed calibration while preserving a one-logit ONNX output."""

    def __init__(self, model: nn.Module, temperature: float) -> None:
        super().__init__()
        self.model = model
        self.register_buffer(
            "temperature",
            torch.tensor(float(temperature), dtype=torch.float32),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.model(inputs) / self.temperature.clamp_min(1e-6)


def make_loader(
    dataset: Dataset,
    shuffle: bool,
    device: torch.device,
) -> DataLoader:
    return DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=shuffle,
        num_workers=NUM_WORKERS,
        pin_memory=device.type == "cuda",
        drop_last=False,
    )


@torch.no_grad()
def evaluate_loss(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> float:
    model.eval()
    total_loss = 0.0
    total_rows = 0
    for features, targets in loader:
        features = features.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        logits = model(features)
        loss = criterion(logits, targets)
        rows = int(targets.size(0))
        total_loss += float(loss.item()) * rows
        total_rows += rows
    return total_loss / max(total_rows, 1)


def train_model(
    model: nn.Module,
    train_loader: DataLoader,
    early_stop_loader: DataLoader,
    device: torch.device,
) -> Tuple[nn.Module, pd.DataFrame]:
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=LEARNING_RATE,
        weight_decay=WEIGHT_DECAY,
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="min",
        factor=0.5,
        patience=5,
        min_lr=1e-6,
    )

    best_state = copy.deepcopy(model.state_dict())
    best_loss = float("inf")
    epochs_without_improvement = 0
    history: List[Dict[str, float]] = []
    scale_count = len(SCALE_FEATURES)

    print("\n--- Starting LSTM training ---")
    for epoch in range(EPOCHS):
        model.train()
        total_loss = 0.0
        total_rows = 0

        for features, targets in train_loader:
            features = features.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)
            if TRAINING_NOISE_STD > 0:
                features = features.clone()
                noise = torch.randn_like(
                    features[:, :, :scale_count]
                ) * TRAINING_NOISE_STD
                features[:, :, :scale_count] += noise

            optimizer.zero_grad(set_to_none=True)
            logits = model(features)
            loss = criterion(logits, targets)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            rows = int(targets.size(0))
            total_loss += float(loss.item()) * rows
            total_rows += rows

        training_loss = total_loss / max(total_rows, 1)
        validation_loss = evaluate_loss(
            model, early_stop_loader, criterion, device
        )
        scheduler.step(validation_loss)
        learning_rate = float(optimizer.param_groups[0]["lr"])
        history.append(
            {
                "epoch": epoch,
                "train_loss": training_loss,
                "early_stop_loss": validation_loss,
                "learning_rate": learning_rate,
            }
        )

        print(
            f"Epoch {epoch:03d} | train={training_loss:.5f} | "
            f"early_stop={validation_loss:.5f} | lr={learning_rate:.2e}"
        )

        if validation_loss < best_loss - MIN_IMPROVEMENT:
            best_loss = validation_loss
            best_state = copy.deepcopy(model.state_dict())
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= EARLY_STOP_PATIENCE:
                print(f"Early stopping at epoch {epoch}.")
                break

    model.load_state_dict(best_state)
    return model, pd.DataFrame(history)


@torch.no_grad()
def predict_logits(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> Tuple[np.ndarray, np.ndarray]:
    model.eval()
    logits_parts: List[np.ndarray] = []
    target_parts: List[np.ndarray] = []
    for features, targets in loader:
        features = features.to(device, non_blocking=True)
        logits_parts.append(model(features).detach().cpu().numpy())
        target_parts.append(targets.numpy())
    return (
        np.concatenate(logits_parts).astype(np.float64),
        np.concatenate(target_parts).astype(np.int64),
    )


def fit_temperature(logits: np.ndarray, targets: np.ndarray) -> float:
    """Fit one positive temperature using only the calibration partition."""
    logits_tensor = torch.tensor(logits, dtype=torch.float64)
    targets_tensor = torch.tensor(targets, dtype=torch.float64)
    log_temperature = torch.zeros(
        1, dtype=torch.float64, requires_grad=True
    )
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.LBFGS(
        [log_temperature],
        lr=0.1,
        max_iter=100,
        line_search_fn="strong_wolfe",
    )

    def closure() -> torch.Tensor:
        optimizer.zero_grad()
        temperature = log_temperature.exp().clamp(0.05, 20.0)
        loss = criterion(logits_tensor / temperature, targets_tensor)
        loss.backward()
        return loss

    optimizer.step(closure)
    temperature = float(log_temperature.detach().exp().clamp(0.05, 20.0))
    if not math.isfinite(temperature):
        raise RuntimeError("Temperature calibration produced a non-finite value")
    return temperature


def sigmoid(logits: np.ndarray) -> np.ndarray:
    clipped = np.clip(logits, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def chronological_calibration_masks(
    timestamps: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    Split calibration rows by one global timestamp.

    The first half fits temperature scaling. The second half chooses the
    trading threshold and evaluates calibration before the untouched test.
    """
    unique_times = np.unique(np.asarray(timestamps, dtype=np.int64))
    if unique_times.size < 4:
        raise ValueError("Calibration partition has too few unique timestamps")
    cutoff = int(unique_times[(unique_times.size // 2) - 1])
    temperature_mask = timestamps <= cutoff
    policy_mask = timestamps > cutoff
    if not temperature_mask.any() or not policy_mask.any():
        raise ValueError("Could not split calibration rows chronologically")
    return temperature_mask, policy_mask, cutoff


def expected_value(win_rate: float, payout: float) -> float:
    return win_rate * payout - (1.0 - win_rate)


def select_executable_indices(
    probabilities: np.ndarray,
    targets: np.ndarray,
    assets: np.ndarray,
    timestamps: np.ndarray,
    threshold: float,
) -> np.ndarray:
    """
    Approximate the scanner's executable stream:
    confidence gate, strongest same-base opportunity, then per-asset cooldown.
    """
    confidence = np.maximum(probabilities, 1.0 - probabilities)
    candidate_indices = np.flatnonzero(confidence >= threshold)
    if candidate_indices.size == 0:
        return candidate_indices.astype(np.int64)

    candidates = pd.DataFrame(
        {
            "index": candidate_indices,
            "timestamp": timestamps[candidate_indices],
            "asset": assets[candidate_indices],
            "confidence": confidence[candidate_indices],
        }
    )
    candidates["base"] = candidates["asset"].str.slice(0, 3)
    candidates = candidates.sort_values(
        ["timestamp", "confidence", "asset"],
        ascending=[True, False, True],
        kind="mergesort",
    )

    if DEDUPLICATE_BASE_CURRENCY_PER_TIMESTAMP:
        candidates = candidates.drop_duplicates(
            ["timestamp", "base"], keep="first"
        )

    accepted: List[int] = []
    last_timestamp_by_asset: Dict[str, int] = {}
    for row in candidates.itertuples(index=False):
        previous = last_timestamp_by_asset.get(row.asset)
        if (
            previous is not None
            and int(row.timestamp) - previous < SCANNER_COOLDOWN_SECONDS
        ):
            continue
        accepted.append(int(row.index))
        last_timestamp_by_asset[row.asset] = int(row.timestamp)
    return np.asarray(accepted, dtype=np.int64)


def daily_block_bootstrap(
    correct: np.ndarray,
    timestamps: np.ndarray,
    payout: float,
    samples: int,
    seed: int,
) -> Tuple[float, float]:
    """
    Resample UTC trading days, preserving within-day dependence.

    This is more honest than an IID Wilson interval for heavily overlapping
    time-series predictions.
    """
    if correct.size == 0:
        return float("nan"), float("nan")

    days = timestamps // 86_400
    unique_days = np.unique(days)
    if unique_days.size < 2:
        return float("nan"), float("nan")

    wins_by_day = np.asarray(
        [correct[days == day].sum() for day in unique_days], dtype=np.float64
    )
    trades_by_day = np.asarray(
        [(days == day).sum() for day in unique_days], dtype=np.float64
    )
    rng = np.random.default_rng(seed)
    boot_win_rates = np.empty(samples, dtype=np.float64)

    for sample in range(samples):
        chosen = rng.integers(0, unique_days.size, size=unique_days.size)
        wins = wins_by_day[chosen].sum()
        trades = trades_by_day[chosen].sum()
        boot_win_rates[sample] = wins / max(trades, 1.0)

    lower_win_rate = float(np.quantile(boot_win_rates, 0.025))
    lower_expectancy = expected_value(lower_win_rate, payout)
    return lower_win_rate, lower_expectancy


def calculate_trade_metrics(
    probabilities: np.ndarray,
    targets: np.ndarray,
    assets: np.ndarray,
    timestamps: np.ndarray,
    threshold: float,
    payout: float,
    seed: int,
) -> Dict[str, float]:
    selected = select_executable_indices(
        probabilities, targets, assets, timestamps, threshold
    )
    if selected.size == 0:
        return {
            "threshold": threshold,
            "trades": 0,
            "days": 0,
            "coverage": 0.0,
            "win_rate": float("nan"),
            "lower_win_rate": float("nan"),
            "expectancy": float("nan"),
            "lower_expectancy": float("nan"),
        }

    directions = (probabilities[selected] >= 0.5).astype(np.int64)
    correct = (directions == targets[selected]).astype(np.float64)
    win_rate = float(correct.mean())
    lower_win_rate, lower_expectancy = daily_block_bootstrap(
        correct,
        timestamps[selected],
        payout,
        BOOTSTRAP_SAMPLES,
        seed,
    )
    return {
        "threshold": float(threshold),
        "trades": int(selected.size),
        "days": int(np.unique(timestamps[selected] // 86_400).size),
        "coverage": float(selected.size / len(probabilities)),
        "win_rate": win_rate,
        "lower_win_rate": lower_win_rate,
        "expectancy": expected_value(win_rate, payout),
        "lower_expectancy": lower_expectancy,
    }


def choose_threshold(
    probabilities: np.ndarray,
    targets: np.ndarray,
    assets: np.ndarray,
    timestamps: np.ndarray,
) -> Tuple[float, pd.DataFrame, bool, str]:
    breakeven = 1.0 / (1.0 + BINARY_PAYOUT)
    minimum_threshold = max(
        MIN_DEPLOYMENT_CONFIDENCE,
        math.ceil((breakeven + MIN_PROBABILITY_EDGE) * 100.0) / 100.0,
    )
    threshold_grid = np.round(
        np.arange(minimum_threshold, 0.991, 0.01), 2
    )

    rows = [
        calculate_trade_metrics(
            probabilities,
            targets,
            assets,
            timestamps,
            float(threshold),
            BINARY_PAYOUT,
            RANDOM_SEED + position,
        )
        for position, threshold in enumerate(threshold_grid)
    ]
    table = pd.DataFrame(rows)
    eligible = table.loc[
        (table["trades"] >= MIN_ACTIONABLE_CALIBRATION_TRADES)
        & (table["days"] >= MIN_ACTIONABLE_CALIBRATION_DAYS)
        & table["lower_expectancy"].notna()
    ].copy()
    if eligible.empty:
        available_days = int(np.unique(timestamps // 86_400).size)
        maximum_trades = int(table["trades"].max()) if len(table) else 0
        maximum_trade_days = (
            int(table["days"].max()) if len(table) else 0
        )
        reason = (
            "No calibration threshold met the safety requirements: "
            f"required trades≥{MIN_ACTIONABLE_CALIBRATION_TRADES:,} and "
            f"trade days≥{MIN_ACTIONABLE_CALIBRATION_DAYS}; "
            f"best observed trades={maximum_trades:,}, "
            f"trade days={maximum_trade_days}, "
            f"available calibration days={available_days}. "
            "The fallback threshold is for artifact compatibility only and "
            "must not be treated as deployment approval."
        )
        return minimum_threshold, table, False, reason

    eligible = eligible.sort_values(
        ["lower_expectancy", "trades", "threshold"],
        ascending=[False, False, False],
    )
    best = eligible.iloc[0]
    reason = (
        "Calibration threshold met minimum trade/day requirements and was "
        "selected by the highest daily-bootstrap lower expectancy."
    )
    return float(best["threshold"]), table, True, reason


def safe_auc(targets: np.ndarray, probabilities: np.ndarray) -> float:
    if np.unique(targets).size < 2:
        return float("nan")
    return float(roc_auc_score(targets, probabilities))


def reliability_report(
    targets: np.ndarray,
    probabilities: np.ndarray,
    bins: int = 10,
) -> Tuple[Dict[str, float], pd.DataFrame]:
    """Return proper probability scores and an equal-width reliability table."""
    targets = np.asarray(targets, dtype=np.int64)
    probabilities = np.clip(
        np.asarray(probabilities, dtype=np.float64), 1e-7, 1.0 - 1e-7
    )
    prevalence = float(targets.mean())
    null_probabilities = np.full_like(probabilities, prevalence)
    brier = float(brier_score_loss(targets, probabilities))
    null_brier = float(brier_score_loss(targets, null_probabilities))
    cross_entropy = float(log_loss(targets, probabilities, labels=[0, 1]))
    null_cross_entropy = float(
        log_loss(targets, null_probabilities, labels=[0, 1])
    )

    edges = np.linspace(0.0, 1.0, bins + 1)
    assignments = np.clip(
        np.digitize(probabilities, edges[1:-1], right=False), 0, bins - 1
    )
    rows: List[Dict[str, float]] = []
    expected_calibration_error = 0.0
    for index in range(bins):
        mask = assignments == index
        count = int(mask.sum())
        if count:
            mean_probability = float(probabilities[mask].mean())
            observed_rate = float(targets[mask].mean())
            absolute_gap = abs(mean_probability - observed_rate)
            expected_calibration_error += absolute_gap * count / len(targets)
        else:
            mean_probability = float("nan")
            observed_rate = float("nan")
            absolute_gap = float("nan")
        rows.append(
            {
                "bin": index,
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "count": count,
                "mean_probability": mean_probability,
                "observed_up_rate": observed_rate,
                "absolute_gap": absolute_gap,
            }
        )

    metrics = {
        "brier_score": brier,
        "null_brier_score": null_brier,
        "brier_skill_score": (
            1.0 - brier / null_brier if null_brier > 0.0 else float("nan")
        ),
        "log_loss": cross_entropy,
        "null_log_loss": null_cross_entropy,
        "expected_calibration_error": float(expected_calibration_error),
    }
    return metrics, pd.DataFrame(rows)


def per_asset_report(
    probabilities: np.ndarray,
    targets: np.ndarray,
    assets: np.ndarray,
    timestamps: np.ndarray,
    threshold: float,
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for asset in sorted(np.unique(assets)):
        mask = assets == asset
        asset_probabilities = probabilities[mask]
        asset_targets = targets[mask]
        asset_assets = assets[mask]
        asset_timestamps = timestamps[mask]
        all_predictions = (asset_probabilities >= 0.5).astype(np.int64)
        metrics = calculate_trade_metrics(
            asset_probabilities,
            asset_targets,
            asset_assets,
            asset_timestamps,
            threshold,
            BINARY_PAYOUT,
            RANDOM_SEED,
        )
        rows.append(
            {
                "asset": asset,
                "sequence_rows": int(mask.sum()),
                "all_accuracy": float(
                    accuracy_score(asset_targets, all_predictions)
                ),
                "all_roc_auc": safe_auc(
                    asset_targets, asset_probabilities
                ),
                **{
                    f"actionable_{key}": value
                    for key, value in metrics.items()
                    if key != "threshold"
                },
            }
        )
    return pd.DataFrame(rows)


def export_onnx_and_verify(
    model: nn.Module,
    temperature: float,
    input_size: int,
    test_dataset: LazySequenceDataset,
    output_path: Path,
    device: torch.device,
) -> float:
    calibrated_model = TemperatureScaledModel(
        copy.deepcopy(model).cpu(), temperature
    ).eval()
    dummy = torch.zeros(
        1, SEQUENCE_LENGTH, input_size, dtype=torch.float32
    )
    torch.onnx.export(
        calibrated_model,
        dummy,
        str(output_path),
        input_names=["features"],
        output_names=["logit"],
        opset_version=ONNX_OPSET,
        do_constant_folding=True,
        # The live bot always performs one-symbol inference with batch size 1.
        # A fixed batch avoids ambiguous LSTM hidden-state behavior and the
        # variable-batch exporter warning.
        dynamo=False,
    )

    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "onnxruntime is required to verify the exported model"
        ) from exc

    sample = test_dataset[0][0].unsqueeze(0)
    with torch.no_grad():
        torch_output = calibrated_model(sample).numpy()

    session = ort.InferenceSession(
        str(output_path), providers=["CPUExecutionProvider"]
    )
    onnx_output = session.run(
        ["logit"], {"features": sample.numpy()}
    )[0].reshape(-1)
    maximum_error = float(
        np.max(np.abs(torch_output.reshape(-1) - onnx_output))
    )
    if maximum_error > ONNX_PARITY_TOLERANCE:
        raise RuntimeError(
            f"ONNX parity failed: max absolute error {maximum_error:.6g} "
            f"> {ONNX_PARITY_TOLERANCE}"
        )
    print(f"ONNX parity passed; max absolute error={maximum_error:.3g}")
    return maximum_error


def json_ready(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return value if math.isfinite(value) else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def main() -> None:
    validate_configuration()
    set_reproducible_seed(RANDOM_SEED)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    dataset_fingerprint = fingerprint_dataset(DATA_FILE)
    dataset_id = os.getenv(
        "TRAINING_DATASET_ID",
        f"sha256-{str(dataset_fingerprint['sha256'])[:20]}",
    )

    print("=" * 72)
    print("OTC LSTM STATIONARY PROBABILITY TRAINER v4")
    print("=" * 72)
    print(
        f"Target: next {TARGET_TIMEFRAME_SECONDS // 60}-minute close direction"
    )
    print(
        f"Payout assumption: {BINARY_PAYOUT:.0%}; "
        f"breakeven={1.0 / (1.0 + BINARY_PAYOUT):.2%}"
    )

    candles = load_candles(DATA_FILE)
    prepared, feature_columns, split_calendar = prepare_feature_rows(candles)
    blocks = build_sequence_blocks(prepared, feature_columns)
    scaler = fit_and_apply_scaler(blocks)

    datasets = {
        name: LazySequenceDataset(split_blocks)
        for name, split_blocks in blocks.items()
    }
    for name, dataset in datasets.items():
        if len(dataset) == 0:
            raise ValueError(f"{name} dataset has no sequences")

    print("\nSequence counts:")
    for name in ("train", "early_stop", "calibration", "test"):
        print(f"  {name:12s}: {len(datasets[name]):,}")

    # Targets are cheap to collect and make label-balance mistakes obvious.
    target_rates: Dict[str, float] = {}
    for name, dataset in datasets.items():
        target_parts = [
            block.targets[block.valid_ends] for block in dataset.blocks
        ]
        target_rate = float(np.concatenate(target_parts).mean())
        target_rates[name] = target_rate
        print(f"  {name:12s} target-up rate: {target_rate:.3%}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\nDevice: {device}")
    model = TradingLSTM(input_size=len(feature_columns)).to(device)
    loaders = {
        name: make_loader(
            dataset,
            shuffle=(name == "train"),
            device=device,
        )
        for name, dataset in datasets.items()
    }

    model, history = train_model(
        model, loaders["train"], loaders["early_stop"], device
    )

    # This split calibrates probabilities and selects the deployment threshold.
    # It is distinct from the split that controlled early stopping.
    calibration_logits, calibration_targets = predict_logits(
        model, loaders["calibration"], device
    )
    calibration_assets, calibration_timestamps = datasets[
        "calibration"
    ].metadata_arrays()
    temperature_mask, policy_mask, calibration_cutoff = (
        chronological_calibration_masks(calibration_timestamps)
    )
    temperature = fit_temperature(
        calibration_logits[temperature_mask],
        calibration_targets[temperature_mask],
    )
    calibration_probabilities = sigmoid(calibration_logits / temperature)
    policy_probabilities = calibration_probabilities[policy_mask]
    policy_targets = calibration_targets[policy_mask]
    policy_assets = calibration_assets[policy_mask]
    policy_timestamps = calibration_timestamps[policy_mask]
    calibration_probability_metrics, calibration_reliability = (
        reliability_report(policy_targets, policy_probabilities)
    )

    print(
        f"\nTemperature calibration: T={temperature:.6f}; "
        f"fit rows={int(temperature_mask.sum()):,}; "
        f"policy rows={int(policy_mask.sum()):,}; "
        f"cutoff={pd.to_datetime(calibration_cutoff, unit='s', utc=True)}"
    )
    (
        selected_threshold,
        threshold_table,
        threshold_selection_passed,
        threshold_selection_reason,
    ) = choose_threshold(
        policy_probabilities,
        policy_targets,
        policy_assets,
        policy_timestamps,
    )
    calibration_metrics = calculate_trade_metrics(
        policy_probabilities,
        policy_targets,
        policy_assets,
        policy_timestamps,
        selected_threshold,
        BINARY_PAYOUT,
        RANDOM_SEED,
    )
    if threshold_selection_passed:
        print(
            f"Selected confidence threshold: {selected_threshold:.2%} | "
            f"calibration trades={calibration_metrics['trades']:,} | "
            f"win rate={calibration_metrics['win_rate']:.2%} | "
            f"lower expectancy={calibration_metrics['lower_expectancy']:.4f}"
        )
    else:
        print(f"Calibration gate failed: {threshold_selection_reason}")
        print(
            f"Using non-deployable fallback threshold "
            f"{selected_threshold:.2%} so diagnostics and artifacts can be saved."
        )

    # The final test set is touched once, after all model/temperature/threshold
    # choices are frozen.
    test_logits, test_targets = predict_logits(
        model, loaders["test"], device
    )
    test_probabilities = sigmoid(test_logits / temperature)
    test_probability_metrics, test_reliability = reliability_report(
        test_targets, test_probabilities
    )
    test_assets, test_timestamps = datasets["test"].metadata_arrays()
    all_test_predictions = (test_probabilities >= 0.5).astype(np.int64)
    all_test_accuracy = float(
        accuracy_score(test_targets, all_test_predictions)
    )
    all_test_auc = safe_auc(test_targets, test_probabilities)
    test_metrics = calculate_trade_metrics(
        test_probabilities,
        test_targets,
        test_assets,
        test_timestamps,
        selected_threshold,
        BINARY_PAYOUT,
        RANDOM_SEED + 10_000,
    )
    test_selected = select_executable_indices(
        test_probabilities,
        test_targets,
        test_assets,
        test_timestamps,
        selected_threshold,
    )
    test_report = (
        classification_report(
            test_targets[test_selected],
            (test_probabilities[test_selected] >= 0.5).astype(np.int64),
            digits=4,
            zero_division=0,
        )
        if test_selected.size
        else "No actionable test trades."
    )

    print("\n--- UNTOUCHED FINAL TEST ---")
    print(f"All-window accuracy: {all_test_accuracy:.2%}")
    print(f"All-window ROC AUC:  {all_test_auc:.4f}")
    print(
        f"Brier score:         {test_probability_metrics['brier_score']:.6f} "
        f"(null={test_probability_metrics['null_brier_score']:.6f}, "
        f"skill={test_probability_metrics['brier_skill_score']:.2%})"
    )
    print(
        f"Log loss:            {test_probability_metrics['log_loss']:.6f} "
        f"(null={test_probability_metrics['null_log_loss']:.6f})"
    )
    print(
        "Calibration error:   "
        f"{test_probability_metrics['expected_calibration_error']:.2%}"
    )
    print(
        f"Actionable trades:   {test_metrics['trades']:,} "
        f"({test_metrics['coverage']:.2%} coverage)"
    )
    print(f"Actionable win rate: {test_metrics['win_rate']:.2%}")
    print(
        f"95% day-bootstrap lower win rate: "
        f"{test_metrics['lower_win_rate']:.2%}"
    )
    print(f"Actionable expectancy: {test_metrics['expectancy']:.4f}")
    print(
        f"95% day-bootstrap lower expectancy: "
        f"{test_metrics['lower_expectancy']:.4f}"
    )
    print(test_report)

    per_asset = per_asset_report(
        test_probabilities,
        test_targets,
        test_assets,
        test_timestamps,
        selected_threshold,
    )

    schema_payload = {
        "feature_columns": feature_columns,
        "sequence_length": SEQUENCE_LENGTH,
        "timeframe_seconds": TARGET_TIMEFRAME_SECONDS,
    }
    feature_schema_hash = hashlib.sha256(
        json.dumps(schema_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    deployment_approved = bool(
        threshold_selection_passed
        and calibration_metrics["lower_expectancy"] is not None
        and test_metrics["lower_expectancy"] is not None
        and np.isfinite(calibration_metrics["lower_expectancy"])
        and np.isfinite(test_metrics["lower_expectancy"])
        and calibration_metrics["lower_expectancy"] > 0.0
        and test_metrics["lower_expectancy"] > 0.0
        and test_metrics["trades"] >= MIN_ACTIONABLE_CALIBRATION_TRADES
        and test_metrics["days"] >= MIN_ACTIONABLE_CALIBRATION_DAYS
        and calibration_probability_metrics["brier_skill_score"] > 0.0
        and test_probability_metrics["brier_skill_score"] > 0.0
        and test_probability_metrics["log_loss"]
        < test_probability_metrics["null_log_loss"]
    )

    onnx_path = ARTIFACT_DIR / "deep_lstm_v1.onnx"
    onnx_verification_passed = False
    onnx_verification_reason = ""
    maximum_onnx_error: Optional[float] = None
    try:
        maximum_onnx_error = export_onnx_and_verify(
            model,
            temperature,
            len(feature_columns),
            datasets["test"],
            onnx_path,
            device,
        )
        onnx_verification_passed = True
        onnx_verification_reason = (
            "ONNX Runtime output matched PyTorch within tolerance."
        )
    except Exception as error:
        onnx_verification_reason = (
            f"{type(error).__name__}: {error}"
        )
        print(
            "\nONNX verification did not pass. Research diagnostics will still "
            f"be saved, but deployment is forbidden: {onnx_verification_reason}"
        )

    deployment_approved = bool(
        deployment_approved and onnx_verification_passed
    )

    # Save the uncalibrated PyTorch weights for future retraining/debugging.
    state_path = ARTIFACT_DIR / "lstm_model_state.pt"
    scaler_path = ARTIFACT_DIR / "lstm_scaler.pkl"
    torch.save(
        {
            "state_dict": {
                key: value.detach().cpu()
                for key, value in model.state_dict().items()
            },
            "input_size": len(feature_columns),
            "hidden_size": 64,
            "num_layers": 2,
            "dropout": 0.10,
            "temperature": temperature,
        },
        state_path,
    )
    joblib.dump(scaler, scaler_path)

    split_windows = {}
    for name in ("train", "early_stop", "test"):
        _, timestamps = datasets[name].metadata_arrays()
        split_windows[name] = (
            datetime.fromtimestamp(int(timestamps.min()), tz=UTC),
            datetime.fromtimestamp(int(timestamps.max()), tz=UTC),
            len(datasets[name]),
        )
    calibration_fit_timestamps = calibration_timestamps[temperature_mask]
    split_windows["calibration"] = (
        datetime.fromtimestamp(int(calibration_fit_timestamps.min()), tz=UTC),
        datetime.fromtimestamp(int(calibration_fit_timestamps.max()), tz=UTC),
        int(temperature_mask.sum()),
    )
    split_windows["policy"] = (
        datetime.fromtimestamp(int(policy_timestamps.min()), tz=UTC),
        datetime.fromtimestamp(int(policy_timestamps.max()), tz=UTC),
        int(policy_mask.sum()),
    )
    artifact_paths = {
        "model_state": state_path,
        "scaler": scaler_path,
    }
    if onnx_path.is_file():
        artifact_paths["onnx"] = onnx_path
    provenance = build_calibration_manifest(
        model_version="stationary_probability_v4",
        method="temperature_scaling",
        target_definition=(
            "next contiguous 120-second candle closes above its own open; "
            "ties excluded"
        ),
        dataset_id=dataset_id,
        dataset_sha256=str(dataset_fingerprint["sha256"]),
        split_windows=split_windows,
        test_metrics={
            "brier_score": test_probability_metrics["brier_score"],
            "log_loss": test_probability_metrics["log_loss"],
        },
        artifact_paths=artifact_paths,
        offline_deployment_approved=deployment_approved,
    )
    with (ARTIFACT_DIR / "lstm_calibration_provenance.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(provenance, handle, indent=2)

    metadata = {
        "model_version": "stationary_probability_v4",
        "calibration_id": provenance["calibration_id"],
        "strict_provenance_manifest": True,
        "feature_schema_version": "stationary_2m_v4",
        "pandas_ta_version": EXPECTED_PANDAS_TA_VERSION,
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "input_data": str(DATA_FILE),
        "timeframe_seconds": TARGET_TIMEFRAME_SECONDS,
        "sequence_length": SEQUENCE_LENGTH,
        "warmup_candles": 60,
        "target_definition": (
            "1 when close[t+1] > open[t+1], 0 when close[t+1] < "
            "open[t+1]; ties excluded; prediction is made after t closes "
            "and t+1 is one contiguous 120-second execution candle"
        ),
        "execution_alignment_required": (
            "Order acknowledgement and binary settlement must match the "
            "trained next-2-minute-close horizon."
        ),
        "features": feature_columns,
        "requires_market_context": True,
        "context_schema_version": "market_context_v2",
        "context_features": CONTEXT_CONTINUOUS_FEATURES + CONTEXT_FLAG_FEATURES,
        "scale_features": SCALE_FEATURES,
        "pass_through_features": [
            column for column in feature_columns if column not in SCALE_FEATURES
        ],
        "include_asset_features": INCLUDE_ASSET_FEATURES,
        "assets": sorted(prepared["asset"].unique().tolist()),
        "feature_schema_sha256": feature_schema_hash,
        "input_shape": [1, SEQUENCE_LENGTH, len(feature_columns)],
        # Compatibility keys consumed by MLLSTMStrategy.
        "asset_features": [
            column for column in feature_columns if column.startswith("asset_")
        ],
        "scale_idx": len(SCALE_FEATURES),
        "threshold": selected_threshold,
        "output_type": "logit",
        "temperature_embedded_in_onnx": True,
        "temperature": temperature,
        "recommended_confidence_threshold": selected_threshold,
        "threshold_selection_passed": threshold_selection_passed,
        "threshold_selection_reason": threshold_selection_reason,
        "binary_payout_assumption": BINARY_PAYOUT,
        "binary_breakeven_win_rate": 1.0 / (1.0 + BINARY_PAYOUT),
        "scanner_cooldown_seconds": SCANNER_COOLDOWN_SECONDS,
        "deduplicate_base_currency_per_timestamp": (
            DEDUPLICATE_BASE_CURRENCY_PER_TIMESTAMP
        ),
        "split_fractions": {
            "train": TRAIN_FRACTION,
            "early_stop": EARLY_STOP_FRACTION,
            "calibration": CALIBRATION_FRACTION,
            "test": TEST_FRACTION,
        },
        "calibration_subsplit": {
            "temperature_rows": int(temperature_mask.sum()),
            "policy_rows": int(policy_mask.sum()),
            "cutoff_utc": pd.to_datetime(
                calibration_cutoff, unit="s", utc=True
            ).isoformat(),
            "rule": (
                "Chronological first half fits temperature; second half "
                "selects threshold and evaluates pre-test probability quality."
            ),
        },
        "sequence_counts": {
            name: len(dataset) for name, dataset in datasets.items()
        },
        "target_up_rates": target_rates,
        "calibration_probability_metrics": calibration_probability_metrics,
        "calibration_metrics": calibration_metrics,
        "test_all_window_accuracy": all_test_accuracy,
        "test_all_window_roc_auc": all_test_auc,
        "test_probability_metrics": test_probability_metrics,
        "test_actionable_metrics": test_metrics,
        "onnx_verification_passed": onnx_verification_passed,
        "onnx_verification_reason": onnx_verification_reason,
        "onnx_max_absolute_error": maximum_onnx_error,
        "deployment_approved": deployment_approved,
        "deployment_rule": (
            "True only when calibration and untouched-test 95% daily-block "
            "lower expectancy are positive, the test sample is large enough, "
            "and calibrated Brier/log-loss scores beat the null model."
        ),
        "versions": {
            "python": sys.version.split()[0],
            "numpy": package_version("numpy"),
            "pandas": package_version("pandas"),
            "pandas_ta": package_version("pandas-ta"),
            "torch": package_version("torch"),
            "scikit_learn": package_version("scikit-learn"),
            "onnx": package_version("onnx"),
            "onnxruntime": package_version("onnxruntime"),
        },
    }

    with (ARTIFACT_DIR / "lstm_metadata.pkl").open("wb") as handle:
        pickle.dump(metadata, handle)
    with (ARTIFACT_DIR / "lstm_metadata.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(json_ready(metadata), handle, indent=2)

    split_calendar.to_csv(
        ARTIFACT_DIR / "split_calendar.csv", index=False
    )
    history.to_csv(ARTIFACT_DIR / "training_history.csv", index=False)
    threshold_table.to_csv(
        ARTIFACT_DIR / "calibration_thresholds.csv", index=False
    )
    per_asset.to_csv(
        ARTIFACT_DIR / "test_per_asset_metrics.csv", index=False
    )
    calibration_reliability.to_csv(
        ARTIFACT_DIR / "calibration_reliability.csv", index=False
    )
    test_reliability.to_csv(
        ARTIFACT_DIR / "test_reliability.csv", index=False
    )
    require_unchanged_dataset(DATA_FILE, dataset_fingerprint)

    print("\n--- ARTIFACTS WRITTEN ---")
    for path in sorted(ARTIFACT_DIR.iterdir()):
        print(f"  {path}")

    if deployment_approved:
        print(
            "\n✅ Statistical deployment gate passed for the configured payout "
            "and execution simulation. Start in practice mode and verify live "
            "feature/schema/timing parity before real-money use."
        )
    else:
        print(
            "\n⛔ Deployment gate did not pass. Keep this model out of automated "
            "real-money execution. Inspect calibration_thresholds.csv, "
            "test_per_asset_metrics.csv, and timing parity before retraining."
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTraining interrupted by user.")
        raise SystemExit(130)
    except Exception as error:
        print(f"\nFATAL: {type(error).__name__}: {error}", file=sys.stderr)
        raise
