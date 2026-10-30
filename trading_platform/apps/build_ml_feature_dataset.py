#!/usr/bin/env python3
"""Build causal enriched candle and candidate datasets from local SQLite data.

The script is read-only with respect to both the running harvester database and
the scanner candidate ledger.  Every context lookup is bounded by the candle or
candidate decision timestamp.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from trading_platform.research.context_features import (
    ALL_CONTEXT_FEATURES,
    MarketContextProvider,
    canonical_asset,
    epoch_ms,
)
from trading_platform.research.feature_engineering import FeatureEngineer
from trading_platform.research.feature_dataset import (
    FeatureDatasetRequest,
    build_feature_dataset,
)


def read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.execute("PRAGMA query_only=ON")
    return connection


def write_frame(frame: pd.DataFrame, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_parquet(target, index=False)
        return target
    except (ImportError, ModuleNotFoundError):
        fallback = target.with_suffix(".csv.gz")
        frame.to_csv(fallback, index=False, compression="gzip")
        return fallback


def load_candles(
    context_db: Path,
    start_ms: Optional[int],
    timeframe: int,
) -> pd.DataFrame:
    condition = "AND candle_start_ms >= ?" if start_ms is not None else ""
    parameters: tuple[Any, ...] = (timeframe, start_ms) if start_ms is not None else (timeframe,)
    historical_query = f"""
        SELECT canonical_asset AS asset, broker_asset, timeframe_sec AS timeframe,
               candle_start_ms, open, high, low, close, volume,
               0 AS source_priority
        FROM historical_candles
        WHERE timeframe_sec = ? {condition}
    """
    realtime_query = f"""
        SELECT canonical_asset AS asset, broker_asset, timeframe_sec AS timeframe,
               candle_start_ms, open, high, low, close, volume,
               1 AS source_priority
        FROM realtime_candles
        WHERE timeframe_sec = ? AND finalized = 1 {condition}
    """
    with closing(read_only(context_db)) as connection:
        historical = pd.read_sql_query(historical_query, connection, params=parameters)
        realtime = pd.read_sql_query(realtime_query, connection, params=parameters)
    available = [item for item in (historical, realtime) if not item.empty]
    frame = pd.concat(available, ignore_index=True) if available else pd.DataFrame()
    if frame.empty:
        raise ValueError(f"No finalized {timeframe}s candles found in {context_db}")
    frame["asset"] = frame["asset"].map(canonical_asset)
    frame = (
        frame.sort_values(
            ["asset", "candle_start_ms", "source_priority"],
            kind="mergesort",
        )
        .drop_duplicates(["asset", "candle_start_ms"], keep="last")
        .sort_values(["asset", "candle_start_ms"])
        .reset_index(drop=True)
    )
    frame["timestamp"] = pd.to_datetime(frame["candle_start_ms"], unit="ms", utc=True)
    return frame.drop(columns=["source_priority"])


def context_start(provider: MarketContextProvider, warmup_hours: int) -> Optional[int]:
    coverage = provider.coverage()
    starts = []
    for name in ("quotes", "mood", "payout"):
        item = coverage.get(name, {})
        if item.get("first_ms") is not None:
            starts.append(int(item["first_ms"]))
    if not starts:
        return None
    # All principal feeds must have started. Keep a warm-up prefix so rolling
    # candle indicators and LSTM sequences do not begin cold.
    return max(starts) - int(warmup_hours) * 3_600_000


def enrich_candles(
    candles: pd.DataFrame,
    provider: MarketContextProvider,
    timeframe: int,
) -> pd.DataFrame:
    pieces = []
    for index, (asset, group) in enumerate(candles.groupby("asset", sort=True), 1):
        group = group.sort_values("candle_start_ms").reset_index(drop=True)
        print(f"[{index:02d}] enriching {asset}: {len(group):,} candles")
        enriched = provider.enrich_candles(group, asset, timeframe)
        enriched["decision_time_ms"] = enriched["candle_start_ms"] + timeframe * 1_000
        pieces.append(enriched)
    result = pd.concat(pieces, ignore_index=True)
    return result.sort_values(["decision_time_ms", "asset"]).reset_index(drop=True)


def technical_candidate_rows(enriched: pd.DataFrame) -> pd.DataFrame:
    engineer = FeatureEngineer()
    pieces = []
    for asset, group in enriched.groupby("asset", sort=True):
        featured = engineer.generate_features(group.copy(), is_training=False)
        featured["asset"] = asset
        pieces.append(featured)
    return pd.concat(pieces, ignore_index=True)


def _candidate_time_ms(value: Any) -> Optional[int]:
    return epoch_ms(value)


def load_candidates(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    with closing(read_only(path)) as connection:
        frame = pd.read_sql_query(
            """
            SELECT asset, direction, decision_time, expiry_time,
                   duration_minutes, strategy, score AS strategy_score,
                   confidence AS strategy_confidence, confluence, regime,
                   features_json, entry_price, settlement_price, outcome, label
            FROM candidates
            WHERE label IN (0, 1) AND outcome IN ('win', 'loss')
            ORDER BY decision_time
            """,
            connection,
        )
    if frame.empty:
        return frame
    frame["asset"] = frame["asset"].map(canonical_asset)
    frame["direction"] = frame["direction"].astype(str).str.lower()
    frame["decision_time_ms"] = frame["decision_time"].map(_candidate_time_ms)
    frame["expiry_time_ms"] = frame["expiry_time"].map(_candidate_time_ms)
    frame = frame.dropna(subset=["decision_time_ms", "expiry_time_ms"])
    frame["decision_time_ms"] = frame["decision_time_ms"].astype(np.int64)
    frame["expiry_time_ms"] = frame["expiry_time_ms"].astype(np.int64)
    return frame


def flatten_research_json(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "features_json" not in frame:
        return frame
    mtf_5m = []
    mtf_15m = []
    for raw in frame["features_json"].fillna("{}"):
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        indicators_5m = payload.get("indicators_5m") or {}
        indicators_15m = payload.get("indicators_15m") or {}
        mtf_5m.append(str(indicators_5m.get("trend", "unknown")))
        mtf_15m.append(str(indicators_15m.get("trend", "unknown")))
    result = frame.copy()
    result["trend_5m"] = mtf_5m
    result["trend_15m"] = mtf_15m
    return result.drop(columns=["features_json"])


def build_candidate_dataset(
    candidates: pd.DataFrame,
    featured_candles: pd.DataFrame,
) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    candle_columns = [
        column
        for column in featured_candles.columns
        if column not in {"broker_asset", "timeframe", "volume"}
    ]
    candle_rows = featured_candles[candle_columns].copy()
    result = candidates.merge(
        candle_rows,
        on=["asset", "decision_time_ms"],
        how="inner",
        validate="many_to_one",
        suffixes=("", "_candle"),
    )
    result = flatten_research_json(result)
    result["direction_sign"] = np.where(result["direction"].eq("call"), 1.0, -1.0)
    result["payout_ev_if_correct"] = result["payout_fraction"]
    return result.sort_values(["decision_time_ms", "asset", "strategy"]).reset_index(drop=True)


def coverage_report(
    candles: pd.DataFrame,
    candidates: pd.DataFrame,
    provider: MarketContextProvider,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "context_schema": "market_context_v2",
        "harvester": provider.coverage(),
        "enriched_candles": int(len(candles)),
        "assets": int(candles["asset"].nunique()) if not candles.empty else 0,
        "first_decision_ms": int(candles["decision_time_ms"].min()) if not candles.empty else None,
        "last_decision_ms": int(candles["decision_time_ms"].max()) if not candles.empty else None,
        "candidate_rows": int(len(candidates)),
    }
    if not candles.empty:
        for flag in ("quote_missing", "mood_missing", "payout_missing", "deal_missing"):
            report[f"{flag}_rate"] = float(candles[flag].mean())
        report["context_complete_rate"] = float(candles["context_complete"].mean())
        span = candles["decision_time_ms"].max() - candles["decision_time_ms"].min()
        report["calendar_span_days"] = float(span / 86_400_000)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build causal enriched ML datasets")
    parser.add_argument("--context-db", type=Path, default=Path("data/ml/market_context.sqlite"))
    parser.add_argument("--candidate-db", type=Path, default=Path("data/candidate_research.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/ml/enriched"))
    parser.add_argument("--timeframe", type=int, default=120)
    parser.add_argument("--warmup-hours", type=int, default=6)
    parser.add_argument("--all-history", action="store_true")
    parser.add_argument("--dataset-id")
    return parser.parse_args()


class SQLiteFeatureDatasetAdapter:
    """Read-only SQLite implementation of the platform feature-build port."""

    def __init__(self, context_db: Path, candidate_db: Path) -> None:
        self.context_db = context_db
        self.candidate_db = candidate_db
        self.provider = MarketContextProvider(context_db)

    def context_start(self, warmup_hours: int) -> Optional[int]:
        return context_start(self.provider, warmup_hours)

    def load_candles(self, start_ms: Optional[int], timeframe: int) -> pd.DataFrame:
        return load_candles(self.context_db, start_ms, timeframe)

    def enrich_candles(self, candles: pd.DataFrame, timeframe: int) -> pd.DataFrame:
        return enrich_candles(candles, self.provider, timeframe)

    def load_candidates(self) -> pd.DataFrame:
        return load_candidates(self.candidate_db)

    @staticmethod
    def is_empty(value: pd.DataFrame) -> bool:
        return value.empty

    @staticmethod
    def technical_candidate_rows(enriched: pd.DataFrame) -> pd.DataFrame:
        return technical_candidate_rows(enriched)

    @staticmethod
    def build_candidate_dataset(candidates, featured):
        return build_candidate_dataset(candidates, featured)

    @staticmethod
    def write_frame(frame: pd.DataFrame, target: Path) -> Path:
        return write_frame(frame, target)

    def coverage_report(self, candles, candidates) -> Dict[str, Any]:
        return coverage_report(candles, candidates, self.provider)


def main() -> int:
    args = parse_args()
    if not args.context_db.is_file():
        raise FileNotFoundError(args.context_db)
    result = build_feature_dataset(
        FeatureDatasetRequest(
            output_dir=args.output_dir,
            timeframe=args.timeframe,
            warmup_hours=args.warmup_hours,
            all_history=args.all_history,
            dataset_id=args.dataset_id,
        ),
        SQLiteFeatureDatasetAdapter(args.context_db, args.candidate_db),
    )
    print(f"Candle dataset: {result['candle_dataset']}")
    print(f"Candidate dataset: {result['candidate_dataset'] or 'not created'}")
    print(f"Manifest: {result['manifest'] or 'not requested'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
