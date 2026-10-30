import unittest
from unittest.mock import AsyncMock

from trading_platform.legacy.iqoption_bot.data_provider import CandleData, MarketDataProvider


def make_5m_candle(timestamp, price, *, timestamp_scale=1):
    return {
        "from": timestamp * timestamp_scale,
        "at": timestamp * timestamp_scale,
        "open": price,
        "max": price + 0.6,
        "min": price - 0.4,
        "close": price + 0.2,
        "volume": 10,
        "id": timestamp,
    }


class Synthetic15mAggregationTests(unittest.TestCase):
    def test_uses_only_complete_clock_aligned_groups(self):
        start = 1_800_000_000  # exactly divisible by 900
        candles = [
            make_5m_candle(start + 600, 3.0, timestamp_scale=1000),
            make_5m_candle(start, 1.0, timestamp_scale=1000),
            make_5m_candle(start + 300, 2.0, timestamp_scale=1000),
            # The next 15m bucket is incomplete and must be ignored.
            make_5m_candle(start + 900, 4.0, timestamp_scale=1000),
            make_5m_candle(start + 1500, 6.0, timestamp_scale=1000),
        ]

        result = MarketDataProvider._synthesize_15m_from_5m(candles)

        self.assertEqual(len(result), 1)
        candle = result[0]
        self.assertEqual(candle["at"], start)
        self.assertEqual(candle["from"], start)
        self.assertEqual(candle["to"], start + 900)
        self.assertEqual(candle["open"], 1.0)
        self.assertEqual(candle["close"], 3.2)
        self.assertEqual(candle["max"], 3.6)
        self.assertEqual(candle["min"], 0.6)
        self.assertEqual(candle["volume"], 30.0)

    def test_missing_or_misaligned_candle_is_not_bridged(self):
        start = 1_800_000_000
        candles = [
            make_5m_candle(start, 1.0),
            make_5m_candle(start + 600, 3.0),
            make_5m_candle(start + 900, 4.0),
            make_5m_candle(start + 1200, 5.0),
            make_5m_candle(start + 1500, 6.0),
        ]

        result = MarketDataProvider._synthesize_15m_from_5m(candles)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["at"], start + 900)


class Synthetic15mBundleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.provider = MarketDataProvider(object(), mtf_enabled=True)
        self.start = 1_800_000_000
        self.entry = CandleData(
            timeframe=120,
            candles=[
                {
                    "from": self.start + index * 120,
                    "open": 1.0,
                    "max": 1.1,
                    "min": 0.9,
                    "close": 1.0,
                }
                for index in range(12)
            ],
        )
        self.five = CandleData(
            timeframe=300,
            candles=[
                make_5m_candle(self.start + index * 300, float(index + 1))
                for index in range(30)
            ],
        )

        async def fetch(_asset, timeframe, _count=None):
            if timeframe == 120:
                return self.entry
            if timeframe == 300:
                return self.five
            raise AssertionError("native 900-second data must not be fetched")

        self.provider._fetch_candles = AsyncMock(side_effect=fetch)

    async def test_15m_only_request_still_uses_iq_option_5m_source(self):
        bundle = await self.provider.get_mtf_bundle(
            "EURUSD-OTC", include_5m=False, include_15m=True
        )

        self.assertIsNone(bundle.mid_tf)
        self.assertIsNotNone(bundle.high_tf)
        self.assertEqual(bundle.high_tf.timeframe, 900)
        self.assertEqual(len(bundle.high_tf.candles), 10)
        fetched_timeframes = [
            call.args[1] for call in self.provider._fetch_candles.await_args_list
        ]
        self.assertEqual(fetched_timeframes, [120, 300])

    async def test_full_bundle_reuses_single_5m_fetch(self):
        bundle = await self.provider.get_mtf_bundle(
            "EURUSD-OTC", include_5m=True, include_15m=True
        )

        self.assertIs(bundle.mid_tf, self.five)
        self.assertEqual(len(bundle.high_tf.candles), 10)
        fetched_timeframes = [
            call.args[1] for call in self.provider._fetch_candles.await_args_list
        ]
        self.assertEqual(fetched_timeframes, [120, 300])


if __name__ == "__main__":
    unittest.main()
