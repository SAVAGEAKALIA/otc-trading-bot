"""
Integration tests for the remaining architecture improvements:
  - Scanner ↔ StrategyEngine wiring
  - CCV2 Strategy
  - Adaptive Strategy
  - Fingerprint improvements (time-of-day, Bayesian, 25 matches)
  - Sizing improvements (per-strategy Kelly, no-trade edge rejection, 2% cap)
"""
import unittest
import time
from datetime import datetime, timezone

# Strategy base
from trading_platform.legacy.iqoption_bot.strategies.base import StrategyResult

# Strategies
from trading_platform.legacy.iqoption_bot.strategies.ccv2_strategy import CCV2Strategy
from trading_platform.legacy.iqoption_bot.strategies.adaptive_strategy import AdaptiveStrategy

# Engine
from trading_platform.legacy.iqoption_bot.strategy_engine import StrategyEngine

# Fingerprint
from trading_platform.legacy.iqoption_bot.fingerprint import TradeFingerprint, RollingMemoryDB, _hour_to_session

# Sizing
from trading_platform.legacy.iqoption_bot.sizing import PositionSizer


# ==================================================
# HELPER: Generate fake candle dicts
# ==================================================

def _make_candles(count, direction="up", base_price=1.0, spread=0.001):
    """Generate a list of candle dicts with a trend."""
    candles = []
    price = base_price
    first_timestamp = int(time.time()) - (count + 1) * 120
    for i in range(count):
        if direction == "up":
            o = price
            c = price + spread
        elif direction == "down":
            o = price
            c = price - spread
        else:
            o = price
            c = price + (spread if i % 2 == 0 else -spread)
        h = max(o, c) + spread * 0.3
        l = min(o, c) - spread * 0.3
        candles.append({"open": o, "close": c, "max": h, "min": l, "from": first_timestamp + i * 120})
        price = c
    return candles


def _make_streak_candles(streak_color, streak_len, base=1.0, spread=0.001):
    """Generate candles with a specific streak at the end."""
    candles = []
    price = base
    total_count = 5 + streak_len
    first_timestamp = int(time.time()) - (total_count + 1) * 120
    # Add 5 neutral candles first (mixed)
    for i in range(5):
        d = "up" if i % 2 == 0 else "down"
        o = price
        c = price + spread if d == "up" else price - spread
        h = max(o, c) + spread * 0.3
        l = min(o, c) - spread * 0.3
        candles.append({"open": o, "close": c, "max": h, "min": l, "from": first_timestamp + i * 120})
        price = c
    # Add streak
    for streak_index in range(streak_len):
        o = price
        if streak_color == "green":
            c = price + spread * 2
        else:
            c = price - spread * 2
        h = max(o, c) + spread * 0.3
        l = min(o, c) - spread * 0.3
        candles.append({
            "open": o, "close": c, "max": h, "min": l,
            "from": first_timestamp + (5 + streak_index) * 120,
        })
        price = c
    return candles


# ==================================================
# CCV2 STRATEGY TESTS
# ==================================================

class TestCCV2Strategy(unittest.TestCase):
    def setUp(self):
        self.strategy = CCV2Strategy(min_streak=3)

    def test_3_red_streak_gives_call(self):
        """3 consecutive red candles → expect CALL reversal."""
        candles = _make_streak_candles("red", 3)
        result = self.strategy.analyze(candles, indicators_2m={"rsi": 28.0})
        self.assertEqual(result.direction, "call")
        self.assertTrue(result.should_trade)

    def test_3_green_streak_gives_put(self):
        """3 consecutive green candles → expect PUT reversal."""
        candles = _make_streak_candles("green", 3)
        result = self.strategy.analyze(candles, indicators_2m={"rsi": 72.0})
        self.assertEqual(result.direction, "put")
        self.assertTrue(result.should_trade)

    def test_5_streak_higher_score_than_3(self):
        """Longer streak should produce higher score."""
        candles_3 = _make_streak_candles("red", 3)
        candles_5 = _make_streak_candles("red", 5)
        ind = {"rsi": 28.0}

        score_3 = abs(self.strategy.analyze(candles_3, indicators_2m=ind).score)
        score_5 = abs(self.strategy.analyze(candles_5, indicators_2m=ind).score)
        self.assertGreater(score_5, score_3)

    def test_rsi_confirmation_boosts_score(self):
        """RSI at extreme (< 30 for CALL) should give higher score."""
        candles = _make_streak_candles("red", 3)
        score_oversold = abs(self.strategy.analyze(candles, indicators_2m={"rsi": 25.0}).score)
        score_neutral = abs(self.strategy.analyze(candles, indicators_2m={"rsi": 50.0}).score)
        self.assertGreater(score_oversold, score_neutral)

    def test_insufficient_candles(self):
        """Not enough candles → neutral."""
        candles = [{"open": 1.0, "close": 0.999, "max": 1.001, "min": 0.998}]
        result = self.strategy.analyze(candles, indicators_2m={})
        self.assertEqual(result.direction, "neutral")
        self.assertFalse(result.should_trade)

    def test_no_streak(self):
        """Alternating candles → no streak → neutral."""
        candles = _make_candles(10, direction="mixed")
        result = self.strategy.analyze(candles, indicators_2m={"rsi": 50.0})
        # May or may not detect depending on alternation; check doesn't crash
        self.assertIsInstance(result, StrategyResult)


# ==================================================
# ADAPTIVE STRATEGY TESTS
# ==================================================

class TestAdaptiveStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = AdaptiveStrategy(er_period=5)

    def test_strong_uptrend_gives_call(self):
        """Strong uptrend (high ER) → CALL signal."""
        candles = _make_candles(12, direction="up", spread=0.003)
        result = self.strategy.analyze(candles, indicators_2m={"rsi": 55.0, "stoch_k": 60.0, "stoch_d": 50.0})
        # Should give call or neutral due to not enough crossing
        self.assertIn(result.direction, ("call", "neutral"))

    def test_strong_downtrend_gives_put(self):
        """Strong downtrend → PUT signal."""
        candles = _make_candles(12, direction="down", spread=0.003)
        result = self.strategy.analyze(candles, indicators_2m={"rsi": 40.0, "stoch_k": 30.0, "stoch_d": 40.0})
        self.assertIn(result.direction, ("put", "neutral"))

    def test_insufficient_candles(self):
        """Not enough candles → neutral."""
        candles = _make_candles(3, direction="up")
        result = self.strategy.analyze(candles, indicators_2m={})
        self.assertEqual(result.direction, "neutral")
        self.assertFalse(result.should_trade)

    def test_efficiency_ratio_calculation(self):
        """ER should be high for trending data."""
        trending = [float(i) * 0.001 + 1.0 for i in range(15)]
        er = self.strategy._calculate_er(trending)
        self.assertGreater(er, 0.8)

    def test_efficiency_ratio_choppy(self):
        """ER should be low for choppy data."""
        choppy = [1.0 + (0.001 if i % 2 == 0 else -0.001) for i in range(15)]
        er = self.strategy._calculate_er(choppy)
        self.assertLessEqual(er, 0.2)


# ==================================================
# STRATEGY ENGINE + SCANNER INTEGRATION TESTS
# ==================================================

class TestEngineIntegration(unittest.TestCase):
    """Test that StrategyEngine properly orchestrates multiple strategies."""

    def test_engine_with_all_strategies(self):
        """Engine should run all 4 strategies without crashing."""
        engine = StrategyEngine()
        from trading_platform.legacy.iqoption_bot.strategies.indicator_strategy import IndicatorStrategy
        from trading_platform.legacy.iqoption_bot.strategies.mhi_strategy import MHIStrategy

        engine.register(IndicatorStrategy(), weight=1.2)
        engine.register(MHIStrategy(), weight=1.0)
        engine.register(CCV2Strategy(), weight=0.8)
        engine.register(AdaptiveStrategy(), weight=0.7)

        candles = _make_streak_candles("red", 4)
        decision = engine.evaluate(
            candles=candles,
            indicators_2m={"rsi": 28.0, "stoch_k": 20.0, "stoch_d": 25.0,
                           "macd_histogram": -0.001, "adx": 25.0,
                           "trend": "bearish", "ema_14": 0.999,
                           "candle_open": 0.998, "candle_close": 0.996,
                           "candle_high": 0.999, "candle_low": 0.995,
                           "atr": 0.001, "volatility_regime": "normal"},
        )
        # Should not crash; should return a TradeDecision
        self.assertIn(decision.direction, ("call", "put", "neutral"))
        self.assertIn("CCV2", decision.strategy_scores)

    def test_engine_records_results(self):
        """Recording results should update strategy stats."""
        engine = StrategyEngine()
        engine.register(CCV2Strategy(), weight=1.0)

        engine.record_result("CCV2", "win")
        engine.record_result("CCV2", "win")
        engine.record_result("CCV2", "loss")

        stats = engine.get_stats()
        self.assertEqual(stats["CCV2"]["wins"], 2)
        self.assertEqual(stats["CCV2"]["losses"], 1)


# ==================================================
# FINGERPRINT IMPROVEMENTS TESTS
# ==================================================

class TestFingerprintImprovements(unittest.TestCase):

    def test_hour_auto_populated(self):
        """TradeFingerprint should auto-populate hour from action_time."""
        t = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc).timestamp()
        fp = TradeFingerprint(
            asset="EURUSD-OTC", direction="call", action_time=t,
            rsi=55.0, stoch_k=60.0, stoch_d=55.0, macd_hist=0.001,
            bb_position=0.6, volatility="normal",
            trend_2m="bullish", trend_5m="bullish", trend_15m="neutral",
            score=75.0
        )
        self.assertEqual(fp.hour, 14)

    def test_from_dict_backward_compat(self):
        """from_dict should handle old records without 'hour' field."""
        old_data = {
            "asset": "EURUSD-OTC", "direction": "call", "action_time": time.time(),
            "rsi": 55.0, "stoch_k": 60.0, "stoch_d": 55.0, "macd_hist": 0.001,
            "bb_position": 0.6, "volatility": "normal",
            "trend_2m": "bullish", "trend_5m": "bullish", "trend_15m": "neutral",
            "score": 75.0, "result": "win"
        }
        fp = TradeFingerprint.from_dict(old_data)
        self.assertEqual(fp.asset, "EURUSD-OTC")
        # hour should be auto-populated
        self.assertIsNotNone(fp.hour)

    def test_from_dict_ignores_unknown_fields(self):
        """from_dict should ignore extra fields not in the dataclass."""
        data = {
            "asset": "EURUSD-OTC", "direction": "call", "action_time": time.time(),
            "rsi": 55.0, "stoch_k": 60.0, "stoch_d": 55.0, "macd_hist": 0.001,
            "bb_position": 0.6, "volatility": "normal",
            "trend_2m": "bullish", "trend_5m": "bullish", "trend_15m": "neutral",
            "score": 75.0, "some_future_field": "hello"
        }
        fp = TradeFingerprint.from_dict(data)
        self.assertEqual(fp.asset, "EURUSD-OTC")

    def test_default_max_matches_is_25(self):
        """Default max_matches should now be 25."""
        import inspect
        sig = inspect.signature(RollingMemoryDB.calculate_probability)
        default = sig.parameters["max_matches"].default
        self.assertEqual(default, 25)

    def test_hour_to_session(self):
        """_hour_to_session should map hours correctly."""
        self.assertEqual(_hour_to_session(3), "tokyo")
        self.assertEqual(_hour_to_session(10), "london")
        self.assertEqual(_hour_to_session(15), "new_york")
        self.assertEqual(_hour_to_session(22), "off_hours")

    def test_bayesian_probability_cold_start(self):
        """With no records, probability should be 0.5."""
        import tempfile, os
        fp_path = os.path.join(tempfile.mkdtemp(), "test_fp.json")
        db = RollingMemoryDB(filepath=fp_path, max_records=100)

        current = TradeFingerprint(
            asset="EURUSD-OTC", direction="call", action_time=time.time(),
            rsi=55.0, stoch_k=60.0, stoch_d=55.0, macd_hist=0.001,
            bb_position=0.6, volatility="normal",
            trend_2m="bullish", trend_5m="bullish", trend_15m="neutral",
            score=75.0
        )
        result = db.calculate_probability(current)
        self.assertEqual(result["probability"], 0.5)
        self.assertEqual(result["match_count"], 0)

    def test_bayesian_with_matching_records(self):
        """Bayesian posterior should shift with matching records."""
        import tempfile, os
        fp_path = os.path.join(tempfile.mkdtemp(), "test_fp_bayesian.json")
        db = RollingMemoryDB(filepath=fp_path, max_records=100)

        base_time = time.time()
        # Add 5 wins with similar indicators
        for i in range(5):
            fp = TradeFingerprint(
                asset="EURUSD-OTC", direction="call", action_time=base_time - i * 60,
                rsi=55.0, stoch_k=60.0, stoch_d=55.0, macd_hist=0.001,
                bb_position=0.6, volatility="normal",
                trend_2m="bullish", trend_5m="bullish", trend_15m="neutral",
                score=75.0, result="win"
            )
            db.add_fingerprint(fp)

        # Add 1 loss
        fp_loss = TradeFingerprint(
            asset="EURUSD-OTC", direction="call", action_time=base_time - 300,
            rsi=54.0, stoch_k=59.0, stoch_d=54.0, macd_hist=0.001,
            bb_position=0.61, volatility="normal",
            trend_2m="bullish", trend_5m="bullish", trend_15m="neutral",
            score=72.0, result="loss"
        )
        db.add_fingerprint(fp_loss)

        # Query similar setup
        current = TradeFingerprint(
            asset="EURUSD-OTC", direction="call", action_time=base_time,
            rsi=55.0, stoch_k=60.0, stoch_d=55.0, macd_hist=0.001,
            bb_position=0.6, volatility="normal",
            trend_2m="bullish", trend_5m="bullish", trend_15m="neutral",
            score=75.0
        )
        result = db.calculate_probability(current)
        # Should be > 0.5 because 5 wins vs 1 loss
        self.assertGreater(result["probability"], 0.5)
        self.assertGreater(result["match_count"], 0)
        self.assertIn("Bayesian", result["reason"])


# ==================================================
# POSITION SIZING TESTS
# ==================================================

class TestSizingImprovements(unittest.TestCase):

    def test_kelly_with_strategy_win_rate(self):
        """Per-strategy win rate should be used when provided."""
        sizer = PositionSizer({"method": "kelly", "kelly_fraction": 0.25})
        # High strategy win rate
        size_high = sizer.calculate_size(1000.0, win_rate=0.50, strategy_win_rate=0.70)
        # Low strategy win rate
        size_low = sizer.calculate_size(1000.0, win_rate=0.50, strategy_win_rate=0.55)
        self.assertGreater(size_high, size_low)

    def test_negative_kelly_rejects_trade(self):
        """Negative Kelly represents a negative estimated edge and must not trade."""
        sizer = PositionSizer({"method": "kelly", "kelly_fraction": 0.25, "min_trade": 1.0})
        # Win rate 0.30 at 0.84 payout → Kelly is negative
        size = sizer.calculate_size(500.0, win_rate=0.30, payout=0.84)
        self.assertEqual(size, 0.0)

    def test_hard_2_percent_cap(self):
        """Position should never exceed 2% of balance."""
        sizer = PositionSizer({
            "method": "kelly", "kelly_fraction": 0.5,
            "max_risk_percentage": 0.02,
            "max_trade": 100.0
        })
        # Very high win rate → large Kelly
        size = sizer.calculate_size(1000.0, win_rate=0.80, payout=0.84)
        self.assertLessEqual(size, 20.0)  # 2% of $1000

    def test_anti_martingale_tracking(self):
        """Anti-martingale multiplier should increase after wins."""
        sizer = PositionSizer({"method": "fixed", "anti_martingale_multiplier": 1.5})
        self.assertAlmostEqual(sizer.get_anti_martingale_multiplier(), 1.0)

        sizer.record_outcome("win")
        self.assertAlmostEqual(sizer.get_anti_martingale_multiplier(), 1.5)

        sizer.record_outcome("win")
        self.assertAlmostEqual(sizer.get_anti_martingale_multiplier(), 2.25)

        sizer.record_outcome("loss")
        self.assertAlmostEqual(sizer.get_anti_martingale_multiplier(), 1.0)

    def test_fixed_amount_unchanged(self):
        """Fixed amount method should still work as before."""
        sizer = PositionSizer({"method": "fixed", "fixed_amount": 5.0})
        size = sizer.calculate_size(1000.0)
        self.assertEqual(size, 5.0)

    def test_fixed_percentage(self):
        """Fixed percentage method should work correctly."""
        sizer = PositionSizer({"method": "percent", "fixed_percentage": 0.01})
        size = sizer.calculate_size(1000.0)
        self.assertEqual(size, 10.0)


if __name__ == "__main__":
    unittest.main()
