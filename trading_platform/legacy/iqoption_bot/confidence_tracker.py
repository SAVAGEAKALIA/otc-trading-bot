"""
Confidence Calibration Tracker — Tracks actual win rate per confidence bucket.

Purpose: Validate whether higher-confidence signals actually win more often.
Data is per-session (in-memory, resets on restart).
"""

from typing import Dict, Any, List


class ConfidenceTracker:
    """
    Buckets trade results by confidence range and signal source.

    Buckets: 0-50%, 50-60%, 60-70%, 70-80%, 80-90%, 90-100%
    Sources: "scanner", "telegram"
    """

    BUCKETS = [
        (0.0, 0.50, "<50%"),
        (0.50, 0.60, "50-60%"),
        (0.60, 0.70, "60-70%"),
        (0.70, 0.80, "70-80%"),
        (0.80, 0.90, "80-90%"),
        (0.90, 1.01, "90-100%"),
    ]

    def __init__(self):
        self._data: Dict[str, Dict[str, Dict[str, int]]] = {}
        # Structure: { bucket_label: { source: { "wins": N, "total": N } } }
        self._init_buckets()

    def _init_buckets(self):
        """Initialize empty bucket structure."""
        for _, _, label in self.BUCKETS:
            self._data[label] = {
                "all": {"wins": 0, "total": 0},
                "scanner": {"wins": 0, "total": 0},
                "telegram": {"wins": 0, "total": 0},
            }

    def _get_bucket_label(self, confidence: float) -> str:
        """Map a confidence value to its bucket label."""
        for low, high, label in self.BUCKETS:
            if low <= confidence < high:
                return label
        return "<50%"  # fallback

    def record(self, confidence: float, source: str, won: bool):
        """
        Record a trade result.

        Args:
            confidence: Signal confidence (0.0 - 1.0)
            source: "scanner" or "telegram"
            won: Whether the trade won
        """
        label = self._get_bucket_label(confidence)
        source = source.lower() if source else "telegram"
        if source not in ("scanner", "telegram"):
            source = "telegram"

        # Update bucket totals
        self._data[label]["all"]["total"] += 1
        self._data[label][source]["total"] += 1
        if won:
            self._data[label]["all"]["wins"] += 1
            self._data[label][source]["wins"] += 1

    def get_calibration(self) -> Dict[str, Dict[str, Any]]:
        """
        Get calibration data: actual win rate per bucket and source.

        Returns:
            Dict keyed by bucket label, each containing:
            - total, wins, win_rate for "all", "scanner", "telegram"
        """
        result = {}
        for _, _, label in self.BUCKETS:
            bucket = {}
            for source in ("all", "scanner", "telegram"):
                stats = self._data[label][source]
                total = stats["total"]
                wins = stats["wins"]
                win_rate = (wins / total * 100) if total > 0 else 0.0
                bucket[source] = {
                    "total": total,
                    "wins": wins,
                    "win_rate": round(win_rate, 1),
                }
            result[label] = bucket
        return result

    def get_summary(self) -> str:
        """Get formatted summary for Telegram /stats command."""
        cal = self.get_calibration()

        # Check if we have any data
        total_trades = sum(b["all"]["total"] for b in cal.values())
        if total_trades == 0:
            return "📊 *Confidence Calibration*\n\nNo trades recorded yet."

        lines = ["📊 *Confidence Calibration*\n"]
        lines.append("```")
        lines.append(f"{'Bucket':<10} {'Trades':>6} {'Wins':>5} {'WR%':>6}")
        lines.append("-" * 30)

        for _, _, label in self.BUCKETS:
            stats = cal[label]["all"]
            if stats["total"] > 0:
                lines.append(
                    f"{label:<10} {stats['total']:>6} {stats['wins']:>5} {stats['win_rate']:>5.1f}%"
                )

        lines.append("```")

        # Source breakdown (only if both have data)
        scanner_total = sum(b["scanner"]["total"] for b in cal.values())
        telegram_total = sum(b["telegram"]["total"] for b in cal.values())

        if scanner_total > 0 and telegram_total > 0:
            scanner_wins = sum(b["scanner"]["wins"] for b in cal.values())
            telegram_wins = sum(b["telegram"]["wins"] for b in cal.values())
            s_wr = (scanner_wins / scanner_total * 100) if scanner_total else 0
            t_wr = (telegram_wins / telegram_total * 100) if telegram_total else 0
            lines.append(f"\n*By Source:*")
            lines.append(f"Scanner: {scanner_wins}/{scanner_total} ({s_wr:.1f}%)")
            lines.append(f"Telegram: {telegram_wins}/{telegram_total} ({t_wr:.1f}%)")

        return "\n".join(lines)

    def reset(self):
        """Reset all tracking data."""
        self._init_buckets()
