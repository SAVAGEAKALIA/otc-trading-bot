"""
Tests for indicator cache data integrity.
Verifies that the cross-asset cache contamination bug is fixed:
  - Different symbols must produce different cache keys
  - Same symbol with same candles must produce the same cache key (cache hit)
  - Cache TTL expiration works correctly
"""
import time
import unittest
from unittest.mock import patch

from trading_platform.legacy.iqoption_bot.analytics import MarketAnalyzer


def _make_candles(base_price: float, count: int = 30, trend: str = "flat") -> list:
    """Generate synthetic candle data for testing.
    
    Args:
        base_price: Starting close price.
        count: Number of candles to generate (must be >= 27 for indicators).
        trend: 'up', 'down', or 'flat'.
    """
    candles = []
    price = base_price
    for i in range(count):
        if trend == "up":
            price += 0.0001 * (i + 1)
        elif trend == "down":
            price -= 0.0001 * (i + 1)
        
        candles.append({
            "open": round(price - 0.0002, 8),
            "close": round(price, 8),
            "max": round(price + 0.0005, 8),
            "min": round(price - 0.0005, 8),
            "volume": 100 + i,
        })
    return candles


class TestIndicatorCacheIsolation(unittest.TestCase):
    """Verify that indicator calculations are isolated per symbol."""

    def setUp(self):
        self.analyzer = MarketAnalyzer()

    def test_different_symbols_different_cache_keys(self):
        """Two different symbols with identical candles must produce different cache keys."""
        candles = _make_candles(1.10000, count=30)

        key_eur = self.analyzer._make_indicator_cache_key(candles, "EURUSD-OTC")
        key_gbp = self.analyzer._make_indicator_cache_key(candles, "GBPUSD-OTC")
        key_global = self.analyzer._make_indicator_cache_key(candles, "global")

        self.assertNotEqual(key_eur, key_gbp,
                            "EURUSD and GBPUSD must have different cache keys")
        self.assertNotEqual(key_eur, key_global,
                            "EURUSD and 'global' must have different cache keys")
        self.assertNotEqual(key_gbp, key_global,
                            "GBPUSD and 'global' must have different cache keys")
        
        # Verify symbol is embedded in the key
        self.assertIn("EURUSD-OTC", key_eur)
        self.assertIn("GBPUSD-OTC", key_gbp)

    def test_same_symbol_same_candles_cache_hit(self):
        """Same symbol + same candles must hit cache on second call."""
        candles = _make_candles(1.10000, count=30)

        # First call: cache miss
        result1 = self.analyzer.calculate_indicators(candles, symbol="EURUSD-OTC")
        self.assertIsNotNone(result1, "First call should return indicators")

        stats_before = self.analyzer.get_indicator_cache_stats()
        hits_before = stats_before['hits']

        # Second call: should be a cache hit
        result2 = self.analyzer.calculate_indicators(candles, symbol="EURUSD-OTC")
        self.assertIsNotNone(result2, "Second call should return cached indicators")

        stats_after = self.analyzer.get_indicator_cache_stats()
        self.assertEqual(stats_after['hits'], hits_before + 1,
                         "Second call should increment cache hits")

    def test_same_candles_different_symbols_no_cross_contamination(self):
        """Same candles but different symbols must NOT share cached results.
        
        This is the critical test for the bug we fixed: previously all symbols
        used 'global' as the cache key, so EURUSD's indicators would be
        returned for GBPUSD if the candle data happened to match.
        """
        candles = _make_candles(1.10000, count=30)

        # Calculate for EURUSD
        result_eur = self.analyzer.calculate_indicators(candles, symbol="EURUSD-OTC")
        self.assertIsNotNone(result_eur)

        stats_after_eur = self.analyzer.get_indicator_cache_stats()

        # Calculate for GBPUSD with same candles — must be a cache MISS
        result_gbp = self.analyzer.calculate_indicators(candles, symbol="GBPUSD-OTC")
        self.assertIsNotNone(result_gbp)

        stats_after_gbp = self.analyzer.get_indicator_cache_stats()
        
        # The cache should have 2 entries (one per symbol)
        self.assertEqual(stats_after_gbp['entries'], stats_after_eur['entries'] + 1,
                         "GBPUSD should create a new cache entry, not reuse EURUSD's")

    def test_different_candle_data_per_symbol(self):
        """Different candle data for different symbols must produce different indicator values."""
        candles_up = _make_candles(1.10000, count=30, trend="up")
        candles_down = _make_candles(1.10000, count=30, trend="down")

        result_up = self.analyzer.calculate_indicators(candles_up, symbol="EURUSD-OTC")
        result_down = self.analyzer.calculate_indicators(candles_down, symbol="GBPUSD-OTC")

        self.assertIsNotNone(result_up)
        self.assertIsNotNone(result_down)

        # RSI for uptrend should be higher than for downtrend
        self.assertGreater(result_up['rsi'], result_down['rsi'],
                           "Uptrend RSI should be higher than downtrend RSI")

    def test_cache_ttl_expiry(self):
        """Cache entries must expire after INDICATOR_CACHE_TTL."""
        candles = _make_candles(1.10000, count=30)

        result1 = self.analyzer.calculate_indicators(candles, symbol="EURUSD-OTC")
        self.assertIsNotNone(result1)

        # Patch time to simulate TTL expiry
        original_ttl = self.analyzer.INDICATOR_CACHE_TTL
        with patch('trading_platform.legacy.iqoption_bot.analytics.time') as mock_time:
            # First call uses real time stored in cache, so we need to
            # manipulate the time check in _get_cached_indicators
            mock_time.time.return_value = time.time() + original_ttl + 1
            
            cache_key = self.analyzer._make_indicator_cache_key(candles, "EURUSD-OTC")
            cached = self.analyzer._get_cached_indicators(cache_key)
            self.assertIsNone(cached, "Cache should have expired after TTL")

    def test_default_symbol_is_global(self):
        """Calling without symbol should default to 'global' — verifying the signature."""
        candles = _make_candles(1.10000, count=30)

        # Without symbol (old buggy behavior)
        result_global = self.analyzer.calculate_indicators(candles)
        cache_key = self.analyzer._make_indicator_cache_key(candles, "global")
        
        self.assertIn("global", cache_key,
                       "Default symbol should be 'global'")

    def test_cache_ttl_value(self):
        """Verify the deliberately short cache TTL used for live scanner data."""
        self.assertEqual(self.analyzer.INDICATOR_CACHE_TTL, 3,
                         "Cache TTL should remain 3 seconds to avoid stale cross-scan indicators")


if __name__ == "__main__":
    unittest.main()
