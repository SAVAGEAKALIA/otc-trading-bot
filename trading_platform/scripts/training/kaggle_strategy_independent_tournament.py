#!/usr/bin/env python3
"""
Strategy-independent cross-asset IQ Option model tournament for Kaggle.

This file intentionally does not import or replay any strategy from the bot.
It asks whether the completed IQ candle state itself contains a repeatable,
payout-usable directional signal.

Tournament entrants
-------------------
1. Constant/base-rate null model
2. Regularized linear SGD classifier
3. CatBoost on stationary 2m + causally aligned native 5m/15m features,
   synchronized cross-asset returns, breadth and currency factors
4. Optional temporal-contrastive TCN:
   - self-supervised contrastive pretraining
   - frozen encoder head
   - supervised fine-tuning with 2m/4m/6m auxiliary targets

Scientific protections
----------------------
* Entry is the next exact 2m candle open.
* Higher-timeframe features become available only when their candle closes.
* Splits are global, chronological and purged.
* Calibration, model/policy selection and final testing use different periods.
* The policy period chooses exactly one model, confidence threshold and
  cross-sectional top-k setting.
* Only that frozen winner is evaluated on the untouched final test.
* Daily block bootstrap estimates the lower 95% expectancy bound.
* No strategy score, indicator direction or future price is a model feature.
* Cross-asset information uses only bars completed at the decision timestamp.
* Currency factors exclude the target pair from its own factor calculation.

Expected input schema
---------------------
asset, timeframe, timestamp, open, close, min, max, volume

Aliases such as high/low/from/at are accepted. Native 120s, 300s and 900s IQ
candles are required by default.

This remains historical research. It cannot reproduce broker order
acknowledgement, accepted strike, rejection, payout changes or settlement
discrepancies. Any successful result must be verified in PRACTICE mode.
"""

from __future__ import annotations

import copy
import hashlib
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
from typing import Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer


# =============================================================================
# EDIT ONLY THIS CONFIGURATION BLOCK IN KAGGLE
# =============================================================================


@dataclass(frozen=True)
class Config:
    # None automatically finds the largest candle-like CSV in /kaggle/input.
    # Otherwise use e.g. "/kaggle/input/iq-candles/candles_export.csv".
    data_path: Optional[str] = None
    output_dir: str = "/kaggle/working/strategy_independent_tournament"

    entry_timeframe_seconds: int = 120
    higher_timeframes_seconds: Tuple[int, int] = (300, 900)
    prediction_horizons_minutes: Tuple[int, int, int] = (2, 4, 6)
    # Every listed horizon competes on the policy period. This field is used
    # only for inventory summaries and backward-compatible diagnostics.
    primary_horizon_minutes: int = 2
    require_native_higher_timeframes: bool = True
    binary_payout: float = 0.80
    # The July 9-27 period was summarized by the earlier tournament. Panel
    # relationships were not inspected, so it remains useful exploratory data,
    # but it is no longer a pristine confirmatory holdout. Keep this True for
    # the current export. Set False only when the final partition consists of
    # genuinely new, previously unseen candles.
    holdout_previously_summarized: bool = True

    # The final no-new-data directional hypothesis: other OTC pairs may lead
    # or contextualize the target pair. All source values are synchronized at
    # completed-candle decision timestamps.
    use_cross_asset_panel: bool = True
    panel_source_features: Tuple[str, ...] = (
        "log_return_1",
        "log_return_2",
        "log_return_3",
        "log_return_5",
        "signed_body_ratio",
        "return_zscore_20",
        "atr_ratio_30",
    )

    # Selection is global by timestamp, not independently per asset.
    train_fraction: float = 0.50
    early_stop_fraction: float = 0.10
    calibration_fraction: float = 0.15
    policy_fraction: float = 0.10
    test_fraction: float = 0.15
    # Covers the 64-bar sequence and the longest label across boundaries.
    purge_minutes: int = 150

    # Policy search. top_k=1 is the strict cross-sectional selector;
    # top_k=3 allows several simultaneous assets; 15 approximates no ranking.
    cross_sectional_top_k: Tuple[int, int, int] = (1, 3, 15)
    # Search may begin below theoretical payout breakeven because calibrated
    # classifiers can be deliberately conservative while their cross-sectional
    # rank is useful. Actual win rate and its bootstrap lower bound—not the
    # nominal probability—must still clear payout breakeven on policy and test.
    minimum_confidence_search: float = 0.50
    threshold_step: float = 0.01
    maximum_threshold: float = 0.80
    cooldown_seconds_per_asset: int = 300
    minimum_policy_trades: int = 250
    minimum_test_trades: int = 300
    minimum_policy_days: int = 10
    minimum_test_days: int = 14
    bootstrap_samples: int = 2_000

    # CatBoost.
    train_catboost: bool = True
    auto_install_catboost: bool = True
    catboost_iterations: int = 1_300
    catboost_depth: int = 7
    catboost_learning_rate: float = 0.03
    catboost_early_stopping_rounds: int = 120
    catboost_use_gpu: bool = False

    # Self-supervised temporal model. Kaggle normally includes PyTorch.
    train_temporal_encoder: bool = True
    sequence_length: int = 64
    temporal_hidden_size: int = 64
    temporal_embedding_size: int = 64
    temporal_batch_size: int = 512
    temporal_pretrain_epochs: int = 4
    temporal_frozen_head_epochs: int = 6
    temporal_finetune_epochs: int = 10
    temporal_learning_rate: float = 8e-4
    temporal_weight_decay: float = 1e-4
    max_temporal_train_sequences: int = 450_000
    max_temporal_eval_sequences: Optional[int] = None
    temporal_num_workers: int = 2

    random_seed: int = 42

    # Use only for a fast pipeline test, never for a real conclusion.
    smoke_rows_per_asset_timeframe: Optional[int] = None


CFG = Config()


# Every value is stationary or scale-relative. Raw open/high/low/close prices
# and any future execution prices are excluded.
BASE_FEATURES = [
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
    "plus_di_14",
    "minus_di_14",
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

# Populated deterministically by add_cross_asset_panel(). Keeping the names in
# one place guarantees every model and exported metadata use the same order.
ACTIVE_PANEL_FEATURES: List[str] = []


def set_reproducible(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)


def discover_data_path(configured: Optional[str]) -> Path:
    env_path = os.getenv("TRAINING_DATA_FILE") or os.getenv("DATA_PATH")
    if env_path:
        configured = env_path
    if configured:
        result = Path(configured)
        if not result.is_file():
            raise FileNotFoundError(f"Configured data file does not exist: {result}")
        return result
    candidates: List[Path] = []
    for root in (Path("/kaggle/input"), Path("data/ml"), Path("data/features"), Path(".")):
        if root.exists():
            candidates.extend(root.rglob("*.parquet"))
            candidates.extend(root.rglob("*.csv"))
    if not candidates:
        raise FileNotFoundError(
            "No dataset found. Set CFG.data_path or TRAINING_DATA_FILE."
        )

    def score(path: Path) -> Tuple[int, int]:
        name = path.name.lower()
        return int("candle" in name) + int("export" in name), path.stat().st_size

    selected = max(candidates, key=score)
    print(f"Auto-selected input: {selected}")
    return selected


def partial_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Cheap reproducibility fingerprint: size + first/last MiB."""
    digest = hashlib.sha256()
    size = path.stat().st_size
    digest.update(str(size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(chunk_size))
        if size > chunk_size:
            handle.seek(max(0, size - chunk_size))
            digest.update(handle.read(chunk_size))
    return digest.hexdigest()


def timestamp_to_utc(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if float(numeric.notna().mean()) >= 0.99:
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


def load_candles(path: Path, cfg: Config) -> pd.DataFrame:
    print(f"Reading {path} ({path.stat().st_size / 1024**2:.1f} MiB)...")
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, low_memory=False)
    aliases = {
        "asset": ("symbol", "instrument"),
        "timeframe": ("interval", "size", "period"),
        "timestamp": ("from", "at", "time", "datetime", "date"),
        "open": ("o",),
        "high": ("max", "h"),
        "low": ("min", "l"),
        "close": ("c",),
    }
    lowered = {str(column).lower(): column for column in frame.columns}
    rename: Dict[str, str] = {}
    for target, alternatives in aliases.items():
        for candidate in (target, *alternatives):
            if candidate in lowered:
                rename[lowered[candidate]] = target
                break
    frame = frame.rename(columns=rename)
    required = ["asset", "timeframe", "timestamp", "open", "high", "low", "close"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing candle columns {missing}; found {list(frame.columns)}")
    frame = frame[required].copy()
    frame["asset"] = (
        frame["asset"].astype(str).str.strip().str.upper().str.replace("_", "-", regex=False)
    )
    frame["timeframe"] = pd.to_numeric(frame["timeframe"], errors="coerce")
    frame["timestamp"] = timestamp_to_utc(frame["timestamp"])
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    needed = {cfg.entry_timeframe_seconds, *cfg.higher_timeframes_seconds}
    frame = frame.loc[frame["timeframe"].isin(needed)].dropna().copy()
    frame["timeframe"] = frame["timeframe"].astype(np.int32)
    positive = frame[["open", "high", "low", "close"]].gt(0).all(axis=1)
    valid_range = (
        frame["high"].ge(frame[["open", "close", "low"]].max(axis=1))
        & frame["low"].le(frame[["open", "close", "high"]].min(axis=1))
    )
    rejected = int((~(positive & valid_range)).sum())
    if rejected:
        print(f"Dropping {rejected:,} invalid OHLC rows.")
    frame = (
        frame.loc[positive & valid_range]
        .sort_values(["asset", "timeframe", "timestamp"])
        .drop_duplicates(["asset", "timeframe", "timestamp"], keep="last")
        .reset_index(drop=True)
    )
    if cfg.smoke_rows_per_asset_timeframe:
        frame = (
            frame.groupby(["asset", "timeframe"], group_keys=False)
            .head(cfg.smoke_rows_per_asset_timeframe)
            .reset_index(drop=True)
        )
    inventory = (
        frame.groupby("timeframe")["asset"]
        .agg(rows="size", assets="nunique")
        .reset_index()
    )
    print("\nCandle inventory:")
    print(inventory.to_string(index=False))
    available = set(frame["timeframe"].unique())
    if cfg.entry_timeframe_seconds not in available:
        raise ValueError(f"Missing {cfg.entry_timeframe_seconds}s entry candles.")
    missing_higher = set(cfg.higher_timeframes_seconds).difference(available)
    if missing_higher and cfg.require_native_higher_timeframes:
        raise ValueError(
            f"Missing native timeframes {sorted(missing_higher)}. Exact 5m OHLC "
            "cannot be reconstructed from 2m bars."
        )
    return frame


def wilder_average(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(
        alpha=1.0 / length, adjust=False, min_periods=length
    ).mean()


def calculate_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    average_gain = wilder_average(gain, length)
    average_loss = wilder_average(loss, length)
    rs = average_gain / average_loss.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + rs)
    result = result.where(average_loss.ne(0.0), 100.0)
    return result.where(average_gain.ne(0.0), 0.0)


def add_features(raw: pd.DataFrame, timeframe: int) -> pd.DataFrame:
    frame = raw.sort_values("timestamp").reset_index(drop=True).copy()
    open_price = frame["open"].replace(0.0, np.nan)
    close = frame["close"].replace(0.0, np.nan)
    previous_close = close.shift(1)
    log_close = np.log(close)
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
    frame["ema_20_slope_3"] = np.log(ema_20 / ema_20.shift(3))
    frame["ema_50_slope_3"] = np.log(ema_50 / ema_50.shift(3))

    frame["rsi_14"] = calculate_rsi(close) / 100.0
    low_14 = frame["low"].rolling(14, min_periods=14).min()
    high_14 = frame["high"].rolling(14, min_periods=14).max()
    stochastic_k = (
        100.0 * (close - low_14) / (high_14 - low_14).replace(0.0, np.nan)
    )
    frame["stoch_k"] = stochastic_k / 100.0
    frame["stoch_d"] = stochastic_k.rolling(3, min_periods=3).mean() / 100.0

    mean_20 = close.rolling(20, min_periods=20).mean()
    std_20 = close.rolling(20, min_periods=20).std(ddof=0)
    upper = mean_20 + 2.0 * std_20
    lower = mean_20 - 2.0 * std_20
    frame["bb_percent_b"] = (
        (close - lower) / (upper - lower).replace(0.0, np.nan)
    )
    frame["bb_width"] = (upper - lower) / mean_20

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
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = wilder_average(true_range, 14)
    plus_di = 100.0 * wilder_average(plus_dm, 14) / atr.replace(0.0, np.nan)
    minus_di = 100.0 * wilder_average(minus_dm, 14) / atr.replace(0.0, np.nan)
    dx = (
        100.0
        * (plus_di - minus_di).abs()
        / (plus_di + minus_di).replace(0.0, np.nan)
    )
    frame["adx_14"] = wilder_average(dx, 14) / 100.0
    frame["plus_di_14"] = plus_di / 100.0
    frame["minus_di_14"] = minus_di / 100.0
    frame["atr_pct"] = atr / close
    frame["atr_ratio_30"] = frame["atr_pct"] / frame["atr_pct"].rolling(
        30, min_periods=30
    ).median()
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
    path = close.diff().abs().rolling(10, min_periods=10).sum()
    frame["trend_efficiency_10"] = (
        close.diff(10).abs() / path.replace(0.0, np.nan)
    )
    range_10 = frame["range_pct"].rolling(10, min_periods=10).mean()
    range_50 = frame["range_pct"].rolling(50, min_periods=50).mean()
    frame["range_compression_10_50"] = range_10 / range_50.replace(0.0, np.nan)

    minute = frame["timestamp"].dt.hour * 60 + frame["timestamp"].dt.minute
    hour_angle = 2.0 * np.pi * minute / 1440.0
    day_angle = 2.0 * np.pi * frame["timestamp"].dt.dayofweek / 7.0
    frame["hour_sin"] = np.sin(hour_angle)
    frame["hour_cos"] = np.cos(hour_angle)
    frame["day_sin"] = np.sin(day_angle)
    frame["day_cos"] = np.cos(day_angle)
    frame["available_time"] = frame["timestamp"] + pd.to_timedelta(
        timeframe, unit="s"
    )
    return frame.replace([np.inf, -np.inf], np.nan)


def prefixed_higher(frame: pd.DataFrame, timeframe: int) -> pd.DataFrame:
    available = ["available_time"] + [
        column for column in BASE_FEATURES if column in frame
    ]
    result = frame[available].copy()
    return result.rename(
        columns={
            column: f"tf{timeframe}_{column}"
            for column in available
            if column != "available_time"
        }
    )


def safe_asset_name(asset: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in asset)


def currency_pair(asset: str) -> Tuple[str, str]:
    compact = str(asset).upper().split("-", 1)[0].replace("/", "")
    if len(compact) < 6:
        return "UNK", "UNK"
    return compact[:3], compact[3:6]


def add_cross_asset_panel(frame: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """
    Add synchronized panel features without using any future candle.

    Each row is observed after its own 2m candle has closed. A panel value is
    joined only when another asset has a state with the exact same
    decision_time. Currency factors and breadth statistics exclude the target
    pair so a target's return is not disguised as an external predictor.
    """
    global ACTIVE_PANEL_FEATURES
    ACTIVE_PANEL_FEATURES = []
    if not cfg.use_cross_asset_panel:
        return frame

    result = frame.copy()
    assets = sorted(result["asset"].unique().tolist())
    print(
        f"\nAdding synchronized cross-asset panel features for "
        f"{len(assets)} assets..."
    )
    started = time.time()
    panel_columns: List[str] = []
    wide_pieces: List[pd.DataFrame] = []

    for source in cfg.panel_source_features:
        if source not in result:
            raise ValueError(f"Panel source feature is missing: {source}")
        wide = result.pivot(
            index="decision_time", columns="asset", values=source
        ).sort_index()
        wide = wide.reindex(columns=assets)
        renamed = {
            asset: f"panel_{source}__{safe_asset_name(asset)}"
            for asset in assets
        }
        wide = wide.rename(columns=renamed).astype(np.float32)
        panel_columns.extend(wide.columns.tolist())
        wide_pieces.append(wide)
    synchronized_panel = pd.concat(wide_pieces, axis=1)
    result = result.merge(
        synchronized_panel,
        left_on="decision_time",
        right_index=True,
        how="left",
        validate="many_to_one",
    )

    # Leave-one-target-out breadth and dispersion from synchronized 2m returns.
    return_wide = result.pivot(
        index="decision_time", columns="asset", values="log_return_1"
    ).reindex(columns=assets)
    available = return_wide.notna().sum(axis=1).astype(float)
    total = return_wide.sum(axis=1, skipna=True)
    total_square = return_wide.pow(2).sum(axis=1, skipna=True)
    positive = return_wide.gt(0).sum(axis=1).astype(float)
    panel_stats = pd.DataFrame(
        {
            "_panel_count": available,
            "_panel_sum": total,
            "_panel_sum_square": total_square,
            "_panel_positive": positive,
        },
        index=return_wide.index,
    )
    result = result.merge(
        panel_stats,
        left_on="decision_time",
        right_index=True,
        how="left",
        validate="many_to_one",
    )
    own = result["log_return_1"]
    other_count = (result["_panel_count"] - own.notna().astype(float)).clip(lower=0)
    other_sum = result["_panel_sum"] - own.fillna(0.0)
    other_square = result["_panel_sum_square"] - own.fillna(0.0).pow(2)
    other_positive = result["_panel_positive"] - own.gt(0).astype(float)
    denominator = other_count.replace(0.0, np.nan)
    other_mean = other_sum / denominator
    other_variance = (
        other_square / denominator - other_mean.pow(2)
    ).clip(lower=0.0)
    result["panel_other_asset_count"] = other_count
    result["panel_other_mean_return_1"] = other_mean
    result["panel_other_std_return_1"] = np.sqrt(other_variance)
    result["panel_other_up_fraction_1"] = other_positive / denominator
    result["panel_relative_return_1"] = own - other_mean
    breadth_columns = [
        "panel_other_asset_count",
        "panel_other_mean_return_1",
        "panel_other_std_return_1",
        "panel_other_up_fraction_1",
        "panel_relative_return_1",
    ]
    panel_columns.extend(breadth_columns)

    # Leave-one-pair-out currency factors. If the pair is EURUSD, its EUR
    # factor omits +EURUSD and its USD factor omits -EURUSD.
    pair_map = {asset: currency_pair(asset) for asset in assets}
    currencies = sorted(
        {
            currency
            for base_quote in pair_map.values()
            for currency in base_quote
            if currency != "UNK"
        }
    )
    exposures = pd.DataFrame(0.0, index=assets, columns=currencies)
    for asset, (base, quote) in pair_map.items():
        if base in exposures:
            exposures.loc[asset, base] = 1.0
        if quote in exposures:
            exposures.loc[asset, quote] = -1.0
    result["_base_currency"] = result["asset"].map(
        {asset: pair_map[asset][0] for asset in assets}
    )
    result["_quote_currency"] = result["asset"].map(
        {asset: pair_map[asset][1] for asset in assets}
    )

    for source in ("log_return_1", "log_return_3"):
        source_wide = result.pivot(
            index="decision_time", columns="asset", values=source
        ).reindex(columns=assets)
        # Missing pairs contribute neither sum nor effective count.
        signed_sum = source_wide.fillna(0.0).to_numpy() @ exposures.to_numpy()
        present = source_wide.notna().astype(float).to_numpy()
        effective_count = present @ exposures.ne(0).astype(float).to_numpy()
        signed_sum = pd.DataFrame(
            signed_sum, index=source_wide.index, columns=currencies
        ).rename_axis(columns="_currency")
        effective_count = pd.DataFrame(
            effective_count, index=source_wide.index, columns=currencies
        ).rename_axis(columns="_currency")
        sum_long = signed_sum.stack().rename("_factor_sum").reset_index()
        count_long = effective_count.stack().rename("_factor_count").reset_index()
        factor_long = sum_long.merge(
            count_long, on=["decision_time", "_currency"], validate="one_to_one"
        )

        own_source = result[source].fillna(0.0)
        for role, exposure_sign in (("base", 1.0), ("quote", -1.0)):
            currency_column = f"_{role}_currency"
            joined = result[["decision_time", currency_column]].merge(
                factor_long,
                left_on=["decision_time", currency_column],
                right_on=["decision_time", "_currency"],
                how="left",
                validate="many_to_one",
            )
            leave_sum = joined["_factor_sum"].to_numpy() - (
                exposure_sign * own_source.to_numpy()
            )
            leave_count = joined["_factor_count"].to_numpy() - result[
                source
            ].notna().astype(float).to_numpy()
            column = f"panel_{role}_currency_factor_{source}"
            result[column] = leave_sum / np.where(
                leave_count > 0, leave_count, np.nan
            )
            panel_columns.append(column)
        difference = f"panel_currency_factor_difference_{source}"
        result[difference] = (
            result[f"panel_base_currency_factor_{source}"]
            - result[f"panel_quote_currency_factor_{source}"]
        )
        panel_columns.append(difference)

    result = result.drop(
        columns=[
            "_panel_count",
            "_panel_sum",
            "_panel_sum_square",
            "_panel_positive",
            "_base_currency",
            "_quote_currency",
        ],
        errors="ignore",
    )
    ACTIVE_PANEL_FEATURES = list(dict.fromkeys(panel_columns))
    for column in ACTIVE_PANEL_FEATURES:
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(
            np.float32
        )
    print(
        f"Added {len(ACTIVE_PANEL_FEATURES)} causal panel features in "
        f"{time.time() - started:.1f}s."
    )
    return result


def feature_columns(cfg: Config) -> Tuple[List[str], List[str]]:
    numeric = list(BASE_FEATURES)
    for timeframe in cfg.higher_timeframes_seconds:
        numeric.extend(f"tf{timeframe}_{column}" for column in BASE_FEATURES)
    numeric.extend(ACTIVE_PANEL_FEATURES)
    categorical = ["asset", "volatility_regime"]
    return numeric, categorical


def align_asset(asset_raw: pd.DataFrame, asset: str, cfg: Config) -> pd.DataFrame:
    entry_raw = asset_raw.loc[
        asset_raw["timeframe"].eq(cfg.entry_timeframe_seconds)
    ]
    if entry_raw.empty:
        return pd.DataFrame()
    entry = add_features(entry_raw, cfg.entry_timeframe_seconds)
    entry["decision_time_dt"] = entry["available_time"]
    for timeframe in cfg.higher_timeframes_seconds:
        higher_raw = asset_raw.loc[asset_raw["timeframe"].eq(timeframe)]
        if higher_raw.empty:
            for column in BASE_FEATURES:
                entry[f"tf{timeframe}_{column}"] = np.nan
            continue
        higher = prefixed_higher(
            add_features(higher_raw, timeframe), timeframe
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
    entry["decision_time"] = (
        entry["decision_time_dt"].astype("int64") // 1_000_000_000
    ).astype(np.int64)
    ratio = entry["atr_ratio_30"]
    entry["volatility_regime"] = pd.Series(
        np.select(
            [ratio.lt(0.75), ratio.lt(1.25), ratio.lt(1.75)],
            ["low", "normal", "high"],
            default="extreme",
        ),
        index=entry.index,
    ).where(ratio.notna(), "unknown")
    return entry.sort_values("timestamp").reset_index(drop=True)


def add_labels_and_sequence_validity(frame: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    result = frame.copy()
    entry_step = 1
    expected_next = result["timestamp"] + pd.to_timedelta(
        cfg.entry_timeframe_seconds, unit="s"
    )
    next_start = result["timestamp"].shift(-entry_step)
    result["entry_path_valid"] = next_start.eq(expected_next)
    result["_entry_proxy"] = result["open"].shift(-entry_step)

    for horizon in cfg.prediction_horizons_minutes:
        seconds = horizon * 60
        if seconds % cfg.entry_timeframe_seconds:
            raise ValueError(
                f"Horizon {horizon}m is not divisible by "
                f"{cfg.entry_timeframe_seconds}s candles."
            )
        steps = seconds // cfg.entry_timeframe_seconds
        settlement_start = result["timestamp"].shift(-steps)
        expected_settlement = result["timestamp"] + pd.to_timedelta(
            seconds, unit="s"
        )
        settlement = result["close"].shift(-steps)
        valid = result["entry_path_valid"] & settlement_start.eq(expected_settlement)
        tied = settlement.eq(result["_entry_proxy"])
        label = settlement.gt(result["_entry_proxy"]).astype(np.float32)
        label = label.where(valid & ~tied, np.nan)
        result[f"label_up_{horizon}m"] = label
        result[f"label_valid_{horizon}m"] = label.notna()

    sequence_span = (cfg.sequence_length - 1) * cfg.entry_timeframe_seconds
    sequence_start = result["timestamp"].shift(cfg.sequence_length - 1)
    result["sequence_valid"] = (
        result["timestamp"].sub(sequence_start).dt.total_seconds().eq(sequence_span)
    )
    result["asset_position"] = np.arange(len(result), dtype=np.int64)
    return result


def build_state_table(candles: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    global ACTIVE_PANEL_FEATURES
    # A notebook may call this function more than once during diagnostics.
    # Never let feature names from a prior build leak into the pre-panel schema.
    ACTIVE_PANEL_FEATURES = []
    pieces: List[pd.DataFrame] = []
    assets = sorted(candles["asset"].unique())
    print(f"\nBuilding strategy-independent state table for {len(assets)} assets...")
    started = time.time()
    for index, asset in enumerate(assets, 1):
        aligned = align_asset(candles.loc[candles["asset"].eq(asset)], asset, cfg)
        labeled = add_labels_and_sequence_validity(aligned, cfg)
        pieces.append(labeled)
        primary = f"label_up_{cfg.primary_horizon_minutes}m"
        usable = int(labeled[primary].notna().sum())
        print(f"[{index:02d}/{len(assets):02d}] {asset}: {usable:,} usable states")
    combined = pd.concat(pieces, ignore_index=True)
    numeric, categorical = feature_columns(cfg)
    keep = [
        "asset",
        "timestamp",
        "decision_time",
        "asset_position",
        "sequence_valid",
        *numeric,
        *categorical[1:],
    ]
    for horizon in cfg.prediction_horizons_minutes:
        keep.extend([f"label_up_{horizon}m", f"label_valid_{horizon}m"])
    combined = combined[keep].sort_values(["decision_time", "asset"]).reset_index(
        drop=True
    )
    combined["row_id"] = np.arange(len(combined), dtype=np.int64)
    primary = f"label_up_{cfg.primary_horizon_minutes}m"
    usable_primary = int(combined[primary].notna().sum())
    combined = add_cross_asset_panel(combined, cfg)
    print(
        f"Built {len(combined):,} states ({usable_primary:,} with primary labels) "
        f"in {time.time() - started:.1f}s; primary up "
        f"rate={combined[primary].mean():.3%}."
    )
    return combined


def temporal_partitions(
    frame: pd.DataFrame, cfg: Config
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, int]]:
    fractions = np.asarray(
        [
            cfg.train_fraction,
            cfg.early_stop_fraction,
            cfg.calibration_fraction,
            cfg.policy_fraction,
            cfg.test_fraction,
        ]
    )
    if not np.isclose(fractions.sum(), 1.0):
        raise ValueError("Temporal fractions must sum to 1.")
    label = f"label_up_{cfg.primary_horizon_minutes}m"
    all_label_columns = [
        f"label_up_{horizon}m" for horizon in cfg.prediction_horizons_minutes
    ]
    any_label = frame[all_label_columns].notna().any(axis=1)
    timeline = np.sort(
        frame.loc[any_label, "decision_time"].unique()
    )
    cumulative = np.cumsum(fractions)[:-1]
    cutoffs = [
        int(timeline[max(0, min(len(timeline) - 1, int(len(timeline) * q) - 1))])
        for q in cumulative
    ]
    purge = cfg.purge_minutes * 60
    names = ["train", "early_stop", "calibration", "policy", "test"]
    lowers = [-np.inf] + [cutoff + purge for cutoff in cutoffs]
    uppers = [cutoff - purge for cutoff in cutoffs] + [np.inf]
    parts: Dict[str, pd.DataFrame] = {}
    print("\nPurged global temporal partitions:")
    for name, lower, upper in zip(names, lowers, uppers):
        selected = (
            frame["decision_time"].gt(lower)
            & frame["decision_time"].le(upper)
            & any_label
        )
        part = frame.loc[selected].copy()
        if part.empty:
            raise ValueError(
                f"Partition {name} is empty. For a smoke test only, reduce purge_minutes."
            )
        parts[name] = part
        start = pd.to_datetime(part["decision_time"].min(), unit="s", utc=True)
        end = pd.to_datetime(part["decision_time"].max(), unit="s", utc=True)
        print(
            f"{name:12s} rows={len(part):9,d} up={part[label].mean():.3%} "
            f"{start} -> {end}"
        )
    return parts, {
        "train_end": cutoffs[0],
        "early_stop_end": cutoffs[1],
        "calibration_end": cutoffs[2],
        "policy_end": cutoffs[3],
        "purge_seconds": purge,
    }


def part_for_horizon(
    part: pd.DataFrame, horizon_minutes: int
) -> pd.DataFrame:
    label = f"label_up_{horizon_minutes}m"
    return part.loc[part[label].notna()].copy()


def expected_calibration_error(
    labels: np.ndarray, probability: np.ndarray, bins: int = 10
) -> float:
    assignments = np.digitize(
        probability, np.linspace(0, 1, bins + 1)[1:-1], right=True
    )
    result = 0.0
    for index in range(bins):
        selected = assignments == index
        if selected.any():
            result += (
                selected.mean()
                * abs(labels[selected].mean() - probability[selected].mean())
            )
    return float(result)


def probability_metrics(labels: np.ndarray, probability: np.ndarray) -> Dict[str, float]:
    probability = np.asarray(probability, dtype=float).clip(1e-7, 1 - 1e-7)
    labels = np.asarray(labels, dtype=int)
    return {
        "roc_auc": float(roc_auc_score(labels, probability)),
        "accuracy": float(accuracy_score(labels, probability >= 0.5)),
        "log_loss": float(log_loss(labels, probability)),
        "brier_score": float(brier_score_loss(labels, probability)),
        "ece_10_bins": expected_calibration_error(labels, probability),
        "up_rate": float(labels.mean()),
    }


def fit_platt(raw_score: np.ndarray, label: np.ndarray) -> LogisticRegression:
    calibrator = LogisticRegression(solver="lbfgs", random_state=CFG.random_seed)
    calibrator.fit(np.asarray(raw_score).reshape(-1, 1), np.asarray(label, dtype=int))
    return calibrator


def confidence_and_wins(
    probability_up: np.ndarray, labels_up: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    probability_up = np.asarray(probability_up, dtype=float)
    predicted_up = probability_up >= 0.5
    confidence = np.where(predicted_up, probability_up, 1.0 - probability_up)
    wins = predicted_up == np.asarray(labels_up, dtype=bool)
    return confidence, wins.astype(np.int8), predicted_up.astype(np.int8)


def select_trades(
    confidence: np.ndarray,
    assets: np.ndarray,
    times: np.ndarray,
    threshold: float,
    top_k: int,
    cooldown: int,
) -> np.ndarray:
    candidates = np.flatnonzero(confidence >= threshold)
    if candidates.size == 0:
        return candidates
    table = pd.DataFrame(
        {
            "index": candidates,
            "asset": assets[candidates],
            "time": times[candidates],
            "confidence": confidence[candidates],
        }
    )
    table = (
        table.sort_values(["time", "confidence"], ascending=[True, False])
        .groupby("time", group_keys=False)
        .head(top_k)
        .sort_values(["time", "confidence"], ascending=[True, False])
    )
    accepted: List[int] = []
    last_by_asset: Dict[str, int] = {}
    for row in table.itertuples(index=False):
        previous = last_by_asset.get(row.asset)
        if previous is not None and row.time - previous < cooldown:
            continue
        accepted.append(int(row.index))
        last_by_asset[row.asset] = int(row.time)
    return np.asarray(accepted, dtype=np.int64)


def expectancy(win_rate: float, payout: float) -> float:
    return win_rate * payout - (1.0 - win_rate)


def bootstrap_lower(
    wins: np.ndarray, times: np.ndarray, samples: int, seed: int
) -> float:
    days = times // 86_400
    unique = np.unique(days)
    if len(unique) < 2:
        return float("nan")
    daily_wins = np.asarray([wins[days == day].sum() for day in unique])
    daily_count = np.asarray([(days == day).sum() for day in unique])
    rng = np.random.default_rng(seed)
    values = np.empty(samples)
    for index in range(samples):
        chosen = rng.integers(0, len(unique), len(unique))
        values[index] = daily_wins[chosen].sum() / daily_count[chosen].sum()
    return float(np.quantile(values, 0.025))


def policy_metrics(
    probability_up: np.ndarray,
    labels_up: np.ndarray,
    assets: np.ndarray,
    times: np.ndarray,
    threshold: float,
    top_k: int,
    cfg: Config,
    seed: int,
) -> Dict[str, object]:
    confidence, wins, _ = confidence_and_wins(probability_up, labels_up)
    selected = select_trades(
        confidence,
        assets,
        times,
        threshold,
        top_k,
        cfg.cooldown_seconds_per_asset,
    )
    if not selected.size:
        return {
            "threshold": threshold,
            "top_k": top_k,
            "trades": 0,
            "days": 0,
            "coverage": 0.0,
            "win_rate": None,
            "lower_95_win_rate": None,
            "expectancy_per_unit": None,
            "lower_95_expectancy_per_unit": None,
        }
    selected_wins = wins[selected].astype(float)
    selected_times = times[selected]
    win_rate = float(selected_wins.mean())
    lower = bootstrap_lower(
        selected_wins, selected_times, cfg.bootstrap_samples, seed
    )
    return {
        "threshold": float(threshold),
        "top_k": int(top_k),
        "trades": int(len(selected)),
        "days": int(np.unique(selected_times // 86_400).size),
        "coverage": float(len(selected) / len(labels_up)),
        "win_rate": win_rate,
        "lower_95_win_rate": lower if math.isfinite(lower) else None,
        "expectancy_per_unit": expectancy(win_rate, cfg.binary_payout),
        "lower_95_expectancy_per_unit": (
            expectancy(lower, cfg.binary_payout) if math.isfinite(lower) else None
        ),
    }


def search_model_policy(
    model_name: str,
    horizon_minutes: int,
    probability: np.ndarray,
    part: pd.DataFrame,
    cfg: Config,
) -> Tuple[Dict[str, object], pd.DataFrame, bool]:
    label_column = f"label_up_{horizon_minutes}m"
    labels = part[label_column].to_numpy(dtype=int)
    assets = part["asset"].to_numpy(dtype=str)
    times = part["decision_time"].to_numpy(dtype=np.int64)
    start = math.ceil(
        cfg.minimum_confidence_search / cfg.threshold_step
    ) * cfg.threshold_step
    rows: List[Dict[str, object]] = []
    seed = cfg.random_seed
    for top_k in cfg.cross_sectional_top_k:
        for threshold in np.arange(
            start,
            cfg.maximum_threshold + cfg.threshold_step / 2,
            cfg.threshold_step,
        ):
            row = policy_metrics(
                probability,
                labels,
                assets,
                times,
                float(threshold),
                int(top_k),
                cfg,
                seed,
            )
            row["model"] = model_name
            row["horizon_minutes"] = horizon_minutes
            rows.append(row)
            seed += 1
    table = pd.DataFrame(rows)
    eligible = table.loc[
        table["trades"].ge(cfg.minimum_policy_trades)
        & table["days"].ge(cfg.minimum_policy_days)
        & table["lower_95_expectancy_per_unit"].notna()
        & table["lower_95_expectancy_per_unit"].gt(0.0)
    ]
    passed = not eligible.empty
    selection_pool = eligible if passed else table.loc[
        table["lower_95_expectancy_per_unit"].notna()
    ]
    if selection_pool.empty:
        best = {
            "model": model_name,
            "horizon_minutes": horizon_minutes,
            "threshold": start,
            "top_k": cfg.cross_sectional_top_k[0],
            "trades": 0,
            "days": 0,
            "lower_95_expectancy_per_unit": None,
        }
    else:
        best = selection_pool.sort_values(
            ["lower_95_expectancy_per_unit", "trades"],
            ascending=[False, False],
        ).iloc[0].to_dict()
    best["policy_passed"] = passed
    return best, table, passed


def numeric_and_categorical(cfg: Config) -> Tuple[List[str], List[str]]:
    return feature_columns(cfg)


def linear_pipeline(numeric: Sequence[str], categorical: Sequence[str], seed: int):
    preprocessor = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                list(numeric),
            ),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=True),
                list(categorical),
            ),
        ]
    )
    classifier = SGDClassifier(
        loss="log_loss",
        penalty="elasticnet",
        alpha=2e-5,
        l1_ratio=0.05,
        max_iter=150,
        tol=1e-4,
        random_state=seed,
        average=True,
    )
    return Pipeline([("features", preprocessor), ("model", classifier)])


class ModelPrediction:
    def __init__(
        self,
        name: str,
        horizon_minutes: int,
        calibration: np.ndarray,
        policy: np.ndarray,
        predict_test,
        save,
        details: Optional[Dict[str, object]] = None,
        sequence_only: bool = False,
    ):
        self.name = name
        self.horizon_minutes = int(horizon_minutes)
        self.calibration = calibration
        self.policy = policy
        self.predict_test = predict_test
        self.save = save
        self.details = details or {}
        self.sequence_only = bool(sequence_only)


def evaluation_part(
    model: ModelPrediction,
    parts: Dict[str, pd.DataFrame],
    name: str,
) -> pd.DataFrame:
    part = part_for_horizon(parts[name], model.horizon_minutes)
    if model.sequence_only:
        part = part.loc[part["sequence_valid"]].copy()
    return part


def train_null_model(
    parts: Dict[str, pd.DataFrame], cfg: Config, horizon_minutes: int
) -> ModelPrediction:
    label = f"label_up_{horizon_minutes}m"
    horizon_parts = {
        name: part_for_horizon(part, horizon_minutes)
        for name, part in parts.items()
    }
    rate = float(horizon_parts["train"][label].mean())
    return ModelPrediction(
        f"null_base_rate_{horizon_minutes}m",
        horizon_minutes,
        np.full(len(horizon_parts["calibration"]), rate),
        np.full(len(horizon_parts["policy"]), rate),
        lambda: np.full(len(horizon_parts["test"]), rate),
        lambda output: (output / f"null_model_{horizon_minutes}m.json").write_text(
            json.dumps(
                {"train_up_rate": rate, "horizon_minutes": horizon_minutes},
                indent=2,
            ),
            encoding="utf-8",
        ),
        {"train_up_rate": rate},
    )


def train_linear_model(
    parts: Dict[str, pd.DataFrame], cfg: Config, horizon_minutes: int
) -> ModelPrediction:
    numeric, categorical = numeric_and_categorical(cfg)
    label = f"label_up_{horizon_minutes}m"
    horizon_parts = {
        name: part_for_horizon(part, horizon_minutes)
        for name, part in parts.items()
    }
    columns = numeric + categorical
    print(f"\nTraining regularized linear baseline ({horizon_minutes}m)...")
    model = linear_pipeline(numeric, categorical, cfg.random_seed)
    model.fit(
        horizon_parts["train"][columns],
        horizon_parts["train"][label].astype(int),
    )
    calibration_raw = model.decision_function(
        horizon_parts["calibration"][columns]
    )
    calibrator = fit_platt(
        calibration_raw,
        horizon_parts["calibration"][label].to_numpy(dtype=int),
    )

    def predict(part: pd.DataFrame) -> np.ndarray:
        raw = model.decision_function(part[columns])
        return calibrator.predict_proba(np.asarray(raw).reshape(-1, 1))[:, 1]

    return ModelPrediction(
        f"linear_sgd_{horizon_minutes}m",
        horizon_minutes,
        predict(horizon_parts["calibration"]),
        predict(horizon_parts["policy"]),
        lambda: predict(horizon_parts["test"]),
        lambda output: joblib.dump(
            {
                "model": model,
                "calibrator": calibrator,
                "features": columns,
                "horizon_minutes": horizon_minutes,
            },
            output / f"linear_sgd_{horizon_minutes}m.joblib",
        ),
    )


def ensure_catboost(cfg: Config):
    if importlib.util.find_spec("catboost") is None:
        if not cfg.auto_install_catboost:
            raise RuntimeError("CatBoost missing; run !pip install -q catboost")
        print("Installing CatBoost for this Kaggle session...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "catboost"]
        )
    from catboost import CatBoostClassifier, Pool

    return CatBoostClassifier, Pool


def train_catboost_model(
    parts: Dict[str, pd.DataFrame], cfg: Config, horizon_minutes: int
) -> ModelPrediction:
    CatBoostClassifier, Pool = ensure_catboost(cfg)
    numeric, categorical = numeric_and_categorical(cfg)
    columns = numeric + categorical
    cat_indices = [columns.index(column) for column in categorical]
    label = f"label_up_{horizon_minutes}m"
    horizon_parts = {
        name: part_for_horizon(part, horizon_minutes)
        for name, part in parts.items()
    }

    def x(part: pd.DataFrame) -> pd.DataFrame:
        result = part[columns].copy()
        for column in numeric:
            result[column] = pd.to_numeric(
                result[column], errors="coerce"
            ).astype(np.float32)
        for column in categorical:
            result[column] = result[column].fillna("unknown").astype(str)
        return result.replace([np.inf, -np.inf], np.nan)

    pools = {
        name: Pool(
            x(horizon_parts[name]),
            label=horizon_parts[name][label].astype(int),
            cat_features=cat_indices,
        )
        for name in ("train", "early_stop", "calibration", "policy", "test")
    }
    parameters = dict(
        iterations=cfg.catboost_iterations,
        depth=cfg.catboost_depth,
        learning_rate=cfg.catboost_learning_rate,
        loss_function="Logloss",
        eval_metric="AUC",
        random_seed=cfg.random_seed,
        l2_leaf_reg=7.0,
        random_strength=0.5,
        verbose=50,
        allow_writing_files=False,
        thread_count=-1,
    )
    if cfg.catboost_use_gpu:
        parameters.update(task_type="GPU", devices="0")
    model = CatBoostClassifier(**parameters)
    print(
        f"\nTraining CatBoost cross-asset model ({horizon_minutes}m)..."
    )
    model.fit(
        pools["train"],
        eval_set=pools["early_stop"],
        early_stopping_rounds=cfg.catboost_early_stopping_rounds,
        use_best_model=True,
    )
    calibration_raw = np.asarray(
        model.predict(pools["calibration"], prediction_type="RawFormulaVal")
    )
    calibrator = fit_platt(
        calibration_raw,
        horizon_parts["calibration"][label].to_numpy(dtype=int),
    )

    def predict_pool(name: str) -> np.ndarray:
        raw = np.asarray(
            model.predict(pools[name], prediction_type="RawFormulaVal")
        )
        return calibrator.predict_proba(raw.reshape(-1, 1))[:, 1]

    def save(output: Path) -> None:
        model.save_model(
            output / f"catboost_direction_{horizon_minutes}m.cbm"
        )
        joblib.dump(
            calibrator,
            output / f"catboost_calibrator_{horizon_minutes}m.joblib",
        )
        pd.DataFrame(
            {
                "feature": columns,
                "importance": model.get_feature_importance(pools["train"]),
            }
        ).sort_values("importance", ascending=False).to_csv(
            output / f"catboost_feature_importance_{horizon_minutes}m.csv",
            index=False,
        )

    return ModelPrediction(
        f"catboost_{horizon_minutes}m",
        horizon_minutes,
        predict_pool("calibration"),
        predict_pool("policy"),
        lambda: predict_pool("test"),
        save,
        {"best_iteration": int(model.get_best_iteration())},
    )


# =============================================================================
# OPTIONAL TEMPORAL-CONTRASTIVE TCN
# =============================================================================


def train_temporal_models(
    full_frame: pd.DataFrame,
    parts: Dict[str, pd.DataFrame],
    cfg: Config,
) -> List[ModelPrediction]:
    """
    Train a TS2Vec-inspired temporal encoder.

    This is intentionally described as "temporal contrastive", not as an exact
    reproduction of the official TS2Vec repository. It uses two masked/noisy
    views and an NT-Xent objective, then evaluates both a frozen head and a
    fine-tuned multi-horizon head.
    """
    if importlib.util.find_spec("torch") is None:
        raise RuntimeError(
            "PyTorch is unavailable. Kaggle GPU notebooks normally include it."
        )
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import DataLoader, Dataset

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\nTemporal model device: {device}")
    numeric, _ = numeric_and_categorical(cfg)
    horizons = list(cfg.prediction_horizons_minutes)
    label_columns = [f"label_up_{horizon}m" for horizon in horizons]

    train_values = full_frame.loc[
        full_frame["row_id"].isin(parts["train"]["row_id"]), numeric
    ].replace([np.inf, -np.inf], np.nan)
    medians = train_values.median().fillna(0.0)
    means = train_values.fillna(medians).mean()
    stds = train_values.fillna(medians).std(ddof=0).replace(0.0, 1.0).fillna(1.0)

    assets = sorted(full_frame["asset"].unique())
    asset_to_id = {asset: index for index, asset in enumerate(assets)}
    arrays: Dict[str, np.ndarray] = {}
    for asset in assets:
        asset_part = full_frame.loc[full_frame["asset"].eq(asset)].sort_values(
            "asset_position"
        )
        values = asset_part[numeric].replace([np.inf, -np.inf], np.nan)
        values = ((values.fillna(medians) - means) / stds).clip(-10, 10)
        arrays[asset] = values.to_numpy(dtype=np.float32)

    class SequenceRows(Dataset):
        def __init__(self, rows: pd.DataFrame, limit: Optional[int], seed: int):
            usable = rows.loc[rows["sequence_valid"]].copy()
            if limit and len(usable) > limit:
                rng = np.random.default_rng(seed)
                chosen = np.sort(rng.choice(len(usable), limit, replace=False))
                usable = usable.iloc[chosen]
            self.assets = usable["asset"].to_numpy(dtype=str)
            self.positions = usable["asset_position"].to_numpy(dtype=np.int64)
            self.asset_ids = np.asarray(
                [asset_to_id[asset] for asset in self.assets], dtype=np.int64
            )
            labels = usable[label_columns].to_numpy(dtype=np.float32)
            self.masks = np.isfinite(labels).astype(np.float32)
            self.labels = np.nan_to_num(labels, nan=0.0).astype(np.float32)
            self.row_ids = usable["row_id"].to_numpy(dtype=np.int64)

        def __len__(self):
            return len(self.positions)

        def __getitem__(self, index):
            asset = self.assets[index]
            end = self.positions[index] + 1
            start = end - cfg.sequence_length
            sequence = arrays[asset][start:end]
            return (
                torch.from_numpy(sequence),
                torch.tensor(self.asset_ids[index], dtype=torch.long),
                torch.from_numpy(self.labels[index]),
                torch.from_numpy(self.masks[index]),
                torch.tensor(self.row_ids[index], dtype=torch.long),
            )

    datasets = {
        "train": SequenceRows(
            parts["train"], cfg.max_temporal_train_sequences, cfg.random_seed
        ),
        "early_stop": SequenceRows(
            parts["early_stop"], cfg.max_temporal_eval_sequences, cfg.random_seed + 1
        ),
        "calibration": SequenceRows(
            parts["calibration"], cfg.max_temporal_eval_sequences, cfg.random_seed + 2
        ),
        "policy": SequenceRows(
            parts["policy"], cfg.max_temporal_eval_sequences, cfg.random_seed + 3
        ),
        "test": SequenceRows(
            parts["test"], cfg.max_temporal_eval_sequences, cfg.random_seed + 4
        ),
    }
    for name, dataset in datasets.items():
        print(f"Temporal {name:12s}: {len(dataset):,} sequences")
        if not len(dataset):
            raise ValueError(f"No valid temporal sequences in {name}")

    def loader(name: str, shuffle: bool = False) -> DataLoader:
        return DataLoader(
            datasets[name],
            batch_size=cfg.temporal_batch_size,
            shuffle=shuffle,
            num_workers=cfg.temporal_num_workers,
            pin_memory=device.type == "cuda",
            drop_last=shuffle,
        )

    class ResidualBlock(nn.Module):
        def __init__(self, channels: int, dilation: int):
            super().__init__()
            padding = dilation
            self.conv1 = nn.Conv1d(
                channels, channels, 3, padding=padding, dilation=dilation
            )
            self.conv2 = nn.Conv1d(
                channels, channels, 3, padding=padding, dilation=dilation
            )
            self.norm1 = nn.BatchNorm1d(channels)
            self.norm2 = nn.BatchNorm1d(channels)

        def forward(self, value):
            residual = value
            value = F.gelu(self.norm1(self.conv1(value)))
            value = self.norm2(self.conv2(value))
            return F.gelu(value + residual)

    class TemporalEncoder(nn.Module):
        def __init__(self):
            super().__init__()
            hidden = cfg.temporal_hidden_size
            self.input = nn.Conv1d(len(numeric), hidden, 1)
            self.blocks = nn.Sequential(
                ResidualBlock(hidden, 1),
                ResidualBlock(hidden, 2),
                ResidualBlock(hidden, 4),
                ResidualBlock(hidden, 8),
            )
            self.output = nn.Linear(hidden * 2, cfg.temporal_embedding_size)

        def forward(self, sequence):
            value = sequence.transpose(1, 2)
            value = self.blocks(self.input(value))
            pooled = torch.cat([value.mean(dim=2), value.amax(dim=2)], dim=1)
            return self.output(pooled)

    class DirectionModel(nn.Module):
        def __init__(self, encoder: nn.Module):
            super().__init__()
            self.encoder = encoder
            asset_size = min(16, max(4, len(assets)))
            self.asset_embedding = nn.Embedding(len(assets), asset_size)
            self.head = nn.Sequential(
                nn.Linear(cfg.temporal_embedding_size + asset_size, 64),
                nn.GELU(),
                nn.Dropout(0.15),
                nn.Linear(64, len(horizons)),
            )

        def forward(self, sequence, asset_id):
            encoded = self.encoder(sequence)
            return self.head(
                torch.cat([encoded, self.asset_embedding(asset_id)], dim=1)
            )

    def augment(sequence):
        feature_mask = (
            torch.rand_like(sequence) < 0.10
        )
        time_mask = (
            torch.rand(
                sequence.shape[0], sequence.shape[1], 1, device=sequence.device
            )
            < 0.08
        )
        mask = feature_mask | time_mask
        noise = torch.randn_like(sequence) * 0.015
        return torch.where(mask, torch.zeros_like(sequence), sequence + noise)

    def ntxent(first, second, temperature: float = 0.15):
        first = F.normalize(first, dim=1)
        second = F.normalize(second, dim=1)
        representations = torch.cat([first, second], dim=0)
        similarities = representations @ representations.T / temperature
        count = first.shape[0]
        diagonal = torch.eye(2 * count, dtype=torch.bool, device=device)
        similarities = similarities.masked_fill(diagonal, -1e9)
        targets = torch.arange(2 * count, device=device)
        targets = (targets + count) % (2 * count)
        return F.cross_entropy(similarities, targets)

    encoder = TemporalEncoder().to(device)
    projection = nn.Sequential(
        nn.Linear(cfg.temporal_embedding_size, cfg.temporal_embedding_size),
        nn.GELU(),
        nn.Linear(cfg.temporal_embedding_size, cfg.temporal_embedding_size),
    ).to(device)
    optimizer = torch.optim.AdamW(
        list(encoder.parameters()) + list(projection.parameters()),
        lr=cfg.temporal_learning_rate,
        weight_decay=cfg.temporal_weight_decay,
    )
    print("\nSelf-supervised temporal contrastive pretraining...")
    for epoch in range(cfg.temporal_pretrain_epochs):
        encoder.train()
        projection.train()
        total = 0.0
        count = 0
        for sequence, _, _, _, _ in loader("train", shuffle=True):
            sequence = sequence.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            first = projection(encoder(augment(sequence)))
            second = projection(encoder(augment(sequence)))
            loss = ntxent(first, second)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                list(encoder.parameters()) + list(projection.parameters()), 1.0
            )
            optimizer.step()
            total += float(loss.item()) * len(sequence)
            count += len(sequence)
        print(f"Contrastive epoch {epoch + 1:02d}: loss={total / count:.5f}")

    pretrained_state = copy.deepcopy(encoder.state_dict())

    def supervised_loss(logits, labels, masks):
        raw = F.binary_cross_entropy_with_logits(logits, labels, reduction="none")
        return (raw * masks).sum() / masks.sum().clamp_min(1.0)

    def run_supervised(
        name: str,
        freeze_encoder: bool,
        epochs: int,
    ):
        local_encoder = TemporalEncoder().to(device)
        local_encoder.load_state_dict(pretrained_state)
        model = DirectionModel(local_encoder).to(device)
        for parameter in model.encoder.parameters():
            parameter.requires_grad = not freeze_encoder
        optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=cfg.temporal_learning_rate,
            weight_decay=cfg.temporal_weight_decay,
        )
        best_state = copy.deepcopy(model.state_dict())
        best_loss = float("inf")
        patience = 3
        stale = 0
        for epoch in range(epochs):
            model.train()
            if freeze_encoder:
                model.encoder.eval()
            train_total = 0.0
            train_count = 0
            for sequence, asset_id, labels, masks, _ in loader(
                "train", shuffle=True
            ):
                sequence = sequence.to(device, non_blocking=True)
                asset_id = asset_id.to(device, non_blocking=True)
                labels = labels.to(device, non_blocking=True)
                masks = masks.to(device, non_blocking=True)
                optimizer.zero_grad(set_to_none=True)
                logits = model(sequence, asset_id)
                loss = supervised_loss(logits, labels, masks)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                train_total += float(loss.item()) * len(sequence)
                train_count += len(sequence)
            model.eval()
            validation_total = 0.0
            validation_count = 0
            with torch.no_grad():
                for sequence, asset_id, labels, masks, _ in loader("early_stop"):
                    sequence = sequence.to(device, non_blocking=True)
                    asset_id = asset_id.to(device, non_blocking=True)
                    labels = labels.to(device, non_blocking=True)
                    masks = masks.to(device, non_blocking=True)
                    loss = supervised_loss(model(sequence, asset_id), labels, masks)
                    validation_total += float(loss.item()) * len(sequence)
                    validation_count += len(sequence)
            validation_loss = validation_total / validation_count
            print(
                f"{name} epoch {epoch + 1:02d}: "
                f"train={train_total / train_count:.5f} "
                f"validation={validation_loss:.5f}"
            )
            if validation_loss < best_loss - 1e-5:
                best_loss = validation_loss
                best_state = copy.deepcopy(model.state_dict())
                stale = 0
            else:
                stale += 1
                if stale >= patience:
                    print(f"{name}: early stopping")
                    break
        model.load_state_dict(best_state)
        model.eval()

        def raw_predictions(part_name: str) -> Tuple[np.ndarray, np.ndarray]:
            logits: List[np.ndarray] = []
            row_ids: List[np.ndarray] = []
            with torch.no_grad():
                for sequence, asset_id, _, _, row_id in loader(part_name):
                    output = model(
                        sequence.to(device, non_blocking=True),
                        asset_id.to(device, non_blocking=True),
                    )
                    logits.append(output.cpu().numpy())
                    row_ids.append(row_id.numpy())
            return np.concatenate(logits), np.concatenate(row_ids)

        calibration_matrix, calibration_ids = raw_predictions("calibration")
        calibration_rows = full_frame.set_index("row_id").loc[calibration_ids]
        cache: Dict[str, Tuple[np.ndarray, np.ndarray]] = {
            "calibration": (calibration_matrix, calibration_ids)
        }

        predictions: List[ModelPrediction] = []
        for horizon_index, horizon_minutes in enumerate(horizons):
            label_column = f"label_up_{horizon_minutes}m"
            calibration_valid = calibration_rows[label_column].notna().to_numpy()
            calibrator = fit_platt(
                calibration_matrix[calibration_valid, horizon_index],
                calibration_rows.loc[
                    calibration_valid, label_column
                ].to_numpy(dtype=int),
            )

            def predict_aligned(
                part_name: str,
                *,
                selected_index=horizon_index,
                selected_horizon=horizon_minutes,
                selected_calibrator=calibrator,
            ) -> np.ndarray:
                if part_name not in cache:
                    cache[part_name] = raw_predictions(part_name)
                raw_matrix, row_ids = cache[part_name]
                probability = selected_calibrator.predict_proba(
                    raw_matrix[:, selected_index].reshape(-1, 1)
                )[:, 1]
                mapping = pd.Series(probability, index=row_ids)
                target = part_for_horizon(
                    parts[part_name], selected_horizon
                ).loc[lambda item: item["sequence_valid"]]
                aligned = target["row_id"].map(mapping)
                if aligned.isna().any():
                    raise ValueError(
                        "Temporal prediction alignment lost valid sequence rows"
                    )
                return aligned.to_numpy(dtype=float)

            def save(
                output: Path,
                *,
                selected_horizon=horizon_minutes,
                selected_calibrator=calibrator,
            ) -> None:
                model_path = output / f"{name}.pt"
                if not model_path.exists():
                    torch.save(
                        {
                            "state_dict": model.state_dict(),
                            "numeric_features": numeric,
                            "feature_medians": medians.to_dict(),
                            "feature_means": means.to_dict(),
                            "feature_stds": stds.to_dict(),
                            "assets": assets,
                            "horizons_minutes": horizons,
                            "sequence_length": cfg.sequence_length,
                            "model_name": name,
                            "config": asdict(cfg),
                        },
                        model_path,
                    )
                joblib.dump(
                    selected_calibrator,
                    output
                    / f"{name}_calibrator_{selected_horizon}m.joblib",
                )

            predictions.append(
                ModelPrediction(
                    f"{name}_{horizon_minutes}m",
                    horizon_minutes,
                    predict_aligned("calibration"),
                    predict_aligned("policy"),
                    lambda predict=predict_aligned: predict("test"),
                    save,
                    {
                        "best_validation_loss": best_loss,
                        "sequence_rows": {
                            key: len(value) for key, value in datasets.items()
                        },
                    },
                    sequence_only=True,
                )
            )
        return predictions, model

    frozen_predictions, _ = run_supervised(
        "temporal_contrastive_frozen",
        freeze_encoder=True,
        epochs=cfg.temporal_frozen_head_epochs,
    )
    fine_predictions, _ = run_supervised(
        "temporal_contrastive_finetuned",
        freeze_encoder=False,
        epochs=cfg.temporal_finetune_epochs,
    )
    return [*frozen_predictions, *fine_predictions]


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


def run_tournament(
    state: pd.DataFrame,
    parts: Dict[str, pd.DataFrame],
    split_cutoffs: Dict[str, int],
    source_path: Path,
    cfg: Config,
    output: Path,
) -> Dict[str, object]:
    models: List[ModelPrediction] = []
    failures: Dict[str, str] = {}
    for horizon_minutes in cfg.prediction_horizons_minutes:
        models.append(train_null_model(parts, cfg, horizon_minutes))
        try:
            models.append(
                train_linear_model(parts, cfg, horizon_minutes)
            )
        except Exception as exc:
            key = f"linear_sgd_{horizon_minutes}m"
            failures[key] = f"{type(exc).__name__}: {exc}"
            print(f"{key} failed: {failures[key]}")
        if cfg.train_catboost:
            try:
                models.append(
                    train_catboost_model(parts, cfg, horizon_minutes)
                )
            except Exception as exc:
                key = f"catboost_{horizon_minutes}m"
                failures[key] = f"{type(exc).__name__}: {exc}"
                print(f"{key} failed: {failures[key]}")
    if cfg.train_temporal_encoder:
        try:
            models.extend(train_temporal_models(state, parts, cfg))
        except Exception as exc:
            failures["temporal_models"] = f"{type(exc).__name__}: {exc}"
            print(f"Temporal models failed: {failures['temporal_models']}")

    model_rows: List[Dict[str, object]] = []
    policy_tables: List[pd.DataFrame] = []
    model_by_name = {model.name: model for model in models}
    print("\n================ POLICY-PERIOD TOURNAMENT ================")
    for model in models:
        label = f"label_up_{model.horizon_minutes}m"
        calibration_part = evaluation_part(model, parts, "calibration")
        policy_part = evaluation_part(model, parts, "policy")
        calibration_labels = calibration_part[label].to_numpy(dtype=int)
        policy_labels = policy_part[label].to_numpy(dtype=int)
        if len(model.calibration) != len(calibration_part):
            raise ValueError(
                f"{model.name}: {len(model.calibration)} calibration "
                f"predictions for {len(calibration_part)} rows"
            )
        if len(model.policy) != len(policy_part):
            raise ValueError(
                f"{model.name}: {len(model.policy)} policy predictions for "
                f"{len(policy_part)} rows"
            )
        calibration_report = probability_metrics(
            calibration_labels, model.calibration
        )
        policy_report = probability_metrics(policy_labels, model.policy)
        best, table, passed = search_model_policy(
            model.name,
            model.horizon_minutes,
            model.policy,
            policy_part,
            cfg,
        )
        policy_tables.append(table)
        row = {
            "model": model.name,
            "horizon_minutes": model.horizon_minutes,
            "calibration_auc": calibration_report["roc_auc"],
            "calibration_log_loss": calibration_report["log_loss"],
            "calibration_brier": calibration_report["brier_score"],
            "calibration_ece": calibration_report["ece_10_bins"],
            "policy_auc": policy_report["roc_auc"],
            "policy_log_loss": policy_report["log_loss"],
            "policy_brier": policy_report["brier_score"],
            **best,
            "policy_passed": passed,
        }
        model_rows.append(row)
        print(
            f"{model.name:34s} AUC={policy_report['roc_auc']:.4f} "
            f"best lower expectancy={best.get('lower_95_expectancy_per_unit')} "
            f"trades={best.get('trades')} passed={passed}"
        )
    leaderboard = pd.DataFrame(model_rows)
    leaderboard.to_csv(output / "policy_model_leaderboard.csv", index=False)
    pd.concat(policy_tables, ignore_index=True).to_csv(
        output / "all_policy_searches.csv", index=False
    )

    eligible = leaderboard.loc[
        leaderboard["policy_passed"].eq(True)
        & leaderboard["lower_95_expectancy_per_unit"].notna()
    ]
    selection_passed = not eligible.empty
    selection_pool = eligible if selection_passed else leaderboard.loc[
        leaderboard["lower_95_expectancy_per_unit"].notna()
    ]
    if selection_pool.empty:
        # No model produced a payout-eligible policy. Freeze the best
        # probabilistic forecaster on the policy period for one diagnostic
        # final test, while keeping selection_passed=False so it can never be
        # approved for deployment.
        winner_row = leaderboard.sort_values(
            ["policy_brier", "policy_log_loss"],
            ascending=[True, True],
        ).iloc[0]
    else:
        winner_row = selection_pool.sort_values(
            [
                "lower_95_expectancy_per_unit",
                "policy_brier",
                "trades",
            ],
            ascending=[False, True, False],
        ).iloc[0]
    winner_name = str(winner_row["model"])
    winner = model_by_name[winner_name]
    print(
        f"\nFrozen policy winner before opening final test: {winner_name} "
        f"(horizon={winner.horizon_minutes}m, "
        f"threshold={float(winner_row['threshold']):.2%}, "
        f"top_k={int(winner_row['top_k'])})"
    )

    # Critical: only the policy-selected winner is evaluated on final test.
    winner_horizon = winner.horizon_minutes
    winner_label = f"label_up_{winner_horizon}m"
    test_part = evaluation_part(winner, parts, "test")
    test_probability = winner.predict_test()
    test_labels = test_part[winner_label].to_numpy(dtype=int)
    if len(test_probability) != len(test_part):
        raise ValueError(
            f"{winner_name}: {len(test_probability)} test predictions for "
            f"{len(test_part)} rows"
        )
    test_probability_report = probability_metrics(test_labels, test_probability)
    test_trade_report = policy_metrics(
        test_probability,
        test_labels,
        test_part["asset"].to_numpy(dtype=str),
        test_part["decision_time"].to_numpy(dtype=np.int64),
        float(winner_row["threshold"]),
        int(winner_row["top_k"]),
        cfg,
        cfg.random_seed + 100_000,
    )
    lower_test = test_trade_report.get("lower_95_expectancy_per_unit")
    historical_research_passed = bool(
        selection_passed
        and lower_test is not None
        and lower_test > 0
        and test_trade_report["trades"] >= cfg.minimum_test_trades
        and test_trade_report["days"] >= cfg.minimum_test_days
    )
    offline_approved = bool(
        historical_research_passed
        and not cfg.holdout_previously_summarized
    )

    # Save every trained model for reproducibility, but the metadata names only
    # one policy winner. Do not choose another after viewing final test.
    for model in models:
        try:
            model.save(output)
        except Exception as exc:
            failures[f"save_{model.name}"] = f"{type(exc).__name__}: {exc}"

    confidence, wins, predicted_up = confidence_and_wins(
        test_probability, test_labels
    )
    selected = select_trades(
        confidence,
        test_part["asset"].to_numpy(dtype=str),
        test_part["decision_time"].to_numpy(dtype=np.int64),
        float(winner_row["threshold"]),
        int(winner_row["top_k"]),
        cfg.cooldown_seconds_per_asset,
    )
    predictions = test_part[
        ["decision_time", "asset", winner_label]
    ].copy()
    predictions["probability_up"] = test_probability
    predictions["predicted_direction"] = np.where(
        predicted_up == 1, "call", "put"
    )
    predictions["confidence"] = confidence
    predictions["would_win"] = wins
    predictions["accepted"] = False
    predictions.iloc[
        selected, predictions.columns.get_loc("accepted")
    ] = True
    predictions.to_csv(output / "winner_untouched_test_predictions.csv", index=False)

    accepted = predictions.loc[predictions["accepted"]]
    if accepted.empty:
        breakdown = pd.DataFrame()
    else:
        breakdown = (
            accepted.groupby(["asset", "predicted_direction"])
            .agg(
                trades=("would_win", "size"),
                win_rate=("would_win", "mean"),
                mean_confidence=("confidence", "mean"),
            )
            .reset_index()
        )
    breakdown.to_csv(output / "winner_test_breakdown.csv", index=False)

    metadata = {
        "artifact_type": "iqoption_strategy_independent_tournament",
        "version": "strategy_independent_cross_asset_v2",
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "source_file": source_path.name,
        "source_partial_sha256": partial_sha256(source_path),
        "config": asdict(cfg),
        "features": feature_columns(cfg),
        "assets": sorted(state["asset"].unique().tolist()),
        "state_rows": len(state),
        "split_cutoffs": split_cutoffs,
        "model_failures": failures,
        "winner_selected_on_policy_only": winner_name,
        "winner_horizon_minutes": winner_horizon,
        "winner_policy": clean_json(winner_row.to_dict()),
        "winner_test_probability_metrics": test_probability_report,
        "winner_test_trade_metrics": test_trade_report,
        "policy_selection_passed": selection_passed,
        "historical_research_passed": historical_research_passed,
        "fresh_holdout_required": cfg.holdout_previously_summarized,
        "offline_deployment_approved": offline_approved,
        "live_deployment_approved": False,
        "practice_only": True,
        "limitations": [
            "Historical entry uses next exact 2m candle open",
            "No broker acknowledgement or accepted-strike simulation",
            "No rejected-order simulation",
            "No historical payout variation",
            "Final test is invalidated if another model is selected after viewing it",
        ],
    }
    with (output / "tournament_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(clean_json(metadata), handle, indent=2)

    print("\n================ UNTOUCHED WINNER TEST ================")
    print(json.dumps(clean_json(test_probability_report), indent=2))
    print(json.dumps(clean_json(test_trade_report), indent=2))
    print(f"historical_research_passed={historical_research_passed}")
    print(
        f"fresh_holdout_required={cfg.holdout_previously_summarized}"
    )
    print(f"offline_deployment_approved={offline_approved}")
    print("live_deployment_approved=False")
    return metadata


def write_readme(output: Path, metadata: Dict[str, object]) -> None:
    winner = metadata["winner_selected_on_policy_only"]
    approved = metadata["offline_deployment_approved"]
    text = f"""IQ OPTION STRATEGY-INDEPENDENT TOURNAMENT
================================================

Policy-selected winner: {winner}
Offline approved: {approved}
Live approved: False
Fresh holdout required: {metadata["fresh_holdout_required"]}

Read tournament_metadata.json first.

The policy period selected the model, confidence threshold and cross-sectional
top-k before the final test was opened. Do not switch to another model after
reading the final test; that would turn the test into another tuning period.

Important files
---------------
tournament_metadata.json
policy_model_leaderboard.csv
all_policy_searches.csv
winner_untouched_test_predictions.csv
winner_test_breakdown.csv

Model files are also included when their training completed successfully.

This model does not use the bot's strategies. Even an offline-approved result
requires a matching live feature implementation and IQ Option PRACTICE
verification before any execution decision.

The current July holdout was summarized by the earlier same-asset tournament.
This cross-asset run is therefore exploratory. A positive historical result
must be confirmed on genuinely new candles before offline approval.
"""
    (output / "README.txt").write_text(text, encoding="utf-8")


def zip_outputs(output: Path) -> Path:
    archive = output.parent / f"{output.name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.iterdir()):
            if path.is_file():
                bundle.write(path, arcname=path.name)
    return archive


def main() -> None:
    warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)
    set_reproducible(CFG.random_seed)
    # A unique run directory prevents a failed/retried notebook from silently
    # packaging stale models produced by an earlier configuration.
    run_stamp = pd.Timestamp.now(tz="UTC").strftime("run_%Y%m%dT%H%M%SZ")
    output = Path(CFG.output_dir) / run_stamp
    output.mkdir(parents=True, exist_ok=True)
    print("=" * 76)
    print("IQ OPTION STRATEGY-INDEPENDENT CROSS-ASSET TOURNAMENT v2")
    print("=" * 76)
    print(f"Payout assumption: {CFG.binary_payout:.0%}")
    print(f"Breakeven: {1 / (1 + CFG.binary_payout):.2%}")
    print("No bot strategy is used as an input or candidate generator.")
    print(
        "Current holdout is exploratory because its aggregate outcome was "
        "summarized by the previous tournament."
    )

    source = discover_data_path(CFG.data_path)
    candles = load_candles(source, CFG)
    state = build_state_table(candles, CFG)
    parts, cutoffs = temporal_partitions(state, CFG)
    metadata = run_tournament(state, parts, cutoffs, source, CFG, output)
    write_readme(output, metadata)
    archive = zip_outputs(output)
    print(f"\nDownload from Kaggle Output: {archive}")


if __name__ == "__main__":
    main()
