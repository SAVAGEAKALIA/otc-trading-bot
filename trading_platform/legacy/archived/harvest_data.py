#!/usr/bin/env python3
"""Harvest closed IQ Option candles into SQLite for OTC LSTM training.

The requested asset name is deliberately passed to the API unchanged.  For
example, ``EURUSD-OTC`` is harvested from the OTC feed, never from EURUSD.

Only completed candles are stored.  This prevents an in-progress candle from
being used as if its final close were known by the model.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Use the repository's patched IQ Option client, not a pip-installed copy.
from trading_platform.vendor.iqoptionapi.iqoptionapi.stable_api import IQ_Option


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
LOGGER = logging.getLogger("harvester")

TIMEFRAMES: dict[str, int] = {"2m": 120, "5m": 300, "15m": 900}
CHUNK_SIZE = 1_000  # IQ Option's maximum candle request size.
DEFAULT_ASSETS = (
    "EURUSD-OTC,GBPUSD-OTC,USDJPY-OTC,AUDUSD-OTC,NZDUSD-OTC,"
    "USDCAD-OTC,USDCHF-OTC,EURGBP-OTC,EURJPY-OTC,GBPJPY-OTC,"
    "EURAUD-OTC,GBPAUD-OTC,AUDJPY-OTC,CHFJPY-OTC,CADJPY-OTC"
)


def utc_label(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def last_closed_end(now: int, timeframe_seconds: int) -> int:
    """Return the last second of the most recently completed candle.

    At 12:34:17 for a 120-second timeframe, the candle beginning 12:34 is
    still open.  The API is therefore queried no later than 12:33:59.
    """
    return (now // timeframe_seconds) * timeframe_seconds - 1


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candles (
            asset TEXT NOT NULL,
            timeframe INTEGER NOT NULL,
            timestamp INTEGER NOT NULL,
            open REAL NOT NULL,
            close REAL NOT NULL,
            min REAL NOT NULL,
            max REAL NOT NULL,
            volume INTEGER NOT NULL,
            PRIMARY KEY (asset, timeframe, timestamp)
        )
        """
    )
    conn.commit()
    return conn


def connect_api() -> IQ_Option | None:
    load_dotenv(PROJECT_ROOT / ".env")
    email = os.environ.get("IQ_EMAIL")
    password = os.environ.get("IQ_PASSWORD")
    if not email or not password:
        LOGGER.error("Missing IQ_EMAIL or IQ_PASSWORD in %s", PROJECT_ROOT / ".env")
        return None

    api = IQ_Option(email, password)
    for attempt in range(1, 4):
        connected, reason = api.connect()
        if connected and api.check_connect():
            api.change_balance("PRACTICE")
            LOGGER.info("Connected to IQ Option.")
            return api
        LOGGER.warning("Connection attempt %d/3 failed: %s", attempt, reason)
        time.sleep(2)

    LOGGER.error("Failed to connect to IQ Option after three attempts.")
    return None


def normalise_candle(candle: dict, asset: str, timeframe: int) -> tuple | None:
    """Validate a candle record before inserting it into the training store."""
    try:
        timestamp = int(candle["from"])
        open_price = float(candle["open"])
        close_price = float(candle["close"])
        low_price = float(candle["min"])
        high_price = float(candle["max"])
        volume = int(candle.get("volume", 0))
    except (KeyError, TypeError, ValueError) as exc:
        LOGGER.warning("Ignoring malformed %s candle: %s", asset, exc)
        return None

    if timeframe <= 0 or timestamp % timeframe != 0:
        LOGGER.warning("Ignoring unaligned %s candle at %s", asset, timestamp)
        return None
    if low_price > min(open_price, close_price) or high_price < max(open_price, close_price):
        LOGGER.warning("Ignoring invalid OHLC range for %s at %s", asset, utc_label(timestamp))
        return None
    return (asset, timeframe, timestamp, open_price, close_price, low_price, high_price, volume)


UPSERT_CANDLES = """
    INSERT INTO candles (asset, timeframe, timestamp, open, close, min, max, volume)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(asset, timeframe, timestamp) DO UPDATE SET
        open = excluded.open,
        close = excluded.close,
        min = excluded.min,
        max = excluded.max,
        volume = excluded.volume
"""


def harvest_asset(
    api: IQ_Option,
    conn: sqlite3.Connection,
    asset: str,
    timeframe: int,
    days: int,
    request_pause: float,
) -> None:
    """Backfill only fully closed candles, retaining the exact requested symbol."""
    now = int(time.time())
    start_time = now - days * 86_400
    current_end = last_closed_end(now, timeframe)
    inserted = 0

    LOGGER.info("Harvesting %s [%ss] from %s", asset, timeframe, utc_label(start_time))
    while current_end >= start_time:
        # Do not change asset here: -OTC is the market identity used by IQ Option.
        candles = api.get_candles(asset, timeframe, CHUNK_SIZE, current_end)
        if not candles:
            LOGGER.warning("No candles returned for %s ending %s", asset, utc_label(current_end))
            break

        closed_cutoff = last_closed_end(int(time.time()), timeframe)
        records = [
            record
            for candle in candles
            if (record := normalise_candle(candle, asset, timeframe)) is not None
            and record[2] <= closed_cutoff
        ]
        if records:
            conn.executemany(UPSERT_CANDLES, records)
            conn.commit()
            inserted += len(records)

        oldest = min(int(c["from"]) for c in candles if "from" in c)
        LOGGER.info(
            "%s [%ss]: received=%d stored=%d oldest=%s",
            asset, timeframe, len(candles), len(records), utc_label(oldest),
        )
        if oldest >= current_end:
            LOGGER.warning("No backward time progress for %s; stopping this series.", asset)
            break
        current_end = oldest - 1
        time.sleep(request_pause)

    LOGGER.info("Finished %s [%ss]: %d rows written/refreshed.", asset, timeframe, inserted)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harvest closed IQ Option OTC candles.")
    parser.add_argument("--days", type=int, default=180, help="History to request per asset/timeframe.")
    parser.add_argument("--assets", default=DEFAULT_ASSETS, help="Comma-separated IQ Option assets; retain -OTC.")
    parser.add_argument("--timeframes", default="2m,5m,15m", help="Comma-separated: 2m,5m,15m.")
    parser.add_argument("--db", type=Path, default=Path("data/ml/historical_candles.sqlite"))
    parser.add_argument("--pause", type=float, default=0.5, help="Seconds between API requests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.days <= 0 or args.pause < 0:
        raise SystemExit("--days must be positive and --pause cannot be negative.")
    assets = [asset.strip().upper() for asset in args.assets.split(",") if asset.strip()]
    if not assets:
        raise SystemExit("No assets supplied.")
    unknown_timeframes = [name.strip() for name in args.timeframes.split(",") if name.strip() not in TIMEFRAMES]
    if unknown_timeframes:
        raise SystemExit(f"Unsupported timeframe(s): {', '.join(unknown_timeframes)}")
    timeframes = [TIMEFRAMES[name.strip()] for name in args.timeframes.split(",") if name.strip()]

    api = connect_api()
    if api is None:
        return 1
    conn = get_db_connection(args.db)
    try:
        for asset in assets:
            for timeframe in timeframes:
                harvest_asset(api, conn, asset, timeframe, args.days, args.pause)
    finally:
        conn.close()
    LOGGER.info("All harvesting completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
