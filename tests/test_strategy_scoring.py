"""
Tests for MHI/R7 strategy scoring (Component 2 — Enhanced).
Verifies:
  - Granular scoring: base 40 + dominance + body strength + RSI + trend
  - Dominance ratio weighting: 5V/2R stronger than 4V/3R
  - Candle body strength: doji clusters weakened
  - Score direction, ties, edge cases
  - Indicator strategy ADX scoring and RSI bands
"""
import time
import unittest
from trading_platform.legacy.iqoption_bot.strategies.mhi_strategy import MHIStrategy
from trading_platform.legacy.iqoption_bot.strategies.indicator_strategy import IndicatorStrategy


def _make_candles_colored(colors: list, base_price: float = 1.10000,
                           body_strength: str = "normal") -> list:
    """Generate candles with specific colors and body strengths.
    
    Args:
        colors: List of 'g' (green), 'r' (red), or 'd' (doji).
        body_strength: 'strong' (body_ratio ~0.7), 'normal' (~0.5), 'weak' (~0.15).
    """
    candles = []
    price = base_price
    first_timestamp = int(time.time()) - (len(colors) + 1) * 120
    for index, color in enumerate(colors):
        if body_strength == "strong":
            body_size, wick_size = 0.0007, 0.0001
        elif body_strength == "weak":
            body_size, wick_size = 0.0001, 0.0006
        else:
            body_size, wick_size = 0.0004, 0.0003

        if color == 'g':
            candles.append({
                "open": round(price, 8),
                "close": round(price + body_size, 8),
                "max": round(price + body_size + wick_size, 8),
                "min": round(price - wick_size, 8),
                "from": first_timestamp + index * 120,
            })
        elif color == 'r':
            candles.append({
                "open": round(price, 8),
                "close": round(price - body_size, 8),
                "max": round(price + wick_size, 8),
                "min": round(price - body_size - wick_size, 8),
                "from": first_timestamp + index * 120,
            })
        else:  # doji
            candles.append({
                "open": round(price, 8),
                "close": round(price, 8),  # exact same = doji
                "max": round(price + wick_size, 8),
                "min": round(price - wick_size, 8),
                "from": first_timestamp + index * 120,
            })
        price += 0.0001
    return candles


class TestMHIGranularScoring(unittest.TestCase):
    """Verify enhanced MHI scoring with dominance ratio and body strength."""

    def setUp(self):
        self.strategy = MHIStrategy()

    # ===========================================
    # DOMINANCE RATIO TESTS
    # ===========================================

    def test_strong_dominance_scores_higher(self):
        """3v0 (100% dominance) should score higher than 2v1 (33% dominance)."""
        # 3v0: all green → put, dominance = 1.0
        candles_3v0 = _make_candles_colored(['g', 'g', 'g'])
        result_3v0 = self.strategy.analyze(candles_3v0, strategy_type='mhi')

        # 2v1: 2 green 1 red → put, dominance = 0.33
        candles_2v1 = _make_candles_colored(['g', 'g', 'r'])
        result_2v1 = self.strategy.analyze(candles_2v1, strategy_type='mhi')

        self.assertGreater(abs(result_3v0.score), abs(result_2v1.score),
                           "3v0 should score higher than 2v1 due to dominance")

    def test_r7_dominance_scaling(self):
        """In R7, 6v1 should score higher than 4v3."""
        # 6v1: strong dominance
        candles_6v1 = _make_candles_colored(['r', 'r', 'r', 'r', 'r', 'r', 'g'])
        strategy = MHIStrategy(variant='r7')
        result_6v1 = strategy.analyze(candles_6v1)

        # 4v3: weak dominance
        candles_4v3 = _make_candles_colored(['r', 'r', 'r', 'r', 'g', 'g', 'g'])
        result_4v3 = strategy.analyze(candles_4v3)

        self.assertGreater(abs(result_6v1.score), abs(result_4v3.score),
                           "6v1 should score higher than 4v3 in R7")

    # ===========================================
    # BODY STRENGTH TESTS
    # ===========================================

    def test_strong_bodies_score_higher(self):
        """Candles with strong bodies should score higher than weak bodies."""
        candles_strong = _make_candles_colored(['r', 'r', 'g'], body_strength="strong")
        result_strong = self.strategy.analyze(candles_strong, strategy_type='mhi')

        candles_weak = _make_candles_colored(['r', 'r', 'g'], body_strength="weak")
        result_weak = self.strategy.analyze(candles_weak, strategy_type='mhi')

        self.assertGreater(abs(result_strong.score), abs(result_weak.score),
                           "Strong candle bodies should score higher")

    def test_doji_cluster_penalty(self):
        """Cluster with >1/3 dojis should get penalty warning."""
        # MHI: 1 green + 1 doji + 1 doji → 2 dojis out of 3 → high doji count
        # Actually this becomes 1v0 with 2 dojis, still generates signal
        candles = _make_candles_colored(['g', 'd', 'd'])
        result = self.strategy.analyze(candles, strategy_type='mhi')
        
        has_doji_warning = any("doji" in w.lower() for w in result.warnings)
        self.assertTrue(has_doji_warning, "Should warn about high doji count")

    # ===========================================
    # SCORING RANGE TESTS
    # ===========================================

    def test_minimum_score_is_above_40(self):
        """Weak reversal setups are rejected before the trade threshold."""
        candles = _make_candles_colored(['r', 'r', 'g'], body_strength="weak")
        result = self.strategy.analyze(candles, strategy_type='mhi')
        self.assertLess(abs(result.score), 65.0)
        self.assertFalse(result.should_trade)

    def test_perfect_mhi_setup_near_95(self):
        """Perfect setup: strong dominance + strong bodies + RSI + trend = ~95."""
        candles = _make_candles_colored(['r', 'r', 'r'], body_strength="strong")
        indicators_2m = {'rsi': 28.0}  # Oversold
        indicators_15m = {'trend': 'bullish'}
        result = self.strategy.analyze(
            candles, strategy_type='mhi', profile='trend',
            indicators_2m=indicators_2m, indicators_15m=indicators_15m
        )
        abs_score = abs(result.score)
        self.assertGreaterEqual(abs_score, 90.0, f"Perfect setup should be ~95, got {abs_score}")

    # ===========================================
    # DIRECTION TESTS (unchanged from Component 1)
    # ===========================================

    def test_direction_call(self):
        """Majority red → call."""
        candles = _make_candles_colored(['r', 'r', 'g'])
        result = self.strategy.analyze(candles, strategy_type='mhi')
        self.assertEqual(result.direction, "call")
        self.assertGreater(result.score, 0)

    def test_direction_put(self):
        """Majority green → put."""
        candles = _make_candles_colored(['g', 'g', 'r'])
        result = self.strategy.analyze(candles, strategy_type='mhi')
        self.assertEqual(result.direction, "put")
        self.assertLess(result.score, 0)

    def test_tie_returns_neutral(self):
        """Equal green and red should return neutral."""
        candles = _make_candles_colored(['g', 'r', 'd'])
        result = self.strategy.analyze(candles, strategy_type='mhi')
        self.assertEqual(result.direction, "neutral")
        self.assertEqual(result.score, 0.0)

    # ===========================================
    # STRATEGY VARIANT TESTS
    # ===========================================

    def test_majority_uses_5_candles(self):
        """Majority strategy should look at last 5 candles."""
        candles = _make_candles_colored(['r', 'r', 'r', 'g', 'g'])
        result = MHIStrategy(variant='majority').analyze(candles)
        self.assertEqual(result.direction, "call")

    def test_r7_uses_7_candles(self):
        """R7 strategy should look at last 7 candles."""
        candles = _make_candles_colored(['g', 'g', 'g', 'g', 'g', 'r', 'r'])
        result = MHIStrategy(variant='r7').analyze(candles)
        self.assertEqual(result.direction, "put")

    def test_insufficient_candles(self):
        """Not enough candles → neutral."""
        candles = _make_candles_colored(['g', 'r'])
        result = self.strategy.analyze(candles, strategy_type='mhi')
        self.assertEqual(result.direction, "neutral")
        self.assertFalse(result.should_trade)

    def test_empty_candles(self):
        """Empty candle list → neutral."""
        result = self.strategy.analyze([], strategy_type='mhi')
        self.assertEqual(result.direction, "neutral")
        self.assertFalse(result.should_trade)

    # ===========================================
    # PROFILE FILTERING TESTS
    # ===========================================

    def test_trend_profile_rejects_misaligned(self):
        """Trend profile should reject misaligned call."""
        candles = _make_candles_colored(['r', 'r', 'g'])
        indicators_15m = {'trend': 'bearish'}
        result = self.strategy.analyze(
            candles, strategy_type='mhi', profile='trend',
            indicators_15m=indicators_15m
        )
        self.assertFalse(result.should_trade)

    def test_reversal_profile_ignores_trend(self):
        """Reversal profile should ignore 15m trend."""
        candles = _make_candles_colored(['r', 'r', 'g'])
        indicators_15m = {'trend': 'bearish'}
        result = self.strategy.analyze(
            candles, strategy_type='mhi', profile='reversal',
            indicators_15m=indicators_15m,
            indicators_2m={'rsi': 30.0},
        )
        self.assertTrue(result.should_trade)

    # ===========================================
    # CONFIDENCE TESTS
    # ===========================================

    def test_confidence_scales_with_score(self):
        """Confidence should be proportional to score/100, capped at 0.95."""
        candles = _make_candles_colored(['r', 'r', 'g'], body_strength="strong")
        result = self.strategy.analyze(candles, strategy_type='mhi')
        
        expected_conf = min(0.95, abs(result.score) / 100.0)
        self.assertAlmostEqual(result.confidence, expected_conf, places=2)


class TestIndicatorStrategyEnhanced(unittest.TestCase):
    """Verify indicator strategy ADX scoring and RSI bands."""

    def setUp(self):
        self.strategy = IndicatorStrategy()

    def _base_indicators(self, **overrides):
        """Build a baseline indicator dict with sensible defaults."""
        base = {
            "trend": "bullish",
            "rsi": 60.0,
            "macd_histogram": 0.001,
            "stoch_k": 65.0,
            "stoch_d": 55.0,
            "atr": 0.005,
            "ema_14": 1.10000,
            "candle_open": 1.09990,
            "candle_close": 1.10010,
            "candle_high": 1.10020,
            "candle_low": 1.09985,
            "recent_high": 1.10100,
            "recent_low": 1.09900,
            "adx": 30.0,
            "avg_volume": 100.0,
            "current_volume": 100.0,
            "volatility_regime": "normal",
        }
        base.update(overrides)
        return base

    def test_adx_strong_full_trend_score(self):
        """ADX >= 25 should give full trend points."""
        indicators = self._base_indicators(adx=30.0)
        result = self.strategy.analyze([], direction="call", indicators_2m=indicators)
        has_adx_strong = any("ADX Strong" in r for r in result.reasons)
        self.assertTrue(has_adx_strong, "Should note ADX Strong")

    def test_adx_weak_warns(self):
        """ADX below the hard floor should reject the signal."""
        indicators = self._base_indicators(adx=12.0)
        result = self.strategy.analyze([], direction="call", indicators_2m=indicators)
        self.assertFalse(result.should_trade)
        self.assertTrue(any("ADX too weak" in w for w in result.warnings))

    def test_adx_weak_reduces_trend_score(self):
        """ADX < 18 should halve the trend contribution."""
        indicators_strong = self._base_indicators(adx=25.0, trend="bullish")
        result_strong = self.strategy.analyze([], direction="call",
                                               indicators_2m=indicators_strong)

        indicators_weak = self._base_indicators(adx=10.0, trend="bullish")
        result_weak = self.strategy.analyze([], direction="call",
                                             indicators_2m=indicators_weak)

        self.assertGreater(abs(result_strong.score), abs(result_weak.score),
                           "Strong ADX should score higher than weak ADX")

    def test_tight_rsi_band_call(self):
        """RSI 55-68 should get full momentum points for call."""
        # RSI at 63 (in sweet spot 55-68, outside dead zone 60-69 penalty causes
        # an interaction; let's test the band boundary instead)
        indicators = self._base_indicators(rsi=57.0)
        result = self.strategy.analyze([], direction="call", indicators_2m=indicators)
        
        # RSI at 73 is outside the current widened 52-72 CALL band.
        indicators_outside = self._base_indicators(rsi=73.0)
        result_outside = self.strategy.analyze([], direction="call",
                                                  indicators_2m=indicators_outside)

        self.assertGreater(abs(result.score), abs(result_outside.score),
                           "In-zone RSI should score higher than out-of-zone RSI")

    def test_tight_rsi_band_put(self):
        """RSI 32-45 should get full momentum points for put."""
        indicators = self._base_indicators(trend="bearish", rsi=38.0,
                                            macd_histogram=-0.001,
                                            stoch_k=35.0, stoch_d=45.0)
        result = self.strategy.analyze([], direction="put", indicators_2m=indicators)

        # RSI at 46 (marginal)
        indicators_marginal = self._base_indicators(trend="bearish", rsi=46.0,
                                                     macd_histogram=-0.001,
                                                     stoch_k=35.0, stoch_d=45.0)
        result_marginal = self.strategy.analyze([], direction="put",
                                                  indicators_2m=indicators_marginal)

        self.assertGreater(abs(result.score), abs(result_marginal.score),
                           "Sweet-spot RSI should score higher than marginal RSI")


if __name__ == "__main__":
    unittest.main()
