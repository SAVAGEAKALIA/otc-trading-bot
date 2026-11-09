import sqlite3
import tempfile
import unittest
from pathlib import Path

from trading_platform.legacy.iqoption_bot.candidate_research import CandidateResearchLogger


def candle(start, open_price, close_price):
    return {
        "from": start,
        "open": open_price,
        "max": max(open_price, close_price),
        "min": min(open_price, close_price),
        "close": close_price,
    }


class CandidateResearchTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "candidates.sqlite"
        self.logger = CandidateResearchLogger(
            str(self.path), enabled=True, candle_seconds=120
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_duplicate_candidate_is_recorded_once_and_resolved(self):
        history = [
            candle(1_800_000_000, 1.00, 1.02),
            candle(1_800_000_120, 1.02, 1.03),
        ]
        kwargs = dict(
            asset="EURUSD-OTC",
            direction="call",
            completed_candles=history,
            duration_minutes=2,
            strategy="Indicators",
            score=75.0,
            confidence=0.76,
            confluence=3,
            regime="trending",
            features={"indicators_2m": {"rsi": 55.0}},
        )
        self.logger.record_candidate(**kwargs)
        self.logger.record_candidate(**kwargs)
        self.assertEqual(self.logger.counts(), {"pending": 1})

        # Decision time is 1_800_000_240. The next 2m candle opens at
        # decision and closes exactly at the two-minute expiry.
        future = history + [
            candle(1_800_000_240, 1.03, 1.08),
        ]
        resolved = self.logger.resolve_pending("EURUSD-OTC", future)
        self.assertEqual(resolved, 1)
        self.assertEqual(self.logger.counts(), {"win": 1})

        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT entry_price, settlement_price, label FROM candidates"
            ).fetchone()
        self.assertEqual(row, (1.03, 1.08, 1))

    def test_put_loss_and_tie_are_distinct(self):
        history = [candle(1_800_000_000, 1.0, 1.0)]
        common = dict(
            asset="GBPUSD-OTC",
            completed_candles=history,
            duration_minutes=2,
            strategy="MHI",
            score=60,
            confidence=0.65,
            confluence=2,
            regime="ranging",
            features={},
        )
        self.logger.record_candidate(direction="put", **common)
        future = history + [candle(1_800_000_120, 1.0, 1.1)]
        self.logger.resolve_pending("GBPUSD-OTC", future)
        self.assertEqual(self.logger.counts(), {"loss": 1})
        self.assertEqual(
            self.logger.strategy_summary(),
            [{
                "strategy": "MHI",
                "wins": 0,
                "losses": 1,
                "ties": 0,
                "pending": 0,
            }],
        )


if __name__ == "__main__":
    unittest.main()
