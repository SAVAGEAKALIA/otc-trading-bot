"""Read-only loaders for broker OTC candles.

Two sources:
- historical_candles.sqlite `candles` (asset, timeframe, timestamp[s], open, close, min, max)
- market_context.sqlite `realtime_candles` / `mood_samples` / `payout_samples` (ms timestamps)
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_DB = ROOT / "data/ml/historical_candles.sqlite"
CONTEXT_DB = ROOT / "data/ml/market_context.sqlite"

BAR_COLUMNS = ["asset", "t", "o", "h", "l", "c"]


def sha256_file(path: Path, chunk: int = 1 << 24) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def load_historical(timeframe: int, path: Path = HISTORICAL_DB) -> pd.DataFrame:
    """Bars with t = bar start in UTC seconds, sorted by (asset, t)."""
    with _connect(path) as connection:
        frame = pd.read_sql_query(
            "select asset, timestamp as t, open as o, max as h, min as l, close as c "
            "from candles where timeframe=? order by asset, timestamp",
            connection,
            params=(timeframe,),
        )
    return _clean(frame)


def load_realtime(timeframe: int, path: Path = CONTEXT_DB) -> pd.DataFrame:
    """Bars recorded live by the old collector (Jul 31 - Aug 20 2026)."""
    with _connect(path) as connection:
        columns = {row[1] for row in connection.execute("pragma table_info(realtime_candles)")}
        high = "high" if "high" in columns else "max"
        low = "low" if "low" in columns else "min"
        frame = pd.read_sql_query(
            f"select broker_asset as asset, candle_start_ms/1000 as t, open as o, {high} as h, "
            f"{low} as l, close as c from realtime_candles where timeframe_sec=? "
            "order by broker_asset, candle_start_ms",
            connection,
            params=(timeframe,),
        )
    return _clean(frame)


def load_mood(path: Path = CONTEXT_DB, instrument: str = "turbo-option") -> pd.DataFrame:
    with _connect(path) as connection:
        return pd.read_sql_query(
            "select broker_asset as asset, observed_bucket_ms, received_at_ms, call_fraction "
            "from mood_samples where instrument_type=? order by broker_asset, received_at_ms",
            connection,
            params=(instrument,),
        )


def load_payouts(path: Path = CONTEXT_DB) -> pd.DataFrame:
    with _connect(path) as connection:
        return pd.read_sql_query(
            "select broker_asset as asset, instrument_type, observed_bucket_ms, payout_fraction "
            "from payout_samples where payout_fraction is not null",
            connection,
        )


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.dropna()
    frame = frame[(frame.o > 0) & (frame.c > 0) & (frame.h >= frame[["o", "c"]].max(axis=1))
                  & (frame.l <= frame[["o", "c"]].min(axis=1))]
    frame = frame.drop_duplicates(["asset", "t"], keep="last")
    frame["t"] = frame.t.astype("int64")
    return frame.sort_values(["asset", "t"]).reset_index(drop=True)[BAR_COLUMNS]
