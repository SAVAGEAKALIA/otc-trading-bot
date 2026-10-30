"""
Trade logging with atomic file writes for crash safety.
"""

import os
import json
import tempfile
from typing import List, Optional
from datetime import datetime


class TradeLogger:
    """Handles trade logging, history, and statistics."""

    # Version 2 separates an auditable settlement record from a record that
    # is safe to use for sizing, calibration, or strategy-weight updates.
    # Older records are intentionally retained but never silently mixed into
    # the forward performance cohort.
    LEDGER_SCHEMA_VERSION = 2
    VERIFIED_RESULT_METHODS = frozenset({"api"})
    NEUTRAL_WIN_RATE = 0.50

    def __init__(self, log_file: str = "trade_log.json"):
        self.log_file = log_file
        self.trade_history: List[dict] = []
        self._load_history()

    def _load_history(self):
        """Load existing trade history from file."""
        try:
            with open(self.log_file, "r") as f:
                self.trade_history = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.trade_history = []

    def log_trade(self, asset: str, direction: str, duration: int, order_id: int,
                  amount: float, ai_confidence: float, reasoning: str,
                  source: str = "telegram", metadata: Optional[dict] = None) -> dict:
        """Log a new trade."""
        metadata = metadata or {}
        timestamp = datetime.now().isoformat()
        trade = {
            "timestamp": timestamp,
            "decision_time": metadata.get("decision_time", timestamp),
            "ledger_schema_version": self.LEDGER_SCHEMA_VERSION,
            "asset": asset,
            "direction": direction,
            "duration": duration,
            "order_id": order_id,
            "amount": amount,
            "ai_confidence": ai_confidence,
            "reasoning": reasoning,
            "source": source,
            # Decision-time fields are persisted explicitly so performance can
            # be analysed without parsing free-form reasoning text.
            "payout_rate": metadata.get("payout_rate"),
            "strategy_used": metadata.get("strategy_used", ""),
            "winning_strategy": metadata.get("winning_strategy", ""),
            "agreeing_strategies": metadata.get("agreeing_strategies", []),
            "quality_score": metadata.get("quality_score"),
            "regime": metadata.get("regime"),
            "martingale_step": metadata.get("martingale_step", 0),
            "martingale_series_id": metadata.get("martingale_series_id"),
            "result": None,
            "profit": None,
            "result_method": None,
            "settlement_verified": False,
            "performance_eligible": False,
        }

        self.trade_history.append(trade)
        self._save()

        return trade

    @classmethod
    def is_performance_eligible(cls, result: str,
                                result_method: Optional[str]) -> bool:
        """Return whether a result is trustworthy enough to train on."""
        return (
            result in {"win", "lose"}
            and (result_method or "").lower() in cls.VERIFIED_RESULT_METHODS
        )

    def update_result(self, order_id: int, result: str, profit: float,
                      result_method: Optional[str] = None):
        """Update trade result after expiration."""
        for trade in self.trade_history:
            if trade['order_id'] == order_id:
                normalized_method = (result_method or "").lower() or None
                trade['result'] = result
                trade['profit'] = profit
                trade['result_method'] = normalized_method
                trade['settlement_verified'] = (
                    normalized_method in self.VERIFIED_RESULT_METHODS
                )
                trade['performance_eligible'] = self.is_performance_eligible(
                    result, normalized_method
                )
                break
        self._save()

    def _save(self):
        """Persist the complete ledger using an atomic same-directory swap."""
        temp_path = None
        try:
            log_dir = os.path.dirname(os.path.abspath(self.log_file)) or "."
            os.makedirs(log_dir, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                dir=log_dir, prefix=".trade-log-", suffix=".tmp", text=True
            )
            def default_encoder(obj):
                if hasattr(obj, 'item'):
                    return obj.item()
                raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

            with os.fdopen(fd, "w") as f:
                json.dump(self.trade_history, f, indent=2, default=default_encoder)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.log_file)
        except Exception as e:
            print(f"⚠️ Error saving trade log: {e}")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @classmethod
    def _is_verified_performance_trade(cls, trade: dict) -> bool:
        """Filter records to the explicit versioned forward cohort."""
        return (
            trade.get("ledger_schema_version", 1) >= cls.LEDGER_SCHEMA_VERSION
            and trade.get("performance_eligible") is True
            and cls.is_performance_eligible(
                trade.get("result"), trade.get("result_method")
            )
        )

    def get_win_rate(self, last_n: int = 50) -> float:
        """
        Calculate win rate from recent trades.

        Args:
            last_n: Number of recent trades to consider

        Returns:
            Win rate as decimal (0.0-1.0)
        """
        completed = [
            t for t in self.trade_history
            if self._is_verified_performance_trade(t)
        ]

        if not completed:
            # Never turn unverified legacy outcomes into an assumed edge.
            return self.NEUTRAL_WIN_RATE

        recent = completed[-last_n:] if len(completed) > last_n else completed
        wins = len([t for t in recent if t['result'] == 'win'])

        return wins / len(recent) if recent else self.NEUTRAL_WIN_RATE

    def get_statistics(self) -> dict:
        """Calculate trading statistics."""
        if not self.trade_history:
            return {
                "total": 0, "wins": 0, "losses": 0, "ties": 0,
                "unknown": 0, "win_rate": 0, "total_profit": 0,
                "unverified_settled": 0, "excluded_settlements": 0,
                "pending": 0,
            }

        # ``unknown`` is an operational state, not a breakeven result. It
        # must remain observable without entering performance denominators.
        settled = [
            t for t in self.trade_history
            if t.get('result') in ('win', 'lose', 'tie')
        ]
        verified_settled = [
            t for t in settled
            if (
                t.get("ledger_schema_version", 1) >= self.LEDGER_SCHEMA_VERSION
                and t.get("settlement_verified") is True
            )
        ]
        completed = [t for t in settled if self._is_verified_performance_trade(t)]
        unverified_settled = len(settled) - len(verified_settled)
        unknown = len([t for t in self.trade_history if t.get('result') == 'unknown'])
        wins = len([t for t in completed if t['result'] == 'win'])
        losses = len([t for t in completed if t['result'] == 'lose'])
        ties = len([t for t in verified_settled if t['result'] == 'tie'])
        decided = wins + losses
        total_profit = sum(t.get('profit', 0) or 0 for t in completed)

        return {
            "total": len(verified_settled),
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "unknown": unknown,
            "win_rate": round((wins / decided * 100), 1) if decided else 0,
            "total_profit": round(total_profit, 2),
            "unverified_settled": unverified_settled,
            "excluded_settlements": len(settled) - len(completed),
            "pending": len([t for t in self.trade_history if t.get('result') is None]),
        }

    def print_statistics(self):
        """Print formatted statistics."""
        stats = self.get_statistics()
        print(f"\n📊 VERIFIED TRADING STATISTICS")
        print(f"   Total Trades: {stats['total']}")
        print(f"   Wins: {stats['wins']} | Losses: {stats['losses']}")
        print(f"   Win Rate: {stats['win_rate']}%")
        print(f"   Total Profit: ${stats['total_profit']:.2f}")

    def get_breakdown_stats(self) -> dict:
        """
        Get win rate breakdown by asset, source, and duration.

        Returns dict with keys: 'by_asset', 'by_source', 'by_duration'
        Each maps to a dict of { key: { total, wins, win_rate, profit } }
        """
        completed = [
            t for t in self.trade_history
            if self._is_verified_performance_trade(t)
        ]
        if not completed:
            return {'by_asset': {}, 'by_source': {}, 'by_duration': {}}

        def _bucket(trades, key_fn):
            buckets = {}
            for t in trades:
                k = key_fn(t)
                if k not in buckets:
                    buckets[k] = {'total': 0, 'wins': 0, 'profit': 0.0}
                buckets[k]['total'] += 1
                if t['result'] == 'win':
                    buckets[k]['wins'] += 1
                buckets[k]['profit'] += float(t.get('profit', 0) or 0)
            # Add win_rate
            for v in buckets.values():
                v['win_rate'] = round(v['wins'] / v['total'] * 100, 1) if v['total'] > 0 else 0.0
                v['profit'] = round(v['profit'], 2)
            return buckets

        return {
            'by_asset': _bucket(completed, lambda t: t.get('asset', 'unknown')),
            'by_source': _bucket(completed, lambda t: t.get('source', 'telegram')),
            'by_duration': _bucket(completed, lambda t: f"{t.get('duration', '?')}m"),
        }

    def get_verified_asset_performance(self, source: Optional[str] = None) -> dict:
        """Return verified win/loss counts, optionally for one execution source."""
        records = [
            trade for trade in self.trade_history
            if self._is_verified_performance_trade(trade)
            and (source is None or trade.get("source") == source)
        ]
        buckets = {}
        for trade in records:
            asset = trade.get("asset", "unknown")
            bucket = buckets.setdefault(asset, {"wins": 0, "losses": 0, "total": 0})
            bucket["total"] += 1
            if trade.get("result") == "win":
                bucket["wins"] += 1
            else:
                bucket["losses"] += 1
        return buckets

    def format_breakdown(self) -> str:
        """Format breakdown stats for Telegram display."""
        bd = self.get_breakdown_stats()
        if not bd['by_asset'] and not bd['by_source']:
            return "📊 *Verified Breakdown*\n\nNo broker-verified trades yet."

        lines = ["📊 *Verified Win Rate Breakdown*\n"]

        # By source
        if bd['by_source']:
            lines.append("*By Source:*")
            for src, s in sorted(bd['by_source'].items()):
                lines.append(f"  {src.capitalize()}: {s['wins']}/{s['total']} ({s['win_rate']}%) ${s['profit']:+.2f}")

        # By asset (top 5 by trade count)
        if bd['by_asset']:
            lines.append("\n*By Asset (top 5):*")
            sorted_assets = sorted(bd['by_asset'].items(), key=lambda x: x[1]['total'], reverse=True)[:5]
            for asset, s in sorted_assets:
                lines.append(f"  {asset}: {s['wins']}/{s['total']} ({s['win_rate']}%) ${s['profit']:+.2f}")

        # By duration
        if bd['by_duration']:
            lines.append("\n*By Duration:*")
            for dur, s in sorted(bd['by_duration'].items()):
                lines.append(f"  {dur}: {s['wins']}/{s['total']} ({s['win_rate']}%) ${s['profit']:+.2f}")

        return "\n".join(lines)


class AtomicTradeLogger(TradeLogger):
    """
    Crash-safe logger using atomic file writes.
    Prevents data corruption if power/script fails during write.
    """

    # Atomic writes are now the default for all TradeLogger users.  Keep this
    # name as a compatibility alias for configuration and external imports.
    pass

