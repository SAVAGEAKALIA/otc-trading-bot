"""Persistent paper outcomes for scanner-candidate meta-label research."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "item"):
        return _plain(value.item())
    return str(value)


def _value(candle: dict, *keys: str) -> Optional[float]:
    for key in keys:
        if key in candle and candle[key] is not None:
            try:
                return float(candle[key])
            except (TypeError, ValueError):
                return None
    return None


def _timestamp(candle: dict) -> Optional[int]:
    value = _value(candle, "at", "from", "time", "timestamp")
    if value is None:
        return None
    while value > 5_000_000_000:
        value /= 1000.0
    return int(value)


class CandidateResearchLogger:
    """Collect candidates and resolve broker-candle paper outcomes."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: Optional[str] = None,
        enabled: Optional[bool] = None,
        candle_seconds: int = 120,
    ) -> None:
        if enabled is None:
            enabled = os.getenv(
                "CANDIDATE_RESEARCH_ENABLED", "true"
            ).strip().lower() in {"1", "true", "yes", "on"}
        self.enabled = bool(enabled)
        self.path = Path(
            path
            or os.getenv(
                "CANDIDATE_RESEARCH_DB",
                "data/candidate_research.sqlite",
            )
        )
        self.candle_seconds = int(candle_seconds)
        self._lock = threading.RLock()
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()
            print(f"   🧪 Candidate research ledger: {self.path}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schema_version INTEGER NOT NULL,
                    candidate_key TEXT NOT NULL UNIQUE,
                    asset TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    decision_time INTEGER NOT NULL,
                    expiry_time INTEGER NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    strategy TEXT,
                    score REAL,
                    confidence REAL,
                    confluence INTEGER,
                    regime TEXT,
                    features_json TEXT NOT NULL,
                    entry_price REAL,
                    settlement_price REAL,
                    outcome TEXT,
                    label INTEGER,
                    created_at INTEGER NOT NULL,
                    resolved_at INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidates_pending
                ON candidates(asset, outcome, expiry_time)
                """
            )

    def record_candidate(
        self,
        *,
        asset: str,
        direction: str,
        completed_candles: Iterable[dict],
        duration_minutes: int,
        strategy: str,
        score: float,
        confidence: float,
        confluence: int,
        regime: Optional[str],
        features: Dict[str, Any],
    ) -> Optional[str]:
        if not self.enabled:
            return None
        candles = [item for item in completed_candles if isinstance(item, dict)]
        if not candles or direction.lower() not in {"call", "put"}:
            return None
        last_start = _timestamp(candles[-1])
        if last_start is None:
            return None
        decision_time = last_start + self.candle_seconds
        duration = int(duration_minutes)
        if duration <= 0:
            return None
        expiry_time = decision_time + duration * 60
        normalized_asset = str(asset).upper()
        normalized_direction = direction.lower()
        normalized_strategy = str(strategy or "unknown")
        candidate_key = (
            f"{normalized_asset}|{decision_time}|{normalized_direction}|"
            f"{duration}|{normalized_strategy}"
        )
        payload = json.dumps(_plain(features), separators=(",", ":"))

        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO candidates (
                    schema_version, candidate_key, asset, direction,
                    decision_time, expiry_time, duration_minutes, strategy,
                    score, confidence, confluence, regime, features_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.SCHEMA_VERSION,
                    candidate_key,
                    normalized_asset,
                    normalized_direction,
                    decision_time,
                    expiry_time,
                    duration,
                    normalized_strategy,
                    float(score),
                    float(confidence),
                    int(confluence),
                    str(regime or "unknown"),
                    payload,
                    int(time.time()),
                ),
            )
        return candidate_key

    def resolve_pending(
        self, asset: str, completed_candles: Iterable[dict]
    ) -> int:
        """Resolve pending candidates only when exact candle boundaries exist."""
        if not self.enabled:
            return 0
        normalized = []
        for candle in completed_candles:
            if not isinstance(candle, dict):
                continue
            start = _timestamp(candle)
            open_price = _value(candle, "open", "o")
            close_price = _value(candle, "close", "c")
            if start is None or open_price is None or close_price is None:
                continue
            normalized.append((start, open_price, close_price))
        normalized.sort(key=lambda item: item[0])
        if not normalized:
            return 0
        by_start = {item[0]: item for item in normalized}
        latest_close = normalized[-1][0] + self.candle_seconds
        normalized_asset = str(asset).upper()

        with self._lock, self._connect() as connection:
            pending = connection.execute(
                """
                SELECT id, direction, decision_time, expiry_time
                FROM candidates
                WHERE asset = ? AND outcome IS NULL AND expiry_time <= ?
                ORDER BY expiry_time
                """,
                (normalized_asset, latest_close),
            ).fetchall()
            resolved = 0
            for row_id, direction, decision_time, expiry_time in pending:
                # The paper entry must be the open of the first candle after
                # the decision. Settlement must be an exact 2m boundary.
                if (expiry_time - decision_time) % self.candle_seconds:
                    continue
                entry_candle = by_start.get(decision_time)
                settlement_candle = by_start.get(
                    expiry_time - self.candle_seconds
                )
                if entry_candle is None or settlement_candle is None:
                    continue
                entry_price = entry_candle[1]
                settlement_price = settlement_candle[2]
                if settlement_price == entry_price:
                    outcome, label = "tie", None
                else:
                    call_won = settlement_price > entry_price
                    won = call_won if direction == "call" else not call_won
                    outcome, label = ("win", 1) if won else ("loss", 0)
                connection.execute(
                    """
                    UPDATE candidates
                    SET entry_price = ?, settlement_price = ?, outcome = ?,
                        label = ?, resolved_at = ?
                    WHERE id = ? AND outcome IS NULL
                    """,
                    (
                        entry_price,
                        settlement_price,
                        outcome,
                        label,
                        int(time.time()),
                        row_id,
                    ),
                )
                resolved += 1
        return resolved

    def counts(self) -> Dict[str, int]:
        if not self.enabled:
            return {}
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT COALESCE(outcome, 'pending'), COUNT(*)
                FROM candidates GROUP BY COALESCE(outcome, 'pending')
                """
            ).fetchall()
        return {str(name): int(count) for name, count in rows}

    def strategy_summary(self) -> list[Dict[str, Any]]:
        """Return paper outcome counts grouped by strategy."""
        if not self.enabled:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    COALESCE(strategy, 'unknown') AS strategy_name,
                    SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN outcome = 'tie' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN outcome IS NULL THEN 1 ELSE 0 END)
                FROM candidates
                GROUP BY COALESCE(strategy, 'unknown')
                ORDER BY
                    SUM(CASE WHEN outcome IN ('win', 'loss') THEN 1 ELSE 0 END)
                    DESC,
                    strategy_name
                """
            ).fetchall()
        return [
            {
                "strategy": str(strategy),
                "wins": int(wins or 0),
                "losses": int(losses or 0),
                "ties": int(ties or 0),
                "pending": int(pending or 0),
            }
            for strategy, wins, losses, ties, pending in rows
        ]
