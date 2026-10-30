#!/usr/bin/env python3
"""
Standalone causal trending/ranging multi-timeframe OTC trainer.

Input CSV columns:
    asset,timeframe,timestamp,open,high,low,close

``min``/``max`` are accepted as aliases for ``low``/``high``. Candle
timestamps are treated as candle-open timestamps, matching IQ Option. A
higher-timeframe candle is visible only at:

    candle_close_time = timestamp + timeframe

The model predicts whether the close of the next contiguous 2-minute candle
will be above the latest completed 2-minute close. It consumes independent
sequences of completed 2m, 5m, and 15m candles plus an asset ID.

This is a research trainer. It rejects models without positive calibrated and
untouched-test expectancy at the configured binary payout. Its ONNX contract
is intentionally different from the old one-input model and requires a new
live MTF inference strategy.
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
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import RobustScaler
from torch.utils.data import DataLoader, Dataset

from trading_platform.research.model_promotion import assess_offline_promotion
from trading_platform.research.training_provenance import (
    build_calibration_manifest,
    fingerprint_dataset,
    require_unchanged_dataset,
)


# ---------------------------------------------------------------------------
# Cloud configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path(os.getenv("TRAINING_DATA_FILE", "candles_export.csv"))
ARTIFACT_DIR = Path(
    os.getenv("TRAINING_ARTIFACT_DIR", "regime_mtf_lstm_v5_artifacts")
)

SOURCE_TIMEFRAMES = (120, 300)
TIMEFRAMES = (120, 300, 900)
BASE_TIMEFRAME = 120
SEQUENCE_LENGTHS = {120: 90, 300: 36, 900: 20}

TRAIN_FRACTION = 0.55
EARLY_STOP_FRACTION = 0.10
CALIBRATION_FRACTION = 0.10
POLICY_FRACTION = 0.10
TEST_FRACTION = 0.15

BATCH_SIZE = 768
EPOCHS = 80
LEARNING_RATE = 5e-4
WEIGHT_DECAY = 1e-5
PATIENCE = 15
MIN_IMPROVEMENT = 1e-5
TRAINING_NOISE_STD = 0.003

BINARY_PAYOUT = 0.80
MIN_CONFIDENCE = 0.60
MIN_PROBABILITY_EDGE = 0.02
MIN_CALIBRATION_TRADES = 1_000
MIN_CALIBRATION_DAYS = 20
MIN_TEST_TRADES = 1_000
MIN_TEST_DAYS = 15
BOOTSTRAP_SAMPLES = 1_000
TRADE_COOLDOWN_SECONDS = 300
DEDUPLICATE_BASE_PER_TIMESTAMP = True
TRAIN_SEPARATE_REGIMES = (
    os.getenv("TRAIN_SEPARATE_REGIMES", "true").strip().lower()
    in {"1", "true", "yes", "on"}
)

RANDOM_SEED = 42
NUM_WORKERS = 0
ONNX_OPSET = 17
ONNX_TOLERANCE = 1e-4


FEATURES = [
    "open_pct",
    "high_pct",
    "low_pct",
    "close_pct",
    "dist_ema_20",
    "dist_ema_50",
    "atr_pct",
    "macd_hist",
    "roc_10",
    "rsi_14",
    "body_ratio",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "close_position",
    "stoch_k",
    "bb_percent_b",
    "hour_of_day",
    "day_of_week",
    "spread",
    "deal_count",
    "call_ratio",
    "traders_mood",
]

SPLIT_CODES = {
    "train": 0,
    "early_stop": 1,
    "calibration": 2,
    "policy": 3,
    "test": 4,
}


def validate_config() -> None:
    split_total = (
        TRAIN_FRACTION
        + EARLY_STOP_FRACTION
        + CALIBRATION_FRACTION
        + POLICY_FRACTION
        + TEST_FRACTION
    )
    if not math.isclose(split_total, 1.0, abs_tol=1e-9):
        raise ValueError(f"Split fractions total {split_total}, not 1.0")
    if set(TIMEFRAMES) != set(SEQUENCE_LENGTHS):
        raise ValueError("Every timeframe needs a sequence length")
    if not 0.0 < BINARY_PAYOUT <= 1.0:
        raise ValueError("BINARY_PAYOUT must be in (0, 1]")


def set_seed(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def package_version(name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def parse_timestamp(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series(
        pd.NaT, index=values.index, dtype="datetime64[ns, UTC]"
    )
    numeric_mask = numeric.notna()
    if numeric_mask.any():
        magnitude = float(numeric.loc[numeric_mask].abs().median())
        unit = (
            "ns"
            if magnitude >= 1e17
            else "us"
            if magnitude >= 1e14
            else "ms"
            if magnitude >= 1e11
            else "s"
        )
        result.loc[numeric_mask] = pd.to_datetime(
            numeric.loc[numeric_mask], unit=unit, utc=True, errors="coerce"
        )
    if (~numeric_mask).any():
        result.loc[~numeric_mask] = pd.to_datetime(
            values.loc[~numeric_mask], utc=True, errors="coerce"
        )
    return result


def load_candles(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"CSV not found: {path.resolve()}")
    frame = pd.read_csv(path)
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    frame = frame.rename(columns={"min": "low", "max": "high"})
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
        raise ValueError(f"Missing CSV columns: {missing}")

    frame["asset"] = frame["asset"].astype(str).str.strip().str.upper()
    frame["timeframe"] = pd.to_numeric(
        frame["timeframe"], errors="coerce"
    )
    observed = sorted(
        int(item) for item in frame["timeframe"].dropna().unique()
    )
    frame = frame.loc[frame["timeframe"].isin(TIMEFRAMES)].copy()
    absent = sorted(
        set(SOURCE_TIMEFRAMES).difference(frame["timeframe"].unique())
    )
    if absent:
        raise ValueError(
            f"Required source timeframes absent: {absent}; observed={observed}"
        )

    frame["timestamp"] = parse_timestamp(frame["timestamp"])
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    missing_values = frame[
        ["asset", "timestamp", "open", "high", "low", "close"]
    ].isna().any(axis=1)
    invalid_ohlc = (
        (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    bad = missing_values | invalid_ohlc
    if bad.any():
        print(f"Discarding {int(bad.sum()):,} malformed rows.")
        frame = frame.loc[~bad].copy()

    frame = frame.sort_values(
        ["asset", "timeframe", "timestamp"], kind="mergesort"
    )
    duplicate = frame.duplicated(
        ["asset", "timeframe", "timestamp"], keep="last"
    )
    if duplicate.any():
        print(f"Discarding {int(duplicate.sum()):,} duplicate rows.")
        frame = frame.loc[~duplicate].copy()

    source = frame.loc[frame["timeframe"].isin(SOURCE_TIMEFRAMES)].copy()
    counts = (
        source.groupby(["asset", "timeframe"])
        .size()
        .unstack(fill_value=0)
    )
    usable_assets = counts.index[
        (counts[list(SOURCE_TIMEFRAMES)] > 0).all(axis=1)
    ]
    removed = sorted(set(source["asset"]).difference(usable_assets))
    if removed:
        print(f"Removing assets without 2m and 5m sources: {removed}")
    source = source.loc[source["asset"].isin(usable_assets)].copy()
    if source.empty:
        raise ValueError("No asset has both required source timeframes")

    synthetic_15m = synthesize_15m_from_5m(source)
    frame = pd.concat([source, synthetic_15m], ignore_index=True)
    frame = frame.sort_values(
        ["asset", "timeframe", "timestamp"], kind="mergesort"
    ).reset_index(drop=True)

    print(
        f"Validated {len(frame):,} rows across "
        f"{frame['asset'].nunique()} assets; model timeframes={list(TIMEFRAMES)}"
    )
    print(
        "15m source: clock-aligned aggregation of complete 3×5m bars "
        "(native CSV 900s rows intentionally ignored)."
    )
    return frame.reset_index(drop=True)


def synthesize_15m_from_5m(source: pd.DataFrame) -> pd.DataFrame:
    """Aggregate only complete UTC-aligned groups at :00/:05/:10."""
    five = source.loc[source["timeframe"] == 300].copy()
    five = five.sort_values(["asset", "timestamp"], kind="mergesort")
    five["open_time_s"] = (
        five["timestamp"].astype("int64") // 1_000_000_000
    ).astype(np.int64)
    five["bucket_s"] = (five["open_time_s"] // 900) * 900

    grouped = (
        five.groupby(["asset", "bucket_s"], sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            row_count=("open_time_s", "size"),
            first_open_s=("open_time_s", "first"),
            last_open_s=("open_time_s", "last"),
        )
        .reset_index()
    )
    complete = grouped.loc[
        (grouped["row_count"] == 3)
        & (grouped["first_open_s"] == grouped["bucket_s"])
        & (grouped["last_open_s"] == grouped["bucket_s"] + 600)
    ].copy()
    if complete.empty:
        raise ValueError("No complete clock-aligned 3×5m groups for 15m")
    complete["timeframe"] = 900
    complete["timestamp"] = pd.to_datetime(
        complete["bucket_s"], unit="s", utc=True
    )
    return complete[
        ["asset", "timeframe", "timestamp", "open", "high", "low", "close"]
    ].reset_index(drop=True)


def add_features(segment: pd.DataFrame) -> pd.DataFrame:
    result = segment.copy()
    for column in ("open", "high", "low", "close"):
        result[f"{column}_pct"] = result[column].pct_change()

    ema_20 = ta.ema(result["close"], length=20)
    ema_50 = ta.ema(result["close"], length=50)
    result["dist_ema_20"] = result["close"].div(ema_20).sub(1.0)
    result["dist_ema_50"] = result["close"].div(ema_50).sub(1.0)
    atr_14 = ta.atr(
        result["high"], result["low"], result["close"], length=14
    )
    result["atr_pct"] = atr_14.div(result["close"])
    result["rsi_14"] = ta.rsi(result["close"], length=14).div(100.0)
    result["roc_10"] = result["close"].pct_change(10) * 100.0

    macd = ta.macd(result["close"], fast=12, slow=26, signal=9)
    stochastic = ta.stoch(
        result["high"], result["low"], result["close"], k=14, d=3
    )
    bands = ta.bbands(result["close"], length=20, std=2)
    if macd is None or stochastic is None or bands is None:
        raise ValueError("pandas-ta could not calculate indicators")
    result["macd_hist"] = macd.iloc[:, 1]
    result["stoch_k"] = stochastic.iloc[:, 0].div(100.0)
    result["bb_percent_b"] = bands.iloc[:, 4]

    candle_range = result["high"] - result["low"] + 1e-8
    body = result["close"] - result["open"]
    result["body_ratio"] = body.abs().div(candle_range)
    result["upper_wick_ratio"] = (
        result["high"] - result[["open", "close"]].max(axis=1)
    ).div(candle_range)
    result["lower_wick_ratio"] = (
        result[["open", "close"]].min(axis=1) - result["low"]
    ).div(candle_range)
    result["close_position"] = (
        result["close"] - result["low"]
    ).div(candle_range)
    result["hour_of_day"] = result["timestamp"].dt.hour.div(24.0)
    result["day_of_week"] = result["timestamp"].dt.dayofweek.div(7.0)
    
    # Telemetry fallbacks (if absent in legacy CSVs)
    if "spread" not in result.columns:
        result["spread"] = 0.0
    if "deal_count" not in result.columns:
        result["deal_count"] = 0.0
    if "call_ratio" not in result.columns:
        result["call_ratio"] = 0.5
    if "traders_mood" not in result.columns:
        result["traders_mood"] = 0.5
        
    # Causal regime router. Ambiguous rows are deliberately excluded when
    # separate-regime training is enabled.
    path_length = result["close"].diff().abs().rolling(20).sum()
    result["regime_efficiency"] = (
        result["close"].sub(result["close"].shift(20)).abs().div(path_length)
    )
    regime_fast_ma = result["close"].rolling(20).mean()
    regime_slow_ma = result["close"].rolling(50).mean()
    result["regime_ma_gap_atr"] = (
        regime_fast_ma.sub(regime_slow_ma)
        .abs()
        .div(atr_14.replace(0.0, np.nan))
    )
    trending = (
        result["regime_efficiency"].ge(0.35)
        | (
            result["regime_efficiency"].ge(0.28)
            & result["regime_ma_gap_atr"].ge(0.75)
        )
    )
    ranging = (
        result["regime_efficiency"].le(0.25)
        & result["regime_ma_gap_atr"].le(0.50)
    )
    result["regime_label"] = np.select(
        [trending, ranging], ["trending", "ranging"], default="ambiguous"
    )
    result.loc[:, FEATURES] = result[FEATURES].replace(
        [np.inf, -np.inf], np.nan
    )
    return result


def shared_cutoffs(candles: pd.DataFrame) -> Tuple[pd.Timestamp, ...]:
    base = candles.loc[candles["timeframe"] == BASE_TIMEFRAME].copy()
    decision_times = (
        base["timestamp"] + pd.to_timedelta(BASE_TIMEFRAME, unit="s")
    )
    timeline = pd.DatetimeIndex(decision_times.unique()).sort_values()
    if len(timeline) < 1_000:
        raise ValueError("Shared 2-minute timeline is too short")

    cumulative = (
        TRAIN_FRACTION,
        TRAIN_FRACTION + EARLY_STOP_FRACTION,
        TRAIN_FRACTION + EARLY_STOP_FRACTION + CALIBRATION_FRACTION,
        TRAIN_FRACTION
        + EARLY_STOP_FRACTION
        + CALIBRATION_FRACTION
        + POLICY_FRACTION,
    )
    positions = [
        min(len(timeline) - 1, max(0, int(len(timeline) * value) - 1))
        for value in cumulative
    ]
    cutoffs = tuple(timeline[position] for position in positions)
    print(
        "Shared decision-time cutoffs: "
        f"train≤{cutoffs[0]}, early-stop≤{cutoffs[1]}, "
        f"calibration≤{cutoffs[2]}, policy≤{cutoffs[3]}, then test"
    )
    return cutoffs


def assign_split_codes(
    close_times: pd.Series, cutoffs: Tuple[pd.Timestamp, ...]
) -> np.ndarray:
    codes = np.full(len(close_times), SPLIT_CODES["test"], dtype=np.int8)
    codes[close_times.le(cutoffs[3]).to_numpy()] = SPLIT_CODES["policy"]
    codes[close_times.le(cutoffs[2]).to_numpy()] = SPLIT_CODES["calibration"]
    codes[close_times.le(cutoffs[1]).to_numpy()] = SPLIT_CODES["early_stop"]
    codes[close_times.le(cutoffs[0]).to_numpy()] = SPLIT_CODES["train"]
    return codes


def prepare_frames(
    candles: pd.DataFrame,
) -> Tuple[Dict[str, Dict[int, pd.DataFrame]], Tuple[pd.Timestamp, ...]]:
    cutoffs = shared_cutoffs(candles)
    result: Dict[str, Dict[int, pd.DataFrame]] = {}
    segment_counter = 0

    for asset in sorted(candles["asset"].unique()):
        asset_frames: Dict[int, pd.DataFrame] = {}
        complete = True
        for timeframe in TIMEFRAMES:
            raw = candles.loc[
                (candles["asset"] == asset)
                & (candles["timeframe"] == timeframe)
            ].sort_values("timestamp")
            raw = raw.reset_index(drop=True)
            gap_ids = (
                raw["timestamp"]
                .diff()
                .dt.total_seconds()
                .ne(timeframe)
                .cumsum()
            )
            gap_count = max(0, int(gap_ids.nunique()) - 1)
            if gap_count:
                print(f"{asset} {timeframe}s: {gap_count} gap(s)")

            parts: List[pd.DataFrame] = []
            for _, segment in raw.groupby(gap_ids, sort=False):
                minimum = max(80, SEQUENCE_LENGTHS[timeframe] + 55)
                if len(segment) < minimum:
                    continue
                segment = segment.copy().reset_index(drop=True)
                if timeframe == BASE_TIMEFRAME:
                    next_close = segment["close"].shift(-1)
                    segment["target"] = np.where(
                        next_close > segment["close"],
                        1.0,
                        np.where(
                            next_close < segment["close"], 0.0, np.nan
                        ),
                    )
                    segment.loc[next_close.isna(), "target"] = np.nan
                else:
                    segment["target"] = np.nan

                featured = add_features(segment)
                featured = featured.dropna(subset=FEATURES).copy()
                if len(featured) < SEQUENCE_LENGTHS[timeframe] + 2:
                    continue
                featured["segment_id"] = segment_counter
                segment_counter += 1
                parts.append(featured)

            if not parts:
                complete = False
                break
            frame = pd.concat(parts, ignore_index=True)
            frame = frame.sort_values("timestamp").reset_index(drop=True)
            frame["open_time_s"] = (
                frame["timestamp"].astype("int64") // 1_000_000_000
            ).astype(np.int64)
            frame["close_time_s"] = (
                frame["open_time_s"] + int(timeframe)
            ).astype(np.int64)
            close_times = pd.to_datetime(
                frame["close_time_s"], unit="s", utc=True
            )
            frame["split_code"] = assign_split_codes(close_times, cutoffs)

            if timeframe == BASE_TIMEFRAME:
                last_indices = (
                    frame.groupby(
                        ["segment_id", "split_code"], sort=False
                    )
                    .tail(1)
                    .index
                )
                frame.loc[last_indices, "target"] = np.nan
            asset_frames[timeframe] = frame

        if complete and len(asset_frames) == len(TIMEFRAMES):
            result[asset] = asset_frames

    if not result:
        raise ValueError("No assets produced complete MTF feature frames")
    print(f"Prepared complete MTF frames for {len(result)} assets.")
    return result, cutoffs


@dataclass
class MTFBlock:
    asset: str
    asset_id: int
    split: str
    values_2m: np.ndarray
    values_5m: np.ndarray
    values_15m: np.ndarray
    end_2m: np.ndarray
    end_5m: np.ndarray
    end_15m: np.ndarray
    targets: np.ndarray
    decision_times: np.ndarray
    regimes: np.ndarray


def _valid_sequence_ends(
    frame: pd.DataFrame,
    endpoints: np.ndarray,
    length: int,
    split_code: int,
) -> np.ndarray:
    valid = endpoints >= length - 1
    safe_end = np.clip(endpoints, 0, len(frame) - 1)
    safe_start = np.clip(safe_end - length + 1, 0, len(frame) - 1)
    segments = frame["segment_id"].to_numpy()
    splits = frame["split_code"].to_numpy()
    valid &= segments[safe_start] == segments[safe_end]
    valid &= splits[safe_start] == split_code
    valid &= splits[safe_end] == split_code
    return valid


def build_blocks(
    frames: Dict[str, Dict[int, pd.DataFrame]],
    assets: Sequence[str],
) -> Dict[str, List[MTFBlock]]:
    blocks: Dict[str, List[MTFBlock]] = {
        name: [] for name in SPLIT_CODES
    }

    for asset_id, asset in enumerate(assets):
        by_tf = frames[asset]
        base = by_tf[120]
        mid = by_tf[300]
        high = by_tf[900]
        decision_all = base["close_time_s"].to_numpy(dtype=np.int64)
        mid_close = mid["close_time_s"].to_numpy(dtype=np.int64)
        high_close = high["close_time_s"].to_numpy(dtype=np.int64)
        base_targets = base["target"].to_numpy(dtype=np.float32)
        # Share one feature matrix per asset/timeframe across all four split
        # blocks. Recreating the full arrays per split would multiply memory
        # use on free cloud runtimes.
        values_2m = base[FEATURES].to_numpy(dtype=np.float32)
        values_5m = mid[FEATURES].to_numpy(dtype=np.float32)
        values_15m = high[FEATURES].to_numpy(dtype=np.float32)

        for split_name, split_code in SPLIT_CODES.items():
            end_2m = np.flatnonzero(
                (base["split_code"].to_numpy() == split_code)
                & np.isfinite(base_targets)
            ).astype(np.int64)
            if end_2m.size == 0:
                continue
            decisions = decision_all[end_2m]
            end_5m = (
                np.searchsorted(mid_close, decisions, side="right") - 1
            ).astype(np.int64)
            end_15m = (
                np.searchsorted(high_close, decisions, side="right") - 1
            ).astype(np.int64)

            valid = _valid_sequence_ends(
                base, end_2m, SEQUENCE_LENGTHS[120], split_code
            )
            valid &= _valid_sequence_ends(
                mid, end_5m, SEQUENCE_LENGTHS[300], split_code
            )
            valid &= _valid_sequence_ends(
                high, end_15m, SEQUENCE_LENGTHS[900], split_code
            )

            safe_5m = np.clip(end_5m, 0, len(mid) - 1)
            safe_15m = np.clip(end_15m, 0, len(high) - 1)
            lag_5m = decisions - mid_close[safe_5m]
            lag_15m = decisions - high_close[safe_15m]
            valid &= (lag_5m >= 0) & (lag_5m < 300)
            valid &= (lag_15m >= 0) & (lag_15m < 900)

            end_2m = end_2m[valid]
            end_5m = end_5m[valid]
            end_15m = end_15m[valid]
            if end_2m.size == 0:
                continue

            block = MTFBlock(
                asset=asset,
                asset_id=asset_id,
                split=split_name,
                values_2m=values_2m,
                values_5m=values_5m,
                values_15m=values_15m,
                end_2m=end_2m,
                end_5m=end_5m,
                end_15m=end_15m,
                targets=base_targets[end_2m],
                decision_times=decision_all[end_2m],
                regimes=base["regime_label"].to_numpy(dtype=object)[end_2m],
            )
            blocks[split_name].append(block)
            print(
                f"{asset} {split_name}: {len(end_2m):,} aligned samples"
            )

    missing = [name for name, values in blocks.items() if not values]
    if missing:
        raise ValueError(f"No aligned MTF samples for splits: {missing}")
    return blocks


def regime_blocks(
    blocks: Dict[str, List[MTFBlock]], regime: str
) -> Dict[str, List[MTFBlock]]:
    selected: Dict[str, List[MTFBlock]] = {name: [] for name in blocks}
    for split_name, split_blocks in blocks.items():
        for block in split_blocks:
            mask = block.regimes == regime
            if not mask.any():
                continue
            selected[split_name].append(
                MTFBlock(
                    asset=block.asset,
                    asset_id=block.asset_id,
                    split=block.split,
                    values_2m=block.values_2m,
                    values_5m=block.values_5m,
                    values_15m=block.values_15m,
                    end_2m=block.end_2m[mask],
                    end_5m=block.end_5m[mask],
                    end_15m=block.end_15m[mask],
                    targets=block.targets[mask],
                    decision_times=block.decision_times[mask],
                    regimes=block.regimes[mask],
                )
            )
    missing = [name for name, values in selected.items() if not values]
    if missing:
        raise ValueError(f"{regime} has no samples for splits: {missing}")
    return selected


def fit_scalers(
    frames: Dict[str, Dict[int, pd.DataFrame]]
) -> Dict[int, RobustScaler]:
    scalers: Dict[int, RobustScaler] = {}
    train_code = SPLIT_CODES["train"]
    for timeframe in TIMEFRAMES:
        rows = np.concatenate(
            [
                by_tf[timeframe]
                .loc[by_tf[timeframe]["split_code"] == train_code, FEATURES]
                .to_numpy(dtype=np.float32)
                for by_tf in frames.values()
            ],
            axis=0,
        )
        if not np.isfinite(rows).all():
            raise ValueError(f"Non-finite {timeframe}s scaler rows")
        scaler = RobustScaler().fit(rows)
        scalers[timeframe] = scaler
    return scalers


def scale_blocks(
    blocks: Dict[str, List[MTFBlock]],
    scalers: Dict[int, RobustScaler],
) -> None:
    # A block contains the full asset frame and appears once per split. Cache
    # transformed arrays by original array identity to avoid repeated work.
    cache: Dict[Tuple[int, int], np.ndarray] = {}
    for split_blocks in blocks.values():
        for block in split_blocks:
            for timeframe, attribute in (
                (120, "values_2m"),
                (300, "values_5m"),
                (900, "values_15m"),
            ):
                values = getattr(block, attribute)
                key = (timeframe, id(values))
                transformed = cache.get(key)
                if transformed is None:
                    transformed = scalers[timeframe].transform(values).astype(
                        np.float32
                    )
                    if not np.isfinite(transformed).all():
                        raise ValueError(
                            f"Non-finite scaled {timeframe}s features"
                        )
                    cache[key] = transformed
                setattr(block, attribute, transformed)


class MTFDataset(Dataset):
    def __init__(self, blocks: Sequence[MTFBlock]) -> None:
        self.blocks = list(blocks)
        self.cumulative: List[int] = []
        total = 0
        for block in self.blocks:
            total += len(block.targets)
            self.cumulative.append(total)

    def __len__(self) -> int:
        return self.cumulative[-1] if self.cumulative else 0

    def __getitem__(self, index: int):
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        block_index = bisect.bisect_right(self.cumulative, index)
        previous = self.cumulative[block_index - 1] if block_index else 0
        local = index - previous
        block = self.blocks[block_index]

        def sequence(values: np.ndarray, end: int, length: int):
            return torch.from_numpy(values[end - length + 1 : end + 1])

        return (
            sequence(
                block.values_2m,
                int(block.end_2m[local]),
                SEQUENCE_LENGTHS[120],
            ),
            sequence(
                block.values_5m,
                int(block.end_5m[local]),
                SEQUENCE_LENGTHS[300],
            ),
            sequence(
                block.values_15m,
                int(block.end_15m[local]),
                SEQUENCE_LENGTHS[900],
            ),
            torch.tensor(block.asset_id, dtype=torch.long),
            torch.tensor(block.targets[local], dtype=torch.float32),
        )

    def metadata(self) -> Tuple[np.ndarray, np.ndarray]:
        assets: List[str] = []
        times: List[np.ndarray] = []
        for block in self.blocks:
            assets.extend([block.asset] * len(block.targets))
            times.append(block.decision_times)
        return np.asarray(assets, dtype=object), np.concatenate(times)

    def targets(self) -> np.ndarray:
        return np.concatenate([block.targets for block in self.blocks])


class MTFModel(nn.Module):
    def __init__(self, feature_count: int, asset_count: int) -> None:
        super().__init__()
        self.lstm_2m = nn.LSTM(
            feature_count, 64, num_layers=2, batch_first=True, dropout=0.10
        )
        self.lstm_5m = nn.LSTM(
            feature_count, 40, num_layers=1, batch_first=True
        )
        self.lstm_15m = nn.LSTM(
            feature_count, 32, num_layers=1, batch_first=True
        )
        self.asset_embedding = nn.Embedding(asset_count, 8)
        self.head = nn.Sequential(
            nn.Linear(64 + 40 + 32 + 8, 72),
            nn.ReLU(),
            nn.Dropout(0.15),
            nn.Linear(72, 24),
            nn.ReLU(),
            nn.Dropout(0.10),
            nn.Linear(24, 1),
        )

    @staticmethod
    def _last(lstm: nn.LSTM, values: torch.Tensor) -> torch.Tensor:
        output, _ = lstm(values)
        return output[:, -1, :]

    def forward(
        self,
        input_2m: torch.Tensor,
        input_5m: torch.Tensor,
        input_15m: torch.Tensor,
        asset_id: torch.Tensor,
    ) -> torch.Tensor:
        encoded = torch.cat(
            [
                self._last(self.lstm_2m, input_2m),
                self._last(self.lstm_5m, input_5m),
                self._last(self.lstm_15m, input_15m),
                self.asset_embedding(asset_id),
            ],
            dim=1,
        )
        return self.head(encoded).squeeze(-1)


class CalibratedMTFModel(nn.Module):
    def __init__(self, model: MTFModel, temperature: float) -> None:
        super().__init__()
        self.model = model
        self.register_buffer(
            "temperature", torch.tensor(temperature, dtype=torch.float32)
        )

    def forward(self, input_2m, input_5m, input_15m, asset_id):
        return (
            self.model(input_2m, input_5m, input_15m, asset_id)
            / self.temperature.clamp_min(1e-6)
        )


def make_loader(
    dataset: Dataset, shuffle: bool, device: torch.device
) -> DataLoader:
    return DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=shuffle,
        num_workers=NUM_WORKERS,
        pin_memory=device.type == "cuda",
        drop_last=False,
    )


def move_batch(batch, device: torch.device):
    x2, x5, x15, asset_ids, targets = batch
    return (
        x2.to(device, non_blocking=True),
        x5.to(device, non_blocking=True),
        x15.to(device, non_blocking=True),
        asset_ids.to(device, non_blocking=True),
        targets.to(device, non_blocking=True),
    )


@torch.no_grad()
def validation_loss(model, loader, criterion, device) -> float:
    model.eval()
    total = 0.0
    rows = 0
    for batch in loader:
        x2, x5, x15, asset_ids, targets = move_batch(batch, device)
        loss = criterion(model(x2, x5, x15, asset_ids), targets)
        total += float(loss.item()) * len(targets)
        rows += len(targets)
    return total / max(rows, 1)


def train_model(model, train_loader, stop_loader, device):
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=4, min_lr=1e-6
    )
    best_loss = float("inf")
    best_state = copy.deepcopy(model.state_dict())
    stale_epochs = 0
    history: List[Dict[str, float]] = []

    print("\n--- Starting causal MTF training ---")
    for epoch in range(EPOCHS):
        model.train()
        total = 0.0
        rows = 0
        for batch in train_loader:
            x2, x5, x15, asset_ids, targets = move_batch(batch, device)
            if TRAINING_NOISE_STD:
                x2 = x2 + torch.randn_like(x2) * TRAINING_NOISE_STD
                x5 = x5 + torch.randn_like(x5) * TRAINING_NOISE_STD
                x15 = x15 + torch.randn_like(x15) * TRAINING_NOISE_STD
            optimizer.zero_grad(set_to_none=True)
            logits = model(x2, x5, x15, asset_ids)
            loss = criterion(logits, targets)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total += float(loss.item()) * len(targets)
            rows += len(targets)

        train_loss = total / max(rows, 1)
        stop_loss = validation_loss(model, stop_loader, criterion, device)
        scheduler.step(stop_loss)
        lr = float(optimizer.param_groups[0]["lr"])
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "early_stop_loss": stop_loss,
                "learning_rate": lr,
            }
        )
        print(
            f"Epoch {epoch:03d} | train={train_loss:.5f} | "
            f"early_stop={stop_loss:.5f} | lr={lr:.2e}"
        )
        if stop_loss < best_loss - MIN_IMPROVEMENT:
            best_loss = stop_loss
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= PATIENCE:
                print(f"Early stopping at epoch {epoch}.")
                break

    model.load_state_dict(best_state)
    return model, pd.DataFrame(history)


@torch.no_grad()
def predict(model, loader, device) -> Tuple[np.ndarray, np.ndarray]:
    model.eval()
    logits: List[np.ndarray] = []
    targets: List[np.ndarray] = []
    for batch in loader:
        x2, x5, x15, asset_ids, labels = move_batch(batch, device)
        logits.append(
            model(x2, x5, x15, asset_ids).detach().cpu().numpy()
        )
        targets.append(labels.cpu().numpy())
    return (
        np.concatenate(logits).astype(np.float64),
        np.concatenate(targets).astype(np.int64),
    )


def fit_temperature(logits: np.ndarray, targets: np.ndarray) -> float:
    logits_t = torch.tensor(logits, dtype=torch.float64)
    targets_t = torch.tensor(targets, dtype=torch.float64)
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

    def closure():
        optimizer.zero_grad()
        temperature = log_temperature.exp().clamp(0.05, 20.0)
        loss = criterion(logits_t / temperature, targets_t)
        loss.backward()
        return loss

    optimizer.step(closure)
    return float(log_temperature.detach().exp().clamp(0.05, 20.0))


def sigmoid(logits: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))


def expectancy(win_rate: float) -> float:
    return win_rate * BINARY_PAYOUT - (1.0 - win_rate)


def executable_indices(
    probabilities: np.ndarray,
    assets: np.ndarray,
    times: np.ndarray,
    threshold: float,
) -> np.ndarray:
    confidence = np.maximum(probabilities, 1.0 - probabilities)
    candidates = np.flatnonzero(confidence >= threshold)
    if candidates.size == 0:
        return candidates.astype(np.int64)
    table = pd.DataFrame(
        {
            "index": candidates,
            "asset": assets[candidates],
            "time": times[candidates],
            "confidence": confidence[candidates],
        }
    )
    table["base"] = table["asset"].str.slice(0, 3)
    table = table.sort_values(
        ["time", "confidence", "asset"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    if DEDUPLICATE_BASE_PER_TIMESTAMP:
        table = table.drop_duplicates(["time", "base"], keep="first")
    accepted: List[int] = []
    last_by_asset: Dict[str, int] = {}
    for row in table.itertuples(index=False):
        previous = last_by_asset.get(row.asset)
        if (
            previous is not None
            and int(row.time) - previous < TRADE_COOLDOWN_SECONDS
        ):
            continue
        accepted.append(int(row.index))
        last_by_asset[row.asset] = int(row.time)
    return np.asarray(accepted, dtype=np.int64)


def bootstrap_lower(
    correct: np.ndarray, times: np.ndarray, seed: int
) -> Tuple[float, float]:
    days = times // 86_400
    unique_days = np.unique(days)
    if len(unique_days) < 2:
        return float("nan"), float("nan")
    wins = np.asarray(
        [correct[days == day].sum() for day in unique_days], dtype=float
    )
    trades = np.asarray(
        [(days == day).sum() for day in unique_days], dtype=float
    )
    rng = np.random.default_rng(seed)
    rates = np.empty(BOOTSTRAP_SAMPLES, dtype=float)
    for iteration in range(BOOTSTRAP_SAMPLES):
        chosen = rng.integers(0, len(unique_days), len(unique_days))
        rates[iteration] = wins[chosen].sum() / trades[chosen].sum()
    lower = float(np.quantile(rates, 0.025))
    return lower, expectancy(lower)


def trade_metrics(
    probabilities,
    targets,
    assets,
    times,
    threshold,
    seed=RANDOM_SEED,
) -> Dict[str, float]:
    selected = executable_indices(probabilities, assets, times, threshold)
    if selected.size == 0:
        return {
            "threshold": float(threshold),
            "trades": 0,
            "days": 0,
            "coverage": 0.0,
            "win_rate": float("nan"),
            "lower_win_rate": float("nan"),
            "expectancy": float("nan"),
            "lower_expectancy": float("nan"),
        }
    predicted = (probabilities[selected] >= 0.5).astype(np.int64)
    correct = (predicted == targets[selected]).astype(float)
    win_rate = float(correct.mean())
    lower, lower_ev = bootstrap_lower(correct, times[selected], seed)
    return {
        "threshold": float(threshold),
        "trades": int(len(selected)),
        "days": int(np.unique(times[selected] // 86_400).size),
        "coverage": float(len(selected) / len(targets)),
        "win_rate": win_rate,
        "lower_win_rate": lower,
        "expectancy": expectancy(win_rate),
        "lower_expectancy": lower_ev,
    }


def choose_threshold(probabilities, targets, assets, times):
    breakeven = 1.0 / (1.0 + BINARY_PAYOUT)
    start = max(
        MIN_CONFIDENCE,
        math.ceil((breakeven + MIN_PROBABILITY_EDGE) * 100) / 100,
    )
    thresholds = np.round(np.arange(start, 0.991, 0.01), 2)
    rows = [
        trade_metrics(
            probabilities,
            targets,
            assets,
            times,
            threshold,
            RANDOM_SEED + index,
        )
        for index, threshold in enumerate(thresholds)
    ]
    table = pd.DataFrame(rows)
    eligible = table.loc[
        (table["trades"] >= MIN_CALIBRATION_TRADES)
        & (table["days"] >= MIN_CALIBRATION_DAYS)
        & table["lower_expectancy"].notna()
    ]
    if eligible.empty:
        reason = (
            "No threshold met calibration requirements. "
            f"Maximum trades={int(table['trades'].max())}, "
            f"maximum trade days={int(table['days'].max())}."
        )
        return start, table, False, reason
    best = eligible.sort_values(
        ["lower_expectancy", "trades", "threshold"],
        ascending=[False, False, False],
    ).iloc[0]
    return (
        float(best["threshold"]),
        table,
        True,
        "Selected by maximum daily-bootstrap lower expectancy.",
    )


def safe_auc(targets, probabilities) -> float:
    if np.unique(targets).size < 2:
        return float("nan")
    return float(roc_auc_score(targets, probabilities))


def export_and_verify(
    model,
    temperature,
    asset_count,
    dataset: MTFDataset,
    path: Path,
) -> Tuple[bool, Optional[float], str]:
    calibrated = CalibratedMTFModel(copy.deepcopy(model).cpu(), temperature)
    calibrated.eval()
    dummy = (
        torch.zeros(1, SEQUENCE_LENGTHS[120], len(FEATURES)),
        torch.zeros(1, SEQUENCE_LENGTHS[300], len(FEATURES)),
        torch.zeros(1, SEQUENCE_LENGTHS[900], len(FEATURES)),
        torch.zeros(1, dtype=torch.long),
    )
    try:
        torch.onnx.export(
            calibrated,
            dummy,
            str(path),
            input_names=["input_2m", "input_5m", "input_15m", "asset_id"],
            output_names=["logit"],
            opset_version=ONNX_OPSET,
            do_constant_folding=True,
            dynamo=False,
        )
    except Exception as error:
        return False, None, f"ONNX export failed: {type(error).__name__}: {error}"

    try:
        import onnxruntime as ort
    except ImportError:
        return False, None, "onnxruntime is not installed"

    x2, x5, x15, asset_id, _ = dataset[0]
    inputs = (
        x2.unsqueeze(0),
        x5.unsqueeze(0),
        x15.unsqueeze(0),
        asset_id.reshape(1),
    )
    with torch.no_grad():
        expected = calibrated(*inputs).numpy().reshape(-1)
    session = ort.InferenceSession(
        str(path), providers=["CPUExecutionProvider"]
    )
    actual = session.run(
        ["logit"],
        {
            "input_2m": inputs[0].numpy(),
            "input_5m": inputs[1].numpy(),
            "input_15m": inputs[2].numpy(),
            "asset_id": inputs[3].numpy().astype(np.int64),
        },
    )[0].reshape(-1)
    error = float(np.max(np.abs(expected - actual)))
    passed = error <= ONNX_TOLERANCE
    reason = (
        f"max absolute error={error:.6g}"
        if passed
        else f"parity error {error:.6g} exceeds {ONNX_TOLERANCE}"
    )
    return passed, error, reason


def json_ready(value):
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def run_experiment(
    regime,
    blocks,
    assets,
    scalers,
    cutoffs,
    device,
    dataset_id,
    dataset_sha256,
):
    output_dir = ARTIFACT_DIR / regime
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets = {
        name: MTFDataset(values) for name, values in blocks.items()
    }
    print(f"\n{'=' * 24} {regime.upper()} {'=' * 24}")
    for name, dataset in datasets.items():
        print(
            f"{name:12s}: {len(dataset):,}; "
            f"target-up={dataset.targets().mean():.3%}"
        )
    loaders = {
        name: make_loader(dataset, name == "train", device)
        for name, dataset in datasets.items()
    }
    model = MTFModel(len(FEATURES), len(assets)).to(device)
    model, history = train_model(
        model, loaders["train"], loaders["early_stop"], device
    )
    cal_logits, cal_targets = predict(
        model, loaders["calibration"], device
    )
    temperature = fit_temperature(cal_logits, cal_targets)
    cal_probability = sigmoid(cal_logits / temperature)
    cal_assets, cal_times = datasets["calibration"].metadata()
    policy_logits, policy_targets = predict(model, loaders["policy"], device)
    policy_probability = sigmoid(policy_logits / temperature)
    policy_assets, policy_times = datasets["policy"].metadata()
    threshold, threshold_table, threshold_passed, threshold_reason = (
        choose_threshold(
            policy_probability, policy_targets, policy_assets, policy_times
        )
    )
    cal_metrics = trade_metrics(
        cal_probability, cal_targets, cal_assets, cal_times, threshold
    )
    policy_metrics = trade_metrics(
        policy_probability,
        policy_targets,
        policy_assets,
        policy_times,
        threshold,
    )
    test_logits, test_targets = predict(model, loaders["test"], device)
    test_probability = sigmoid(test_logits / temperature)
    test_assets, test_times = datasets["test"].metadata()
    test_accuracy = float(
        accuracy_score(test_targets, test_probability >= 0.5)
    )
    test_auc = safe_auc(test_targets, test_probability)
    test_metrics = trade_metrics(
        test_probability,
        test_targets,
        test_assets,
        test_times,
        threshold,
        RANDOM_SEED + 10_000,
    )
    onnx_path = output_dir / f"{regime}_mtf_lstm.onnx"
    onnx_passed, onnx_error, onnx_reason = export_and_verify(
        model, temperature, len(assets), datasets["test"], onnx_path
    )
    scaler_path = output_dir / "mtf_scalers.pkl"
    state_path = output_dir / "model_state.pt"
    joblib.dump(scalers, scaler_path)
    torch.save(
        {
            "state_dict": {
                key: value.detach().cpu()
                for key, value in model.state_dict().items()
            },
            "assets": assets,
            "features": FEATURES,
            "sequence_lengths": SEQUENCE_LENGTHS,
            "temperature": temperature,
            "regime": regime,
        },
        state_path,
    )
    promotion = assess_offline_promotion(
        independent_policy_partition=True,
        strict_provenance_manifest=True,
        threshold_selection_passed=threshold_passed,
        inference_parity_passed=onnx_passed,
        calibration_lower_expectancy=float(policy_metrics["lower_expectancy"]),
        test_lower_expectancy=float(test_metrics["lower_expectancy"]),
        test_trades=int(test_metrics["trades"]),
        minimum_test_trades=MIN_TEST_TRADES,
        test_days=int(test_metrics["days"]),
        minimum_test_days=MIN_TEST_DAYS,
    )
    approved = promotion.approved
    metadata = {
        "model_version": "causal_regime_mtf_lstm_v5",
        "regime": regime,
        "regime_router": {
            "trending": "ER20>=0.35 or (ER20>=0.28 and SMA20_50_gap/ATR14>=0.75)",
            "ranging": "ER20<=0.25 and SMA20_50_gap/ATR14<=0.50",
            "otherwise": "ambiguous: abstain",
        },
        "target": "next contiguous 120-second close direction; ties excluded",
        "features": FEATURES,
        "sequence_lengths": SEQUENCE_LENGTHS,
        "assets": assets,
        "asset_to_id": {asset: index for index, asset in enumerate(assets)},
        "temperature": temperature,
        "threshold": threshold,
        "threshold_selection_passed": threshold_passed,
        "threshold_selection_reason": threshold_reason,
        "sample_counts": {
            name: len(dataset) for name, dataset in datasets.items()
        },
        "calibration_metrics": cal_metrics,
        "policy_metrics": policy_metrics,
        "test_accuracy": test_accuracy,
        "test_roc_auc": test_auc,
        "test_actionable_metrics": test_metrics,
        "onnx_verification_passed": onnx_passed,
        "onnx_verification_reason": onnx_reason,
        "onnx_max_absolute_error": onnx_error,
        "deployment_approved": approved,
        "deployment_gate_reasons": list(promotion.reasons),
        "independent_policy_partition": True,
        "strict_provenance_manifest": True,
        "split_cutoffs": [item.isoformat() for item in cutoffs],
    }
    with (output_dir / "metadata.pkl").open("wb") as handle:
        pickle.dump(metadata, handle)
    with (output_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(json_ready(metadata), handle, indent=2)
    history.to_csv(output_dir / "training_history.csv", index=False)
    threshold_table.to_csv(
        output_dir / "calibration_thresholds.csv", index=False
    )
    split_windows = {}
    for name, dataset in datasets.items():
        _, timestamps = dataset.metadata()
        split_windows[name] = (
            datetime.fromtimestamp(int(timestamps.min()), tz=UTC),
            datetime.fromtimestamp(int(timestamps.max()), tz=UTC),
            len(dataset),
        )
    artifact_paths = {
        "model_state": state_path,
        "scalers": scaler_path,
    }
    if onnx_path.is_file():
        artifact_paths["onnx"] = onnx_path
    manifest = build_calibration_manifest(
        model_version=f"causal_regime_mtf_lstm_v5-{regime}",
        method="temperature_scaling",
        target_definition="next contiguous 120-second close direction; ties excluded",
        dataset_id=dataset_id,
        dataset_sha256=dataset_sha256,
        split_windows=split_windows,
        test_metrics={
            "brier_score": brier_score_loss(test_targets, test_probability),
            "log_loss": log_loss(test_targets, test_probability, labels=[0, 1]),
        },
        artifact_paths=artifact_paths,
        offline_deployment_approved=approved,
    )
    with (output_dir / "calibration_provenance.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(manifest, handle, indent=2)
    metadata["calibration_id"] = manifest["calibration_id"]
    with (output_dir / "metadata.pkl").open("wb") as handle:
        pickle.dump(metadata, handle)
    with (output_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(json_ready(metadata), handle, indent=2)
    print(
        f"{regime}: AUC={test_auc:.4f}, accuracy={test_accuracy:.2%}, "
        f"approved={approved}, actionable={test_metrics}"
    )
    del model, loaders, datasets
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return metadata


def main() -> None:
    validate_config()
    set_seed(RANDOM_SEED)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    dataset_fingerprint = fingerprint_dataset(DATA_FILE)
    dataset_id = os.getenv(
        "TRAINING_DATASET_ID",
        f"sha256-{str(dataset_fingerprint['sha256'])[:20]}",
    )
    print("=" * 72)
    print("CAUSAL OTC REGIME-SPECIFIC MULTI-TIMEFRAME LSTM v5")
    print("=" * 72)
    candles = load_candles(DATA_FILE)
    frames, cutoffs = prepare_frames(candles)
    assets = sorted(frames)
    all_blocks = build_blocks(frames, assets)
    scalers = fit_scalers(frames)
    scale_blocks(all_blocks, scalers)
    experiments = (
        {
            "trending": regime_blocks(all_blocks, "trending"),
            "ranging": regime_blocks(all_blocks, "ranging"),
        }
        if TRAIN_SEPARATE_REGIMES
        else {"global": all_blocks}
    )
    del candles, frames, all_blocks
    gc.collect()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    summaries = {
        name: run_experiment(
            name,
            blocks,
            assets,
            scalers,
            cutoffs,
            device,
            dataset_id,
            str(dataset_fingerprint["sha256"]),
        )
        for name, blocks in experiments.items()
    }
    require_unchanged_dataset(DATA_FILE, dataset_fingerprint)
    with (ARTIFACT_DIR / "regime_summary.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(json_ready(summaries), handle, indent=2)
    print(
        "\nBoth models must independently pass their gates. Ambiguous regimes "
        "always abstain; never substitute one model for the other."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)
    except Exception as error:
        print(f"\nFATAL: {type(error).__name__}: {error}", file=sys.stderr)
        raise
