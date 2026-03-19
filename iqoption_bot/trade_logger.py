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
                  source: str = "telegram") -> dict:
        """Log a new trade."""
        trade = {
            "timestamp": datetime.now().isoformat(),
            "asset": asset,
            "direction": direction,
            "duration": duration,
            "order_id": order_id,
            "amount": amount,
            "ai_confidence": ai_confidence,
            "reasoning": reasoning,
            "source": source,
            "result": None,
            "profit": None
        }

        self.trade_history.append(trade)
        self._save()

        return trade

    def update_result(self, order_id: int, result: str, profit: float):
        """Update trade result after expiration."""
        for trade in self.trade_history:
            if trade['order_id'] == order_id:
                trade['result'] = result
                trade['profit'] = profit
                break
        self._save()

    def _save(self):
        """Save trade history to file."""
        try:
            with open(self.log_file, "w") as f:
                json.dump(self.trade_history, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving trade log: {e}")

    def get_win_rate(self, last_n: int = 50) -> float:
        """
        Calculate win rate from recent trades.

        Args:
            last_n: Number of recent trades to consider

        Returns:
            Win rate as decimal (0.0-1.0)
        """
        completed = [t for t in self.trade_history if t.get('result') in ('win', 'lose')]

        if not completed:
            return 0.55  # Default assumption

        recent = completed[-last_n:] if len(completed) > last_n else completed
        wins = len([t for t in recent if t['result'] == 'win'])

        return wins / len(recent) if recent else 0.55

    def get_statistics(self) -> dict:
        """Calculate trading statistics."""
        if not self.trade_history:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_profit": 0}

        completed = [t for t in self.trade_history if t['result'] is not None]
        wins = len([t for t in completed if t['result'] == 'win'])
        losses = len([t for t in completed if t['result'] == 'lose'])
        total_profit = sum(t.get('profit', 0) or 0 for t in completed)

        return {
            "total": len(completed),
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / len(completed) * 100), 1) if completed else 0,
            "total_profit": round(total_profit, 2)
        }

    def print_statistics(self):
        """Print formatted statistics."""
        stats = self.get_statistics()
        print(f"\n📊 TRADING STATISTICS")
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
        completed = [t for t in self.trade_history if t.get('result') in ('win', 'lose')]
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

    def format_breakdown(self) -> str:
        """Format breakdown stats for Telegram display."""
        bd = self.get_breakdown_stats()
        if not bd['by_asset'] and not bd['by_source']:
            return "📊 *Breakdown*\n\nNo completed trades yet."

        lines = ["📊 *Win Rate Breakdown*\n"]

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

    def _save(self):
        """Write to temp file then atomic rename."""
        temp_path = None
        try:
            # Get directory of log file
            log_dir = os.path.dirname(self.log_file)
            if not log_dir:
                log_dir = '.'

            # Ensure directory exists
            os.makedirs(log_dir, exist_ok=True)

            # 1. Write to a temporary file first
            fd, temp_path = tempfile.mkstemp(dir=log_dir, suffix='.tmp', text=True)
            with os.fdopen(fd, 'w') as f:
                json.dump(self.trade_history, f, indent=2)

            # 2. Atomic replace (instant swap)
            os.replace(temp_path, self.log_file)

        except Exception as e:
            print(f"⚠️ Atomic Save Error: {e}")
            # Cleanup temp file if it exists
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass

