#!/usr/bin/env python3
"""Causally timestamped IQ Option research-data harvester.

This process is intentionally independent from the trading bot.  It never
places, modifies, or closes an order.  It collects only market state that was
observable before a future label:

* historical 2m/5m/15m candles (optional backfill);
* live broker candle updates and bid/ask samples;
* aggregate traders' mood snapshots;
* binary/turbo/digital payout or commission snapshots;
* privacy-stripped public live-deal flow.

Account balance, personal profiles, trader identities, countries, leaderboards,
and raw websocket payloads are deliberately not persisted.  They are either
not market features or introduce privacy, leakage, and overfitting risks.

Examples:

    python3 harvest_market_data.py --mode live
    python3 harvest_market_data.py --mode both --history-days 30
    python3 harvest_market_data.py --self-test

The API wrapper is unofficial and may change without notice.  Use a practice
account and keep this collector separate from the execution process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import queue
import signal
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_API_ROOT = PROJECT_ROOT / "iqoptionapi"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(LOCAL_API_ROOT))

from trading_platform.vendor.iqoptionapi.iqoptionapi.stable_api import IQ_Option  # noqa: E402
import trading_platform.vendor.iqoptionapi.iqoptionapi.constants as OP_code  # noqa: E402


LOGGER = logging.getLogger("market_harvester")
SCHEMA_VERSION = "1"
DEFAULT_DB = PROJECT_ROOT / "data" / "ml" / "market_context.sqlite"
DEFAULT_ASSETS = (
    "EURUSD-OTC,GBPUSD-OTC,USDJPY-OTC,AUDUSD-OTC,NZDUSD-OTC,"
    "USDCAD-OTC,USDCHF-OTC,EURGBP-OTC,EURJPY-OTC,GBPJPY-OTC,"
    "EURAUD-OTC,GBPAUD-OTC,AUDJPY-OTC,CHFJPY-OTC,CADJPY-OTC"
)
HISTORICAL_TIMEFRAMES = (120, 300, 900)
VALID_DIRECTIONS = {"call", "put"}


def utc_ms() -> int:
    return time.time_ns() // 1_000_000


def finite_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalize_epoch_ms(value: Any) -> Optional[int]:
    """Normalize a plausible Unix timestamp expressed in s, ms, us, or ns."""
    numeric = finite_float(value)
    if numeric is None or numeric <= 0:
        return None
    magnitude = abs(numeric)
    if magnitude < 100_000_000_000:  # seconds
        numeric *= 1_000
    elif magnitude < 100_000_000_000_000:  # milliseconds
        pass
    elif magnitude < 100_000_000_000_000_000:  # microseconds
        numeric /= 1_000
    else:  # nanoseconds
        numeric /= 1_000_000
    return int(numeric)


def canonical_asset(symbol: str) -> str:
    """Use one model identity while retaining the exact broker symbol."""
    cleaned = str(symbol).strip().upper()
    if cleaned.endswith("-OP"):
        return f"{cleaned[:-3]}-OTC"
    return cleaned


def symbol_candidates(requested: str) -> list[str]:
    symbol = str(requested).strip().upper()
    candidates = [symbol]
    if symbol.endswith("-OTC"):
        base = symbol[:-4]
        candidates.extend((f"{base}-OP", base))
    elif symbol.endswith("-OP"):
        base = symbol[:-3]
        candidates.extend((f"{base}-OTC", base))
    else:
        candidates.extend((f"{symbol}-OTC", f"{symbol}-OP"))
    return list(dict.fromkeys(candidates))


def resolve_assets(requested_assets: Iterable[str]) -> dict[str, str]:
    """Map requested names to symbols present in the wrapper's opcode table."""
    available = {str(name).upper() for name in OP_code.ACTIVES}
    resolved: dict[str, str] = {}
    for requested in requested_assets:
        match = next(
            (candidate for candidate in symbol_candidates(requested) if candidate in available),
            None,
        )
        if match is None:
            LOGGER.warning("Skipping unknown broker symbol %s", requested)
            continue
        resolved[canonical_asset(requested)] = match
    return resolved


def broker_server_ms(api: IQ_Option) -> Optional[int]:
    try:
        return normalize_epoch_ms(api.get_server_timestamp())
    except Exception:
        return None


def sqlite_connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30.0)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


class MarketStore:
    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite_connect(path)
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS historical_candles (
                canonical_asset TEXT NOT NULL,
                broker_asset TEXT NOT NULL,
                timeframe_sec INTEGER NOT NULL,
                candle_start_ms INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                harvested_at_ms INTEGER NOT NULL,
                PRIMARY KEY (broker_asset, timeframe_sec, candle_start_ms)
            );

            CREATE TABLE IF NOT EXISTS realtime_candles (
                canonical_asset TEXT NOT NULL,
                broker_asset TEXT NOT NULL,
                timeframe_sec INTEGER NOT NULL,
                candle_start_ms INTEGER NOT NULL,
                source_event_ms INTEGER,
                received_at_ms INTEGER NOT NULL,
                server_at_receive_ms INTEGER,
                clock_offset_ms INTEGER,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                bid REAL,
                ask REAL,
                spread REAL,
                finalized INTEGER NOT NULL CHECK (finalized IN (0, 1)),
                PRIMARY KEY (broker_asset, timeframe_sec, candle_start_ms)
            );

            CREATE TABLE IF NOT EXISTS quote_samples (
                canonical_asset TEXT NOT NULL,
                broker_asset TEXT NOT NULL,
                source_event_ms INTEGER NOT NULL,
                received_at_ms INTEGER NOT NULL,
                server_at_receive_ms INTEGER,
                clock_offset_ms INTEGER,
                bid REAL NOT NULL,
                ask REAL NOT NULL,
                mid REAL NOT NULL,
                spread REAL NOT NULL,
                PRIMARY KEY (broker_asset, source_event_ms, bid, ask)
            );

            CREATE TABLE IF NOT EXISTS mood_samples (
                canonical_asset TEXT NOT NULL,
                broker_asset TEXT NOT NULL,
                instrument_type TEXT NOT NULL,
                observed_bucket_ms INTEGER NOT NULL,
                received_at_ms INTEGER NOT NULL,
                server_at_receive_ms INTEGER,
                clock_offset_ms INTEGER,
                call_fraction REAL NOT NULL,
                put_fraction REAL NOT NULL,
                PRIMARY KEY (
                    broker_asset, instrument_type, observed_bucket_ms
                )
            );

            CREATE TABLE IF NOT EXISTS payout_samples (
                canonical_asset TEXT NOT NULL,
                broker_asset TEXT NOT NULL,
                instrument_type TEXT NOT NULL,
                observed_bucket_ms INTEGER NOT NULL,
                received_at_ms INTEGER NOT NULL,
                server_at_receive_ms INTEGER,
                clock_offset_ms INTEGER,
                commission_percent REAL,
                payout_fraction REAL,
                source TEXT NOT NULL,
                PRIMARY KEY (
                    broker_asset, instrument_type, observed_bucket_ms, source
                )
            );

            CREATE TABLE IF NOT EXISTS live_deal_events (
                event_hash TEXT PRIMARY KEY,
                canonical_asset TEXT NOT NULL,
                broker_asset TEXT NOT NULL,
                instrument_type TEXT NOT NULL,
                expiration_type TEXT,
                direction TEXT NOT NULL CHECK (direction IN ('call', 'put')),
                amount REAL,
                event_time_ms INTEGER,
                expiration_ms INTEGER,
                received_at_ms INTEGER NOT NULL,
                server_at_receive_ms INTEGER,
                clock_offset_ms INTEGER,
                receive_latency_ms INTEGER
            );

            CREATE TABLE IF NOT EXISTS clock_samples (
                observed_bucket_ms INTEGER PRIMARY KEY,
                received_at_ms INTEGER NOT NULL,
                server_at_receive_ms INTEGER NOT NULL,
                clock_offset_ms INTEGER NOT NULL,
                websocket_connected INTEGER NOT NULL
                    CHECK (websocket_connected IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS collection_health (
                observed_bucket_ms INTEGER PRIMARY KEY,
                received_at_ms INTEGER NOT NULL,
                websocket_connected INTEGER NOT NULL,
                assets_subscribed INTEGER NOT NULL,
                queued_deals INTEGER NOT NULL,
                last_quote_age_ms INTEGER,
                note TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_historical_causal
                ON historical_candles (
                    canonical_asset, timeframe_sec, candle_start_ms
                );
            CREATE INDEX IF NOT EXISTS idx_realtime_causal
                ON realtime_candles (
                    canonical_asset, timeframe_sec, candle_start_ms, finalized
                );
            CREATE INDEX IF NOT EXISTS idx_quotes_causal
                ON quote_samples (canonical_asset, source_event_ms);
            CREATE INDEX IF NOT EXISTS idx_mood_causal
                ON mood_samples (canonical_asset, observed_bucket_ms);
            CREATE INDEX IF NOT EXISTS idx_payout_causal
                ON payout_samples (
                    canonical_asset, instrument_type, observed_bucket_ms
                );
            CREATE INDEX IF NOT EXISTS idx_deals_causal
                ON live_deal_events (
                    canonical_asset, event_time_ms, received_at_ms
                );

            CREATE VIEW IF NOT EXISTS deal_flow_10s AS
            SELECT
                canonical_asset,
                broker_asset,
                (COALESCE(event_time_ms, received_at_ms) / 10000) * 10000
                    AS bucket_start_ms,
                COUNT(*) AS deal_count,
                SUM(CASE WHEN direction = 'call' THEN 1 ELSE 0 END)
                    AS call_count,
                SUM(CASE WHEN direction = 'put' THEN 1 ELSE 0 END)
                    AS put_count,
                SUM(CASE WHEN direction = 'call'
                         THEN COALESCE(amount, 0.0) ELSE 0.0 END)
                    AS call_amount,
                SUM(CASE WHEN direction = 'put'
                         THEN COALESCE(amount, 0.0) ELSE 0.0 END)
                    AS put_amount,
                CAST(SUM(CASE WHEN direction = 'call' THEN 1 ELSE 0 END) AS REAL)
                    / NULLIF(COUNT(*), 0) AS call_count_fraction,
                SUM(CASE WHEN direction = 'call'
                         THEN COALESCE(amount, 0.0) ELSE 0.0 END)
                    / NULLIF(SUM(COALESCE(amount, 0.0)), 0.0)
                    AS call_amount_fraction
            FROM live_deal_events
            GROUP BY canonical_asset, broker_asset, bucket_start_ms;
            """
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("created_or_opened_utc", datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()

    def insert_historical(
        self,
        canonical: str,
        broker: str,
        timeframe_sec: int,
        candles: Iterable[Mapping[str, Any]],
    ) -> int:
        harvested_at = utc_ms()
        rows = []
        for candle in candles:
            start_ms = normalize_epoch_ms(candle.get("from"))
            values = (
                finite_float(candle.get("open")),
                finite_float(candle.get("max")),
                finite_float(candle.get("min")),
                finite_float(candle.get("close")),
            )
            if start_ms is None or any(value is None for value in values):
                continue
            rows.append(
                (
                    canonical,
                    broker,
                    timeframe_sec,
                    start_ms,
                    *values,
                    finite_float(candle.get("volume")),
                    harvested_at,
                )
            )
        self.connection.executemany(
            """
            INSERT OR IGNORE INTO historical_candles (
                canonical_asset, broker_asset, timeframe_sec, candle_start_ms,
                open, high, low, close, volume, harvested_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.connection.commit()
        return len(rows)

    def upsert_realtime(
        self,
        canonical: str,
        broker: str,
        timeframe_sec: int,
        candle: Mapping[str, Any],
        received_at: int,
        server_at_receive: Optional[int],
    ) -> bool:
        start_ms = normalize_epoch_ms(candle.get("from"))
        event_ms = normalize_epoch_ms(candle.get("at"))
        values = (
            finite_float(candle.get("open")),
            finite_float(candle.get("max")),
            finite_float(candle.get("min")),
            finite_float(candle.get("close", candle.get("value"))),
        )
        if start_ms is None or any(value is None for value in values):
            return False

        bid = finite_float(candle.get("bid"))
        ask = finite_float(candle.get("ask"))
        spread = ask - bid if bid is not None and ask is not None else None
        clock_offset = (
            server_at_receive - received_at
            if server_at_receive is not None
            else None
        )
        causal_now = server_at_receive or event_ms or received_at
        finalized = int(causal_now >= start_ms + timeframe_sec * 1_000)

        self.connection.execute(
            """
            INSERT INTO realtime_candles (
                canonical_asset, broker_asset, timeframe_sec, candle_start_ms,
                source_event_ms, received_at_ms, server_at_receive_ms,
                clock_offset_ms, open, high, low, close, volume, bid, ask,
                spread, finalized
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(broker_asset, timeframe_sec, candle_start_ms)
            DO UPDATE SET
                source_event_ms = excluded.source_event_ms,
                received_at_ms = excluded.received_at_ms,
                server_at_receive_ms = excluded.server_at_receive_ms,
                clock_offset_ms = excluded.clock_offset_ms,
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                bid = excluded.bid,
                ask = excluded.ask,
                spread = excluded.spread,
                finalized = MAX(realtime_candles.finalized, excluded.finalized)
            """,
            (
                canonical,
                broker,
                timeframe_sec,
                start_ms,
                event_ms,
                received_at,
                server_at_receive,
                clock_offset,
                *values,
                finite_float(candle.get("volume")),
                bid,
                ask,
                spread,
                finalized,
            ),
        )

        if bid is not None and ask is not None and ask >= bid:
            quote_time = event_ms or server_at_receive or received_at
            self.connection.execute(
                """
                INSERT OR IGNORE INTO quote_samples (
                    canonical_asset, broker_asset, source_event_ms,
                    received_at_ms, server_at_receive_ms, clock_offset_ms,
                    bid, ask, mid, spread
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical,
                    broker,
                    quote_time,
                    received_at,
                    server_at_receive,
                    clock_offset,
                    bid,
                    ask,
                    (bid + ask) / 2.0,
                    ask - bid,
                ),
            )
        return True

    def insert_mood(
        self,
        canonical: str,
        broker: str,
        instrument_type: str,
        interval_ms: int,
        call_fraction: float,
        received_at: int,
        server_at_receive: Optional[int],
    ) -> None:
        if not 0.0 <= call_fraction <= 1.0:
            return
        observed = server_at_receive or received_at
        bucket = observed // interval_ms * interval_ms
        clock_offset = (
            server_at_receive - received_at
            if server_at_receive is not None
            else None
        )
        self.connection.execute(
            """
            INSERT OR REPLACE INTO mood_samples (
                canonical_asset, broker_asset, instrument_type,
                observed_bucket_ms, received_at_ms, server_at_receive_ms,
                clock_offset_ms, call_fraction, put_fraction
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical,
                broker,
                instrument_type,
                bucket,
                received_at,
                server_at_receive,
                clock_offset,
                call_fraction,
                1.0 - call_fraction,
            ),
        )

    def finalize_due_realtime_candles(self, causal_now_ms: int) -> None:
        """Mark a candle closed only after broker/local causal time passes it."""
        self.connection.execute(
            """
            UPDATE realtime_candles
            SET finalized = 1
            WHERE finalized = 0
              AND candle_start_ms + timeframe_sec * 1000 <= ?
            """,
            (causal_now_ms,),
        )

    def insert_payout(
        self,
        canonical: str,
        broker: str,
        instrument_type: str,
        interval_ms: int,
        received_at: int,
        server_at_receive: Optional[int],
        source: str,
        commission_percent: Optional[float] = None,
        payout_fraction: Optional[float] = None,
    ) -> None:
        if payout_fraction is None and commission_percent is not None:
            payout_fraction = 1.0 - commission_percent / 100.0
        if payout_fraction is not None and not 0.0 <= payout_fraction <= 2.0:
            return
        observed = server_at_receive or received_at
        bucket = observed // interval_ms * interval_ms
        clock_offset = (
            server_at_receive - received_at
            if server_at_receive is not None
            else None
        )
        self.connection.execute(
            """
            INSERT OR REPLACE INTO payout_samples (
                canonical_asset, broker_asset, instrument_type,
                observed_bucket_ms, received_at_ms, server_at_receive_ms,
                clock_offset_ms, commission_percent, payout_fraction, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical,
                broker,
                instrument_type,
                bucket,
                received_at,
                server_at_receive,
                clock_offset,
                commission_percent,
                payout_fraction,
                source,
            ),
        )

    def insert_deal(self, event: Mapping[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO live_deal_events (
                event_hash, canonical_asset, broker_asset, instrument_type,
                expiration_type, direction, amount, event_time_ms,
                expiration_ms, received_at_ms, server_at_receive_ms,
                clock_offset_ms, receive_latency_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_hash"],
                event["canonical_asset"],
                event["broker_asset"],
                event["instrument_type"],
                event.get("expiration_type"),
                event["direction"],
                event.get("amount"),
                event.get("event_time_ms"),
                event.get("expiration_ms"),
                event["received_at_ms"],
                event.get("server_at_receive_ms"),
                event.get("clock_offset_ms"),
                event.get("receive_latency_ms"),
            ),
        )

    def insert_clock(
        self,
        interval_ms: int,
        received_at: int,
        server_at_receive: Optional[int],
        connected: bool,
    ) -> None:
        if server_at_receive is None:
            return
        bucket = server_at_receive // interval_ms * interval_ms
        self.connection.execute(
            """
            INSERT OR REPLACE INTO clock_samples (
                observed_bucket_ms, received_at_ms, server_at_receive_ms,
                clock_offset_ms, websocket_connected
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                bucket,
                received_at,
                server_at_receive,
                server_at_receive - received_at,
                int(connected),
            ),
        )

    def insert_health(
        self,
        interval_ms: int,
        received_at: int,
        connected: bool,
        assets_subscribed: int,
        queued_deals: int,
        last_quote_age_ms: Optional[int],
        note: Optional[str] = None,
    ) -> None:
        bucket = received_at // interval_ms * interval_ms
        self.connection.execute(
            """
            INSERT OR REPLACE INTO collection_health (
                observed_bucket_ms, received_at_ms, websocket_connected,
                assets_subscribed, queued_deals, last_quote_age_ms, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bucket,
                received_at,
                int(connected),
                assets_subscribed,
                queued_deals,
                last_quote_age_ms,
                note,
            ),
        )

    def commit(self) -> None:
        self.connection.commit()


def infer_direction(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("direction", "instrument_dir", "instrument_direction"):
        value = str(payload.get(key, "")).strip().lower()
        if value in VALID_DIRECTIONS:
            return value
        if value in {"higher", "buy", "c"}:
            return "call"
        if value in {"lower", "sell", "p"}:
            return "put"
    return None


def first_value(payload: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def sanitize_live_deal(
    payload: Mapping[str, Any],
    instrument_type: str,
    canonical_by_broker: Mapping[str, str],
    server_at_receive_ms: Optional[int],
    received_at_ms: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Extract model-safe fields and irreversibly discard personal metadata."""
    received = received_at_ms or utc_ms()
    broker = str(payload.get("active", "")).strip().upper()
    direction = infer_direction(payload)
    canonical = canonical_by_broker.get(broker)
    if not broker or canonical is None or direction is None:
        return None

    amount = finite_float(first_value(payload, ("amount_enrolled", "amount")))
    if amount is not None and amount < 0:
        amount = None

    event_time = normalize_epoch_ms(
        first_value(
            payload,
            ("created_at", "created", "at", "timestamp", "open_time"),
        )
    )
    expiration = normalize_epoch_ms(
        first_value(
            payload,
            ("expiration", "expiration_time", "expired_at"),
        )
    )
    expiration_type = first_value(
        payload,
        ("expiration_type", "option_type", "instrument_type"),
    )
    if expiration_type is not None:
        expiration_type = str(expiration_type)

    # Source transaction/user identifiers are used only inside a digest to
    # avoid collapsing two otherwise-identical events.  They are never stored.
    digest_material = {
        "broker": broker,
        "instrument_type": instrument_type,
        "direction": direction,
        "amount": amount,
        "event_time": event_time,
        "expiration": expiration,
        "expiration_type": expiration_type,
        "source_id": first_value(
            payload,
            ("id", "option_id", "position_id", "user_id"),
        ),
    }
    event_hash = hashlib.sha256(
        json.dumps(digest_material, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    clock_offset = (
        server_at_receive_ms - received
        if server_at_receive_ms is not None
        else None
    )
    latency_clock = server_at_receive_ms or received
    latency = latency_clock - event_time if event_time is not None else None
    if latency is not None and abs(latency) > 24 * 60 * 60 * 1_000:
        latency = None

    return {
        "event_hash": event_hash,
        "canonical_asset": canonical,
        "broker_asset": broker,
        "instrument_type": instrument_type,
        "expiration_type": expiration_type,
        "direction": direction,
        "amount": amount,
        "event_time_ms": event_time,
        "expiration_ms": expiration,
        "received_at_ms": received,
        "server_at_receive_ms": server_at_receive_ms,
        "clock_offset_ms": clock_offset,
        "receive_latency_ms": latency,
    }


def connect_api(retries: int, account_type: str) -> IQ_Option:
    load_dotenv(PROJECT_ROOT / ".env")
    email = os.environ.get("IQ_EMAIL")
    password = os.environ.get("IQ_PASSWORD")
    if not email or not password:
        raise RuntimeError("IQ_EMAIL and IQ_PASSWORD must be set in .env")

    api = IQ_Option(email, password)
    last_reason: Any = None
    for attempt in range(1, retries + 1):
        connected, reason = api.connect()
        if connected and api.check_connect():
            api.change_balance(account_type)
            LOGGER.info("Connected to IQ Option (%s)", account_type)
            return api
        last_reason = reason
        LOGGER.warning(
            "Connection attempt %d/%d failed: %s",
            attempt,
            retries,
            reason,
        )
        time.sleep(min(2**attempt, 10))
    raise RuntimeError(f"Could not connect to IQ Option: {last_reason}")


def backfill_history(
    api: IQ_Option,
    store: MarketStore,
    assets: Mapping[str, str],
    history_days: int,
    timeframes: Iterable[int],
    chunk_size: int,
) -> None:
    end_now = int(api.get_server_timestamp() or time.time())
    start_time = end_now - history_days * 86_400
    for canonical, broker in assets.items():
        for timeframe in timeframes:
            cursor_end = end_now
            total = 0
            LOGGER.info(
                "Backfilling %s (%s), %ss for %d days",
                canonical,
                broker,
                timeframe,
                history_days,
            )
            while cursor_end > start_time:
                candles = api.get_candles(
                    broker,
                    int(timeframe),
                    int(chunk_size),
                    int(cursor_end),
                )
                if not candles:
                    LOGGER.warning(
                        "No candles returned for %s/%ss at %s",
                        broker,
                        timeframe,
                        cursor_end,
                    )
                    break
                oldest = min(
                    int(candle["from"])
                    for candle in candles
                    if candle.get("from") is not None
                )
                total += store.insert_historical(
                    canonical,
                    broker,
                    timeframe,
                    candles,
                )
                LOGGER.info(
                    "  %s/%ss: %d rows; reached %s",
                    broker,
                    timeframe,
                    total,
                    datetime.fromtimestamp(oldest, tz=timezone.utc).isoformat(),
                )
                if oldest >= cursor_end:
                    LOGGER.warning("Backfill cursor stopped moving; ending segment")
                    break
                cursor_end = oldest - 1
                time.sleep(0.5)


@dataclass
class LiveConfig:
    poll_seconds: float
    mood_interval_ms: int
    payout_interval_ms: int
    health_interval_ms: int
    clock_interval_ms: int
    stream_buffer: int
    live_timeframes: tuple[int, ...]
    include_binary_deals: bool
    include_digital_deals: bool
    run_seconds: int


class LiveCollector:
    def __init__(
        self,
        api: IQ_Option,
        store: MarketStore,
        assets: Mapping[str, str],
        config: LiveConfig,
        account_type: str,
        reconnect_retries: int,
    ):
        self.api = api
        self.store = store
        self.assets = dict(assets)
        self.canonical_by_broker: dict[str, str] = {}
        self.stream_keys_by_broker: dict[str, tuple[str, ...]] = {}
        for canonical, broker in self.assets.items():
            active_id = OP_code.ACTIVES[broker]
            aliases = tuple(
                str(name).upper()
                for name, opcode in OP_code.ACTIVES.items()
                if opcode == active_id
            )
            self.stream_keys_by_broker[broker] = tuple(
                dict.fromkeys((broker, *aliases))
            )
            for alias in self.stream_keys_by_broker[broker]:
                self.canonical_by_broker[alias] = canonical
        self.config = config
        self.account_type = account_type
        self.reconnect_retries = reconnect_retries
        self.stop_event = threading.Event()
        self.deal_queue: queue.Queue[tuple[str, dict[str, Any], int, Optional[int]]]
        self.deal_queue = queue.Queue(maxsize=100_000)
        self.seen_candle_fingerprints: dict[tuple[str, int, int], tuple[Any, ...]] = {}
        self.seen_commissions: set[tuple[str, str, int, float]] = set()
        self.last_quote_event_ms: Optional[int] = None
        self.last_health_ms = 0
        self.last_mood_ms = 0
        self.last_clock_ms = 0
        self.last_payout_bootstrap_ms = 0
        self.payout_worker: Optional[threading.Thread] = None
        self.payout_results: queue.Queue[tuple[int, Optional[int], Any]]
        self.payout_results = queue.Queue(maxsize=1)

    def request_stop(self, *_: Any) -> None:
        self.stop_event.set()

    def _deal_callback(self, instrument_type: str):
        def callback(**payload: Any) -> None:
            received = utc_ms()
            server_ms = broker_server_ms(self.api)
            try:
                self.deal_queue.put_nowait(
                    (instrument_type, dict(payload), received, server_ms)
                )
            except queue.Full:
                LOGGER.warning("Live-deal queue full; dropping an event")

        return callback

    def subscribe(self) -> None:
        """Subscribe without the wrapper's blocking historical warm-up loops."""
        self.api.set_binary_live_deal_cb(
            self._deal_callback("binary-option")
        )
        self.api.set_digital_live_deal_cb(
            self._deal_callback("digital-option")
        )

        for instrument in ("turbo-option", "binary-option", "digital-option"):
            try:
                self.api.subscribe_commission_changed(instrument)
            except Exception as exc:
                LOGGER.warning(
                    "Commission subscription failed for %s: %s",
                    instrument,
                    exc,
                )

        for canonical, broker in self.assets.items():
            active_id = OP_code.ACTIVES[broker]

            # The all-size message includes broker event time, bid, and ask.
            # Pre-initialize every advertised size because the receiver writes
            # all sizes from a single message.
            for size in self.api.size:
                self.api.api.real_time_candles_maxdict_table[broker][size] = (
                    self.config.stream_buffer
                )
            try:
                self.api.api.subscribe_all_size(active_id)
            except Exception as exc:
                LOGGER.warning("Candle subscription failed for %s: %s", broker, exc)

            try:
                self.api.api.subscribe_Traders_mood(active_id, "turbo-option")
            except Exception as exc:
                LOGGER.warning("Mood subscription failed for %s: %s", broker, exc)

            if self.config.include_binary_deals:
                for option_type in ("turbo", "binary"):
                    try:
                        self.api.subscribe_live_deal(
                            "live-deal-binary-option-placed",
                            broker,
                            option_type,
                            1,
                        )
                    except Exception as exc:
                        LOGGER.warning(
                            "Binary live-deal subscription failed for %s/%s: %s",
                            broker,
                            option_type,
                            exc,
                        )

            if self.config.include_digital_deals:
                for expiration_type in ("PT1M", "PT5M", "PT15M"):
                    try:
                        self.api.subscribe_live_deal(
                            "live-deal-digital-option",
                            broker,
                            expiration_type,
                            1,
                        )
                    except Exception as exc:
                        LOGGER.warning(
                            "Digital live-deal subscription failed for %s/%s: %s",
                            broker,
                            expiration_type,
                            exc,
                        )
            LOGGER.info("Subscribed %s using broker symbol %s", canonical, broker)

    def unsubscribe(self) -> None:
        for _, broker in self.assets.items():
            active_id = OP_code.ACTIVES.get(broker)
            if active_id is None:
                continue
            try:
                self.api.api.unsubscribe_all_size(active_id)
                self.api.api.unsubscribe_Traders_mood(
                    active_id,
                    "turbo-option",
                )
            except Exception:
                pass
            if self.config.include_binary_deals:
                for option_type in ("turbo", "binary"):
                    try:
                        self.api.unscribe_live_deal(
                            "live-deal-binary-option-placed",
                            broker,
                            option_type,
                        )
                    except Exception:
                        pass
            if self.config.include_digital_deals:
                for expiration_type in ("PT1M", "PT5M", "PT15M"):
                    try:
                        self.api.unscribe_live_deal(
                            "live-deal-digital-option",
                            broker,
                            expiration_type,
                        )
                    except Exception:
                        pass
        for instrument in ("turbo-option", "binary-option", "digital-option"):
            try:
                self.api.unsubscribe_commission_changed(instrument)
            except Exception:
                pass

    def _poll_candles(self, received: int, server_ms: Optional[int]) -> int:
        written = 0
        for canonical, broker in self.assets.items():
            try:
                # Read the wrapper's in-memory stream directly.  The public
                # getter logs an error on every poll until its first message.
                all_sizes: Mapping[Any, Any] = {}
                for stream_key in self.stream_keys_by_broker[broker]:
                    candidate = self.api.api.real_time_candles.get(stream_key, {})
                    if isinstance(candidate, Mapping) and candidate:
                        all_sizes = candidate
                        break
                if not isinstance(all_sizes, Mapping):
                    continue
                sizes_snapshot = list(all_sizes.items())
            except (RuntimeError, TypeError):
                continue

            for raw_size, raw_candles in sizes_snapshot:
                try:
                    size = int(raw_size)
                except (TypeError, ValueError):
                    continue
                if size not in self.config.live_timeframes:
                    continue
                try:
                    candle_snapshot = list(dict(raw_candles).items())
                except (TypeError, RuntimeError):
                    continue
                for raw_start, candle in candle_snapshot:
                    if not isinstance(candle, Mapping):
                        continue
                    start_ms = normalize_epoch_ms(candle.get("from", raw_start))
                    if start_ms is None:
                        continue
                    fingerprint = (
                        candle.get("at"),
                        candle.get("open"),
                        candle.get("max"),
                        candle.get("min"),
                        candle.get("close", candle.get("value")),
                        candle.get("volume"),
                        candle.get("bid"),
                        candle.get("ask"),
                    )
                    key = (broker, size, start_ms)
                    if self.seen_candle_fingerprints.get(key) == fingerprint:
                        continue
                    self.seen_candle_fingerprints[key] = fingerprint
                    if self.store.upsert_realtime(
                        canonical,
                        broker,
                        size,
                        candle,
                        received,
                        server_ms,
                    ):
                        written += 1
                        event_ms = normalize_epoch_ms(candle.get("at"))
                        if event_ms is not None:
                            self.last_quote_event_ms = event_ms

        # Keep only recent fingerprints; the wrapper already bounds its cache.
        if len(self.seen_candle_fingerprints) > 50_000:
            cutoff = received - 86_400_000
            self.seen_candle_fingerprints = {
                key: value
                for key, value in self.seen_candle_fingerprints.items()
                if key[2] >= cutoff
            }
        return written

    def _poll_mood(self, received: int, server_ms: Optional[int]) -> None:
        if received - self.last_mood_ms < self.config.mood_interval_ms:
            return
        self.last_mood_ms = received
        for canonical, broker in self.assets.items():
            try:
                value = finite_float(self.api.get_traders_mood(broker))
            except Exception:
                value = None
            if value is not None:
                self.store.insert_mood(
                    canonical,
                    broker,
                    "turbo-option",
                    self.config.mood_interval_ms,
                    value,
                    received,
                    server_ms,
                )

    def _poll_commissions(self, received: int, server_ms: Optional[int]) -> None:
        for instrument in ("turbo-option", "binary-option", "digital-option"):
            try:
                instrument_data = self.api.get_commission_change(instrument)
                snapshot = list(dict(instrument_data).items())
            except (TypeError, RuntimeError, KeyError):
                continue
            for broker, timestamp_map in snapshot:
                canonical = self.canonical_by_broker.get(str(broker).upper())
                if canonical is None:
                    continue
                try:
                    values = list(dict(timestamp_map).items())
                except (TypeError, RuntimeError):
                    continue
                for raw_timestamp, raw_commission in values:
                    timestamp_ms = normalize_epoch_ms(raw_timestamp)
                    commission = finite_float(raw_commission)
                    if timestamp_ms is None or commission is None:
                        continue
                    key = (instrument, broker, timestamp_ms, commission)
                    if key in self.seen_commissions:
                        continue
                    self.seen_commissions.add(key)
                    self.store.insert_payout(
                        canonical,
                        broker,
                        instrument,
                        self.config.payout_interval_ms,
                        received,
                        timestamp_ms,
                        "commission-stream",
                        commission_percent=commission,
                    )

    def _start_payout_bootstrap(self, received: int) -> None:
        if received - self.last_payout_bootstrap_ms < self.config.payout_interval_ms:
            return
        if self.payout_worker is not None and self.payout_worker.is_alive():
            return
        self.last_payout_bootstrap_ms = received

        def worker() -> None:
            server_ms = broker_server_ms(self.api)
            try:
                result: Any = self.api.get_all_profit()
            except Exception as exc:
                result = exc
            try:
                self.payout_results.put_nowait((utc_ms(), server_ms, result))
            except queue.Full:
                pass

        self.payout_worker = threading.Thread(
            target=worker,
            name="payout-snapshot",
            daemon=True,
        )
        self.payout_worker.start()

    def _drain_payout_bootstrap(self) -> None:
        try:
            received, server_ms, result = self.payout_results.get_nowait()
        except queue.Empty:
            return
        if isinstance(result, Exception):
            LOGGER.warning("Payout bootstrap failed: %s", result)
            return
        if not isinstance(result, Mapping):
            return
        for broker, instrument_values in result.items():
            canonical = self.canonical_by_broker.get(str(broker).upper())
            if canonical is None or not isinstance(instrument_values, Mapping):
                continue
            for wrapper_type, raw_payout in instrument_values.items():
                payout = finite_float(raw_payout)
                if payout is None:
                    continue
                instrument = {
                    "turbo": "turbo-option",
                    "binary": "binary-option",
                    "digital": "digital-option",
                }.get(str(wrapper_type), str(wrapper_type))
                self.store.insert_payout(
                    canonical,
                    str(broker).upper(),
                    instrument,
                    self.config.payout_interval_ms,
                    received,
                    server_ms,
                    "init-snapshot",
                    payout_fraction=payout,
                )

    def _drain_deals(self, limit: int = 10_000) -> int:
        inserted = 0
        for _ in range(limit):
            try:
                instrument, payload, received, server_ms = (
                    self.deal_queue.get_nowait()
                )
            except queue.Empty:
                break
            event = sanitize_live_deal(
                payload,
                instrument,
                self.canonical_by_broker,
                server_ms,
                received,
            )
            if event is not None:
                self.store.insert_deal(event)
                inserted += 1
        return inserted

    def _record_health(self, received: int, server_ms: Optional[int]) -> None:
        if received - self.last_clock_ms >= self.config.clock_interval_ms:
            self.last_clock_ms = received
            self.store.insert_clock(
                self.config.clock_interval_ms,
                received,
                server_ms,
                self.api.check_connect(),
            )
        if received - self.last_health_ms >= self.config.health_interval_ms:
            self.last_health_ms = received
            quote_age = (
                max(0, (server_ms or received) - self.last_quote_event_ms)
                if self.last_quote_event_ms is not None
                else None
            )
            self.store.insert_health(
                self.config.health_interval_ms,
                received,
                self.api.check_connect(),
                len(self.assets),
                self.deal_queue.qsize(),
                quote_age,
            )
            LOGGER.info(
                "health connected=%s assets=%d deal_queue=%d quote_age_ms=%s",
                self.api.check_connect(),
                len(self.assets),
                self.deal_queue.qsize(),
                quote_age,
            )

    def _reconnect(self) -> None:
        LOGGER.warning("Websocket disconnected; reconnecting collector")
        self.api = connect_api(self.reconnect_retries, self.account_type)
        self.seen_candle_fingerprints.clear()
        self.seen_commissions.clear()
        self.subscribe()

    def run(self) -> None:
        self.subscribe()
        started = time.monotonic()
        last_commit = time.monotonic()
        try:
            while not self.stop_event.is_set():
                if (
                    self.config.run_seconds > 0
                    and time.monotonic() - started >= self.config.run_seconds
                ):
                    break
                if not self.api.check_connect():
                    self._reconnect()

                received = utc_ms()
                server_ms = broker_server_ms(self.api)
                self._poll_candles(received, server_ms)
                self.store.finalize_due_realtime_candles(
                    server_ms or received
                )
                self._poll_mood(received, server_ms)
                self._poll_commissions(received, server_ms)
                self._start_payout_bootstrap(received)
                self._drain_payout_bootstrap()
                self._drain_deals()
                self._record_health(received, server_ms)

                if time.monotonic() - last_commit >= 2.0:
                    self.store.commit()
                    last_commit = time.monotonic()
                self.stop_event.wait(self.config.poll_seconds)
        finally:
            self._drain_deals()
            self.store.commit()
            self.unsubscribe()


def run_self_test(db_path: Path) -> None:
    if db_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing self-test database: {db_path}"
        )
    store = MarketStore(db_path)
    now = utc_ms()
    candle = {
        "from": (now // 120_000) * 120,
        "at": now,
        "open": 1.1,
        "max": 1.2,
        "min": 1.0,
        "close": 1.15,
        "volume": 42,
        "bid": 1.149,
        "ask": 1.151,
    }
    assert store.upsert_realtime(
        "EURUSD-OTC",
        "EURUSD-OTC",
        120,
        candle,
        now + 5,
        now,
    )
    store.insert_mood(
        "EURUSD-OTC",
        "EURUSD-OTC",
        "turbo-option",
        5_000,
        0.61,
        now,
        now - 2,
    )
    store.insert_payout(
        "EURUSD-OTC",
        "EURUSD-OTC",
        "turbo-option",
        60_000,
        now,
        now - 2,
        "self-test",
        payout_fraction=0.82,
    )
    raw_deal = {
        "active": "EURUSD-OTC",
        "direction": "call",
        "amount_enrolled": 10,
        "created_at": now,
        "expiration": now + 120_000,
        "user_id": 123456,  # used only inside the digest
        "name": "must-not-be-stored",
        "country_id": 999,
    }
    event = sanitize_live_deal(
        raw_deal,
        "binary-option",
        {"EURUSD-OTC": "EURUSD-OTC"},
        now + 2,
        now + 5,
    )
    assert event is not None
    assert "user_id" not in event and "name" not in event and "country_id" not in event
    store.insert_deal(event)
    store.commit()

    expected = {
        "realtime_candles": 1,
        "quote_samples": 1,
        "mood_samples": 1,
        "payout_samples": 1,
        "live_deal_events": 1,
        "deal_flow_10s": 1,
    }
    for table, count in expected.items():
        actual = store.connection.execute(
            f"SELECT COUNT(*) FROM {table}"  # table names are fixed above
        ).fetchone()[0]
        assert actual == count, f"{table}: expected {count}, got {actual}"
    columns = {
        row[1]
        for row in store.connection.execute(
            "PRAGMA table_info(live_deal_events)"
        )
    }
    assert not {"user_id", "name", "country_id", "raw_json"} & columns
    store.close()
    LOGGER.info("Self-test passed: %s", db_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone IQ Option market-context research harvester"
    )
    parser.add_argument(
        "--mode",
        choices=("live", "backfill", "both"),
        default="live",
        help="Collection mode (default: live)",
    )
    parser.add_argument("--assets", default=DEFAULT_ASSETS)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--history-days", type=int, default=30)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument(
        "--history-timeframes",
        default="120,300,900",
        help="Comma-separated seconds",
    )
    parser.add_argument(
        "--live-timeframes",
        default="1,120,300,900",
        help="Live sizes retained from the all-size broker stream",
    )
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument("--mood-interval-seconds", type=float, default=5.0)
    parser.add_argument("--payout-interval-seconds", type=float, default=300.0)
    parser.add_argument("--health-interval-seconds", type=float, default=30.0)
    parser.add_argument("--clock-interval-seconds", type=float, default=10.0)
    parser.add_argument("--stream-buffer", type=int, default=10)
    parser.add_argument(
        "--run-seconds",
        type=int,
        default=0,
        help="Zero runs until interrupted",
    )
    parser.add_argument(
        "--account-type",
        choices=("PRACTICE", "REAL"),
        default="PRACTICE",
        help="Authentication profile only; this script never trades",
    )
    parser.add_argument("--connect-retries", type=int, default=5)
    parser.add_argument(
        "--no-binary-deals",
        action="store_true",
        help="Disable public binary/turbo live-deal flow",
    )
    parser.add_argument(
        "--digital-deals",
        action="store_true",
        help="Also collect public PT1M/PT5M/PT15M digital live-deal flow",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Validate schema and sanitization without connecting",
    )
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def positive_csv_ints(raw: str) -> tuple[int, ...]:
    values = tuple(
        sorted({int(item.strip()) for item in raw.split(",") if item.strip()})
    )
    if not values or any(value <= 0 for value in values):
        raise ValueError("timeframes must be positive integers")
    return values


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.self_test:
        test_path = (
            args.db
            if args.db != DEFAULT_DB
            else Path(
                "/tmp/iqoption_market_harvester_selftest_"
                f"{os.getpid()}_{time.time_ns()}.sqlite"
            )
        )
        run_self_test(test_path.resolve())
        return 0

    if args.history_days <= 0:
        raise ValueError("--history-days must be positive")
    if not 1 <= args.chunk_size <= 1000:
        raise ValueError("--chunk-size must be in [1, 1000]")
    if args.poll_seconds < 0.05:
        raise ValueError("--poll-seconds must be at least 0.05")
    for name in (
        "mood_interval_seconds",
        "payout_interval_seconds",
        "health_interval_seconds",
        "clock_interval_seconds",
    ):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be positive")
    if args.stream_buffer <= 0:
        raise ValueError("--stream-buffer must be positive")

    requested = [
        item.strip().upper()
        for item in args.assets.split(",")
        if item.strip()
    ]
    api = connect_api(args.connect_retries, args.account_type)
    assets = resolve_assets(requested)
    if not assets:
        raise RuntimeError("None of the requested assets exist in the opcode table")
    LOGGER.info(
        "Resolved %d/%d assets: %s",
        len(assets),
        len(requested),
        ", ".join(f"{canonical}->{broker}" for canonical, broker in assets.items()),
    )

    store = MarketStore(args.db.resolve())
    collector: Optional[LiveCollector] = None
    try:
        if args.mode in {"backfill", "both"}:
            backfill_history(
                api,
                store,
                assets,
                args.history_days,
                positive_csv_ints(args.history_timeframes),
                args.chunk_size,
            )
        if args.mode in {"live", "both"}:
            config = LiveConfig(
                poll_seconds=args.poll_seconds,
                mood_interval_ms=int(args.mood_interval_seconds * 1_000),
                payout_interval_ms=int(args.payout_interval_seconds * 1_000),
                health_interval_ms=int(args.health_interval_seconds * 1_000),
                clock_interval_ms=int(args.clock_interval_seconds * 1_000),
                stream_buffer=args.stream_buffer,
                live_timeframes=positive_csv_ints(args.live_timeframes),
                include_binary_deals=not args.no_binary_deals,
                include_digital_deals=args.digital_deals,
                run_seconds=args.run_seconds,
            )
            collector = LiveCollector(
                api,
                store,
                assets,
                config,
                args.account_type,
                args.connect_retries,
            )
            signal.signal(signal.SIGINT, collector.request_stop)
            signal.signal(signal.SIGTERM, collector.request_stop)
            collector.run()
    finally:
        store.close()
        try:
            api.api.close()
        except Exception:
            pass
    LOGGER.info("Collector stopped cleanly; database: %s", args.db.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
