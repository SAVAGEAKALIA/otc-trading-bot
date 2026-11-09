"""Regression tests for cache freshness at candle boundaries."""

import time
import unittest
from unittest.mock import MagicMock, patch

from trading_platform.legacy.iqoption_bot.data_provider import CandleData, MarketDataProvider


class TestBoundaryAwareCandleCache(unittest.TestCase):
    def setUp(self):
        self.provider = MarketDataProvider(MagicMock())

    def test_pre_close_snapshot_is_not_reused_after_close(self):
        # The last candle was still open when this response was captured.
        candle_start = 1_000.0
        cached = CandleData(
            timeframe=120,
            candles=[{"from": candle_start}],
            fetched_at=candle_start + 110,
        )
        self.provider._set_cached("EURUSD-OTC", 120, cached)

        # At 1,121 the 1,000-1,120 candle is closed.  Reusing its OHLC would
        # promote a 10-second-old partial candle into a completed one.
        with patch("trading_platform.market_data.provider.time.time", return_value=candle_start + 121):
            self.assertIsNone(self.provider._get_cached("EURUSD-OTC", 120))

    def test_cache_remains_usable_before_its_candle_closes(self):
        now = time.time()
        candle_start = now - 30
        cached = CandleData(
            timeframe=120,
            candles=[{"at": candle_start}],
            fetched_at=now - 1,
        )
        self.provider._set_cached("EURUSD-OTC", 120, cached)

        self.assertIs(self.provider._get_cached("EURUSD-OTC", 120), cached)


if __name__ == "__main__":
    unittest.main()
