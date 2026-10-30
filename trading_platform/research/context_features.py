"""Platform-owned causal market-context features for training and inference."""

from __future__ import annotations

import math
import sqlite3
import time
from contextlib import closing
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import pandas as pd


CONTEXT_SCHEMA_VERSION = "market_context_v2"

# Every missing value has an explicit companion flag.  The numeric defaults are
# therefore imputation values, not claims that the market was neutral.
CONTEXT_FEATURES = [
    "spread_bps",
    "quote_age_sec",
    "quote_missing",
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
    "deal_missing",
    "traders_mood",
    "mood_centered",
    "mood_age_sec",
    "mood_missing",
    "payout_fraction",
    "payout_breakeven",
    "payout_age_sec",
    "payout_missing",
    "context_complete",
]

# Backward-compatible aliases used by the current trainers.  New artifacts
# should select the explicit features above from metadata.
LEGACY_CONTEXT_ALIASES = ["spread", "deal_count", "call_ratio"]
ALL_CONTEXT_FEATURES = CONTEXT_FEATURES + LEGACY_CONTEXT_ALIASES


def canonical_asset(symbol: str) -> str:
    value = str(symbol).strip().upper().replace("_", "-")
    if value.endswith("-OP"):
        return f"{value[:-3]}-OTC"
    if not value.endswith("-OTC") and len(value) == 6:
        return f"{value}-OTC"
    return value


def epoch_ms(value: Any) -> Optional[int]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    if numeric < 100_000_000_000:
        numeric *= 1_000
    elif numeric >= 100_000_000_000_000_000:
        numeric /= 1_000_000
    elif numeric >= 100_000_000_000_000:
        numeric /= 1_000
    return int(numeric)


def candle_decision_ms(row: Mapping[str, Any], timeframe_sec: int = 120) -> int:
    raw = row.get("timestamp", row.get("from", row.get("time")))
    if isinstance(raw, pd.Timestamp):
        start = int(raw.timestamp() * 1_000)
    else:
        parsed = epoch_ms(raw)
        if parsed is None:
            raise ValueError("Candle has no valid timestamp")
        start = parsed
    return start + int(timeframe_sec) * 1_000


@dataclass(frozen=True)
class ContextPolicy:
    max_quote_age_ms: int = 10_000
    max_mood_age_ms: int = 60_000
    max_payout_age_ms: int = 900_000
    max_deal_feed_age_ms: int = 300_000
    deal_windows_ms: tuple[int, int, int] = (10_000, 30_000, 60_000)


def missing_context(policy: ContextPolicy) -> Dict[str, float]:
    result = {
        "spread_bps": 0.0,
        "quote_age_sec": policy.max_quote_age_ms / 1_000.0,
        "quote_missing": 1.0,
        "deal_count_10s": 0.0,
        "deal_count_30s": 0.0,
        "deal_count_60s": 0.0,
        "deal_count_log_60s": 0.0,
        "call_ratio_10s": 0.5,
        "call_ratio_30s": 0.5,
        "call_ratio_60s": 0.5,
        "call_amount_ratio_60s": 0.5,
        "deal_flow_imbalance_60s": 0.0,
        "deal_amount_imbalance_60s": 0.0,
        "deal_feed_age_sec": policy.max_deal_feed_age_ms / 1_000.0,
        "deal_missing": 1.0,
        "traders_mood": 0.5,
        "mood_centered": 0.0,
        "mood_age_sec": policy.max_mood_age_ms / 1_000.0,
        "mood_missing": 1.0,
        "payout_fraction": 0.0,
        "payout_breakeven": 1.0,
        "payout_age_sec": policy.max_payout_age_ms / 1_000.0,
        "payout_missing": 1.0,
        "context_complete": 0.0,
    }
    result.update(
        spread=0.0,
        deal_count=0.0,
        call_ratio=0.5,
    )
    return result


class MarketContextProvider:
    """Read causally bounded context snapshots from the harvester database."""

    def __init__(
        self,
        db_path: str | Path = "data/ml/market_context.sqlite",
        policy: Optional[ContextPolicy] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.policy = policy or ContextPolicy()

    @property
    def available(self) -> bool:
        return self.db_path.is_file()

    def _connect(self) -> sqlite3.Connection:
        if not self.available:
            raise FileNotFoundError(self.db_path)
        uri = f"file:{self.db_path.resolve()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=1000")
        return connection

    def coverage(self) -> Dict[str, Any]:
        if not self.available:
            return {"available": False, "path": str(self.db_path)}
        tables = {
            "quotes": ("quote_samples", "source_event_ms"),
            "mood": ("mood_samples", "observed_bucket_ms"),
            "payout": ("payout_samples", "observed_bucket_ms"),
            "deals": (
                "live_deal_events",
                "COALESCE(event_time_ms, received_at_ms)",
            ),
        }
        result: Dict[str, Any] = {"available": True, "path": str(self.db_path)}
        with closing(self._connect()) as connection:
            for label, (table, timestamp) in tables.items():
                try:
                    row = connection.execute(
                        f"SELECT COUNT(*) AS n, MIN({timestamp}) AS first_ms, "
                        f"MAX({timestamp}) AS last_ms FROM {table}"
                    ).fetchone()
                    result[label] = {
                        "rows": int(row["n"] or 0),
                        "first_ms": row["first_ms"],
                        "last_ms": row["last_ms"],
                    }
                except sqlite3.Error as exc:
                    result[label] = {"rows": 0, "error": str(exc)}
        starts = [
            item.get("first_ms")
            for item in result.values()
            if isinstance(item, dict) and item.get("first_ms") is not None
        ]
        result["first_context_ms"] = min(starts) if starts else None
        return result

    @staticmethod
    def _latest(
        connection: sqlite3.Connection,
        query: str,
        parameters: Iterable[Any],
    ) -> Optional[sqlite3.Row]:
        return connection.execute(query, tuple(parameters)).fetchone()

    def snapshot(
        self,
        asset: str,
        decision_time_ms: Optional[int] = None,
    ) -> Dict[str, float]:
        decision = int(decision_time_ms or time.time_ns() // 1_000_000)
        # Return a copy so callers cannot mutate the cached snapshot.
        return dict(self._snapshot_cached(canonical_asset(asset), decision))

    @lru_cache(maxsize=20_000)
    def _snapshot_cached(
        self,
        normalized: str,
        decision: int,
    ) -> Dict[str, float]:
        result = missing_context(self.policy)
        if not self.available:
            return result

        try:
            with closing(self._connect()) as connection:
                quote = self._latest(
                    connection,
                    """
                    SELECT source_event_ms, bid, ask, mid, spread
                    FROM quote_samples
                    WHERE canonical_asset = ? AND source_event_ms <= ?
                    ORDER BY source_event_ms DESC LIMIT 1
                    """,
                    (normalized, decision),
                )
                if quote is not None:
                    age = max(0, decision - int(quote["source_event_ms"]))
                    mid = float(quote["mid"] or 0.0)
                    spread = float(quote["spread"] or 0.0)
                    if age <= self.policy.max_quote_age_ms and mid > 0:
                        result.update(
                            spread_bps=spread / mid * 10_000.0,
                            quote_age_sec=age / 1_000.0,
                            quote_missing=0.0,
                            spread=spread,
                        )

                mood = self._latest(
                    connection,
                    """
                    SELECT observed_bucket_ms, call_fraction
                    FROM mood_samples
                    WHERE canonical_asset = ? AND observed_bucket_ms <= ?
                    ORDER BY observed_bucket_ms DESC LIMIT 1
                    """,
                    (normalized, decision),
                )
                if mood is not None:
                    age = max(0, decision - int(mood["observed_bucket_ms"]))
                    value = float(mood["call_fraction"])
                    if age <= self.policy.max_mood_age_ms and 0.0 <= value <= 1.0:
                        result.update(
                            traders_mood=value,
                            mood_centered=2.0 * value - 1.0,
                            mood_age_sec=age / 1_000.0,
                            mood_missing=0.0,
                        )

                payout = self._latest(
                    connection,
                    """
                    SELECT observed_bucket_ms, payout_fraction
                    FROM payout_samples
                    WHERE canonical_asset = ?
                      AND instrument_type IN ('turbo-option', 'binary-option')
                      AND observed_bucket_ms <= ?
                      AND payout_fraction IS NOT NULL
                    ORDER BY observed_bucket_ms DESC LIMIT 1
                    """,
                    (normalized, decision),
                )
                if payout is not None:
                    age = max(0, decision - int(payout["observed_bucket_ms"]))
                    value = float(payout["payout_fraction"])
                    if age <= self.policy.max_payout_age_ms and 0.0 < value <= 2.0:
                        result.update(
                            payout_fraction=value,
                            payout_breakeven=1.0 / (1.0 + value),
                            payout_age_sec=age / 1_000.0,
                            payout_missing=0.0,
                        )

                latest_deal = self._latest(
                    connection,
                    """
                    SELECT MAX(COALESCE(event_time_ms, received_at_ms)) AS last_ms
                    FROM live_deal_events
                    WHERE canonical_asset = ?
                      AND COALESCE(event_time_ms, received_at_ms) <= ?
                    """,
                    (normalized, decision),
                )
                last_deal_ms = latest_deal["last_ms"] if latest_deal else None
                deal_feed_fresh = False
                if last_deal_ms is not None:
                    feed_age = max(0, decision - int(last_deal_ms))
                    result["deal_feed_age_sec"] = feed_age / 1_000.0
                    deal_feed_fresh = feed_age <= self.policy.max_deal_feed_age_ms
                    result["deal_missing"] = 0.0 if deal_feed_fresh else 1.0

                deal_rows = connection.execute(
                    """
                    SELECT direction, amount,
                           COALESCE(event_time_ms, received_at_ms) AS event_ms
                    FROM live_deal_events
                    WHERE canonical_asset = ?
                      AND COALESCE(event_time_ms, received_at_ms) > ?
                      AND COALESCE(event_time_ms, received_at_ms) <= ?
                    """,
                    (normalized, decision - 60_000, decision),
                ).fetchall()
                for window in self.policy.deal_windows_ms:
                    suffix = f"{window // 1_000}s"
                    selected = [
                        row for row in deal_rows
                        if int(row["event_ms"]) > decision - window
                    ]
                    calls = sum(str(row["direction"]).lower() == "call" for row in selected)
                    puts = sum(str(row["direction"]).lower() == "put" for row in selected)
                    count = calls + puts
                    result[f"deal_count_{suffix}"] = float(count)
                    result[f"call_ratio_{suffix}"] = calls / count if count else 0.5

                rows_60 = deal_rows
                call_amount = sum(
                    float(row["amount"] or 0.0)
                    for row in rows_60
                    if str(row["direction"]).lower() == "call"
                )
                put_amount = sum(
                    float(row["amount"] or 0.0)
                    for row in rows_60
                    if str(row["direction"]).lower() == "put"
                )
                total_amount = call_amount + put_amount
                call_ratio_60 = result["call_ratio_60s"]
                result.update(
                    deal_count_log_60s=math.log1p(result["deal_count_60s"]),
                    call_amount_ratio_60s=(
                        call_amount / total_amount if total_amount > 0 else 0.5
                    ),
                    deal_flow_imbalance_60s=2.0 * call_ratio_60 - 1.0,
                    deal_amount_imbalance_60s=(
                        (call_amount - put_amount) / total_amount
                        if total_amount > 0 else 0.0
                    ),
                    deal_count=result["deal_count_60s"],
                    call_ratio=call_ratio_60,
                )

                result["context_complete"] = float(
                    result["quote_missing"] == 0.0
                    and result["mood_missing"] == 0.0
                    and result["payout_missing"] == 0.0
                )
                if not deal_feed_fresh:
                    result["deal_missing"] = 1.0
        except (sqlite3.Error, OSError, ValueError):
            return missing_context(self.policy)
        return result

    def enrich_candles(
        self,
        frame: pd.DataFrame,
        asset: str,
        timeframe_sec: int = 120,
    ) -> pd.DataFrame:
        result = frame.copy()
        if result.empty:
            for feature in ALL_CONTEXT_FEATURES:
                result[feature] = pd.Series(dtype="float64")
            return result
        snapshots = []
        for row in result.to_dict("records"):
            snapshots.append(
                self.snapshot(
                    asset,
                    candle_decision_ms(row, timeframe_sec),
                )
            )
        context = pd.DataFrame(snapshots, index=result.index)
        for feature in ALL_CONTEXT_FEATURES:
            result[feature] = context[feature].astype(float)
        return result
