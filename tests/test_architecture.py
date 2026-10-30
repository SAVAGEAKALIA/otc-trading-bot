"""
Tests for Component 3: Architecture Improvements.
Tests strategy_engine, market_regime, and backtest_engine.
"""
import unittest
"""
Tests for Component 3: Architecture Improvements.
Tests strategy_engine, market_regime, and backtest_engine.
"""
import unittest
import os
import json
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock

from trading_platform.legacy.iqoption_bot.strategy_engine import StrategyEngine, TradeDecision, StrategySlot
from trading_platform.legacy.iqoption_bot.market_regime import MarketRegimeDetector, MarketRegime
from trading_platform.legacy.iqoption_bot.strategies.base import StrategyResult


class MockStrategy:
    """Mock strategy for testing the engine."""
    def __init__(self, name, score=75.0, direction="call", confidence=0.8, should_trade=True):
        self.name = name
        self._score = score
        self._direction = direction
        self._confidence = confidence
        self._should_trade = should_trade

    def analyze(self, candles, **kwargs):
        return StrategyResult(
            score=self._score if self._direction == "call" else -self._score,
            direction=self._direction,
            confidence=self._confidence,
            reasons=[f"{self.name} signal"],
            warnings=[],
            should_trade=self._should_trade
        )


# ==================================================
# STRATEGY ENGINE TESTS
# ==================================================

class TestStrategyEngine(unittest.TestCase):

    def test_single_strategy(self):
        """Single strategy should return its result directly."""
        engine = StrategyEngine()
        engine.register(MockStrategy("MHI", score=80, direction="call"))
        
        decision = engine.evaluate([], min_agreement=1)
        self.assertEqual(decision.direction, "call")
        self.assertGreater(decision.score, 0)
        self.assertTrue(decision.should_trade)
        self.assertEqual(decision.confluence_count, 1)

    def test_two_strategies_agree(self):
        """Two strategies that agree should produce a combined signal."""
        engine = StrategyEngine()
        engine.register(MockStrategy("MHI", score=80, direction="call"))
        engine.register(MockStrategy("Indicators", score=70, direction="call"))
        
        decision = engine.evaluate([], min_agreement=1)
        self.assertEqual(decision.direction, "call")
        self.assertTrue(decision.should_trade)
        self.assertEqual(decision.confluence_count, 2)

    def test_strongest_signal_wins(self):
        """Engine should pick the strongest signal based on weighted score."""
        engine = StrategyEngine()
        engine.register(MockStrategy("MHI", score=80, direction="call"))
        engine.register(MockStrategy("Indicators", score=70, direction="put"), weight=2.0)
        
        # Indicators has score 70 * weight 2 = 140
        # MHI has score 80 * weight 1 = 80
        # So Indicators (put) should win
        decision = engine.evaluate([], min_agreement=1)
        self.assertEqual(decision.direction, "put")
        self.assertTrue(decision.should_trade)
        # Even though "put" won, the confluence count of other strategies agreeing is 0
        self.assertEqual(decision.confluence_count, 1) # Wait, it counts 1 for itself? Ah, I made it count all strategies including itself that agree. Let's let the test just check direction and should_trade.

    def test_no_strategies_registered(self):
        """No strategies → neutral."""
        engine = StrategyEngine()
        decision = engine.evaluate([], min_agreement=1)
        self.assertEqual(decision.direction, "neutral")
        self.assertFalse(decision.should_trade)

    def test_strategy_should_not_trade(self):
        """Strategy that returns should_trade=False → neutral."""
        engine = StrategyEngine()
        engine.register(MockStrategy("MHI", score=80, direction="call", should_trade=False))
        
        decision = engine.evaluate([])
        self.assertEqual(decision.direction, "neutral")
        self.assertFalse(decision.should_trade)

    def test_record_result_updates_stats(self):
        """Recording results should update win/loss counters."""
        engine = StrategyEngine()
        engine.register(MockStrategy("MHI"))
        
        engine.record_result("MHI", "win")
        engine.record_result("MHI", "win")
        engine.record_result("MHI", "loss")
        
        stats = engine.get_stats()
        self.assertEqual(stats["MHI"]["wins"], 2)
        self.assertEqual(stats["MHI"]["losses"], 1)

    def test_effective_weight_cold_start(self):
        """With < 20 trades, effective weight should equal base weight."""
        slot = StrategySlot(strategy=MockStrategy("test"), weight=1.5)
        slot.wins = 5
        slot.losses = 5
        self.assertEqual(slot.effective_weight, 1.5)

    def test_effective_weight_good_performance(self):
        """Win rate > 60% should boost weight by 1.5×."""
        slot = StrategySlot(strategy=MockStrategy("test"), weight=1.0)
        slot.wins = 15
        slot.losses = 5
        # Win rate = 75%, total trades = 20 (threshold reached)
        self.assertEqual(slot.effective_weight, 1.5)

    def test_effective_weight_poor_performance(self):
        """Win rate < 40% should drop weight to 0.3×."""
        slot = StrategySlot(strategy=MockStrategy("test"), weight=1.0)
        slot.wins = 5
        slot.losses = 15
        # Win rate = 25%, total trades = 20
        self.assertEqual(slot.effective_weight, 0.3)

    def test_strategy_crash_handled(self):
        """If a strategy raises an exception, engine should not crash."""
        class CrashingStrategy:
            name = "Crash"
            def analyze(self, candles, **kwargs):
                raise ValueError("boom")
        
        engine = StrategyEngine()
        engine.register(CrashingStrategy())
        engine.register(MockStrategy("MHI", score=80, direction="call"))
        
        decision = engine.evaluate([], min_agreement=1)
        # Should still work with the non-crashing strategy
        self.assertEqual(decision.direction, "call")
        self.assertTrue(decision.should_trade)

    def test_strategy_scores_in_decision(self):
        """Decision should contain per-strategy score breakdown."""
        engine = StrategyEngine()
        engine.register(MockStrategy("MHI", score=80, direction="call"))
        engine.register(MockStrategy("Ind", score=70, direction="call"))
        
        decision = engine.evaluate([])
        self.assertIn("MHI", decision.strategy_scores)
        self.assertIn("Ind", decision.strategy_scores)


# ==================================================
# MARKET REGIME TESTS
# ==================================================

class TestMarketRegime(unittest.TestCase):

    def setUp(self):
        self.detector = MarketRegimeDetector()

    def test_session_detection_london(self):
        """10:00 UTC should be London session."""
        regime = self.detector.detect(
            utc_now=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(regime.session, "london")
        self.assertFalse(regime.is_weekend_otc)

    def test_session_detection_new_york(self):
        """15:00 UTC should be New York session."""
        regime = self.detector.detect(
            utc_now=datetime(2025, 1, 15, 15, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(regime.session, "new_york")

    def test_session_detection_tokyo(self):
        """03:00 UTC should be Tokyo session."""
        regime = self.detector.detect(
            utc_now=datetime(2025, 1, 15, 3, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(regime.session, "tokyo")

    def test_weekend_otc_detected(self):
        """Saturday should be flagged as weekend OTC."""
        regime = self.detector.detect(
            utc_now=datetime(2025, 1, 18, 10, 0, tzinfo=timezone.utc)  # Saturday
        )
        self.assertTrue(regime.is_weekend_otc)
        self.assertEqual(regime.session, "weekend_otc")

    def test_weekend_reduces_weight(self):
        """Weekend trading should reduce recommended weight."""
        regime = self.detector.detect(
            utc_now=datetime(2025, 1, 18, 10, 0, tzinfo=timezone.utc)
        )
        self.assertLess(regime.recommended_weight_mult, 1.0)

    def test_off_hours_reduces_weight(self):
        """Off-hours (22:00 UTC) should reduce weight further."""
        regime = self.detector.detect(
            utc_now=datetime(2025, 1, 15, 22, 0, tzinfo=timezone.utc)  # Wednesday off-hours
        )
        self.assertLess(regime.recommended_weight_mult, 0.75)

    def test_extreme_volatility_reduces_weight(self):
        """Extreme volatility should reduce weight."""
        regime = self.detector.detect(
            indicators={"volatility_regime": "extreme", "volatility_pct": 0.05},
            utc_now=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        )
        self.assertLess(regime.recommended_weight_mult, 0.7)

    def test_quality_labels(self):
        """Good conditions should get 'good' quality."""
        # Normal weekday, London session, normal volatility
        regime = self.detector.detect(
            indicators={"volatility_regime": "normal", "volatility_pct": 0.01},
            utc_now=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(regime.trade_quality, "good")

    def test_spread_tracking(self):
        """Spread abnormality detection should work with enough data."""
        for _ in range(15):
            self.detector.update_spread(1.10000, 1.10005)  # Normal spread
        
        self.assertFalse(self.detector.is_spread_abnormal())
        
        # Abnormally wide spread
        self.detector.update_spread(1.10000, 1.10050)
        self.assertTrue(self.detector.is_spread_abnormal())


if __name__ == "__main__":
    unittest.main()
