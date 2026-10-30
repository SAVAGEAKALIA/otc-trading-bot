
import asyncio
import sys
import os
import unittest
from unittest.mock import MagicMock, AsyncMock

# Add current directory to path so we can import trading_platform.legacy.iqoption_bot
sys.path.append(os.getcwd())

from trading_platform.legacy.iqoption_bot.reanalyzer import SignalReAnalyzer, SmartSignalConfig
from trading_platform.legacy.iqoption_bot.analytics import TradeDecision

class TestSmartMartingale(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.data_provider = MagicMock()
        self.data_provider.get_mtf_bundle = AsyncMock()
        
        self.analyzer = MagicMock()
        self.gatekeeper = MagicMock()
        self.pattern_analyzer = MagicMock()
        
        self.reanalyzer = SignalReAnalyzer(
            self.data_provider, 
            self.analyzer, 
            self.gatekeeper, 
            self.pattern_analyzer
        )
        
        # Enable all features
        self.reanalyzer.config.flip_trades = True
        self.reanalyzer.config.dynamic_duration = True
        self.reanalyzer.config.min_score_to_flip = 30.0
        self.reanalyzer.config.min_score_to_approve = 10.0

    async def test_martingale_flip_scenario(self):
        """Test that a CALL martingale step flips to PUT if market is strongly bearish."""
        # 1. Mock Market Data (Strong Bearish Trend)
        bundle = MagicMock()
        bundle.entry_tf.is_valid = True
        bundle.entry_tf.candles = [{"close": 100}] * 10
        bundle.mid_tf.is_valid = True
        bundle.high_tf.is_valid = True
        self.data_provider.get_mtf_bundle.return_value = bundle
        
        # 2. Mock Indicators (High ADX, Bearish)
        self.analyzer.calculate_indicators.return_value = {
            "adx": 40, 
            "trend": "bearish",
            "volatility_regime": "normal"
        }
        
        # 3. Mock Gatekeeper Decision
        # For CALL (original direction): Reject/Low Score (actually negative score for Bearish)
        # For PUT (opposite direction): Accept/High Score
        def mock_decide(*args, **kwargs):
            direction = kwargs.get('requested_direction')
            if direction == "call":
                return TradeDecision(
                    accept=False, direction="call", score=-85.0, confidence=0.9, 
                    reason="Strong Bearish Trend", notes=[], risk_level="high", confluence_count=0
                )
            else:
                return TradeDecision(
                    accept=True, direction="put", score=85.0, confidence=0.9, 
                    reason="Approved Trend Joining", notes=[], risk_level="low", confluence_count=4
                )
        
        self.gatekeeper.decide.side_effect = mock_decide
        self.gatekeeper.mode = "normal"
        
        # 4. Analyze Martingale Step (CALL)
        result = await self.reanalyzer.analyze("EURUSD", "call", 1, is_martingale=True)
        
        print(f"\n[Test Flip] Action: {result.action}")
        print(f"[Test Flip] New Direction: {result.new_direction}")
        print(f"[Test Flip] Reason: {result.reason}")
        
        self.assertEqual(result.action, "flip")
        self.assertEqual(result.new_direction, "put")
        self.assertIn("SMART RECOVERY FLIP", result.reason)

    async def test_martingale_reject_scenario(self):
        """Test that a martingale step is rejected if market is too neutral."""
        # 1. Mock Market Data (Flat)
        bundle = MagicMock()
        bundle.entry_tf.is_valid = True
        self.data_provider.get_mtf_bundle.return_value = bundle
        
        # 2. Mock Indicators (ADX 5, Neutral)
        self.analyzer.calculate_indicators.return_value = {
            "adx": 5, 
            "trend": "neutral",
            "volatility_regime": "normal"
        }
        
        # 3. Mock Gatekeeper Decision (Near Zero Score)
        self.gatekeeper.decide.return_value = TradeDecision(
            accept=True, direction="call", score=2.0, confidence=0.1, 
            reason="Too Neutral", notes=[], risk_level="normal", confluence_count=1
        )
        self.gatekeeper.mode = "normal"
        
        # 4. Analyze Martingale Step
        result = await self.reanalyzer.analyze("EURUSD", "call", 1, is_martingale=True)
        
        print(f"\n[Test Reject] Action: {result.action}")
        print(f"[Test Reject] Reason: {result.reason}")
        
        self.assertEqual(result.action, "reject")
        self.assertIn("SmartReject", result.reason)

    async def test_independent_sentiment_override(self):
        """Test that the ReAnalyzer's independent brain can override the Gatekeeper."""
        # 1. Setup: Gatekeeper says "CALL" with high score (80.0)
        # 2. MTF Sentiment: Strong BEARISH trend on 15m/5m -> Should produce negative Sentiment Score
        
        bundle = MagicMock()
        bundle.entry_tf.is_valid = True
        bundle.mid_tf.is_valid = True
        bundle.high_tf.is_valid = True
        self.data_provider.get_mtf_bundle.return_value = bundle
        
        # Mock Bearish MTF
        def mock_calc(candles, **kwargs):
            if candles == bundle.entry_tf.candles:
                return {"adx": 20, "trend": "neutral"}
            return {"adx": 30, "trend": "bearish"} # 5m and 15m are bearish
            
        self.analyzer.calculate_indicators.side_effect = mock_calc
        
        # Gatekeeper technically approves CALL
        self.gatekeeper.decide.return_value = TradeDecision(
            accept=True, direction="call", score=80.0, confidence=0.8, 
            reason="Technical Buy", notes=[], risk_level="normal", confluence_count=3
        )
        
        # Weights: 60% Sentiment, 40% Technical
        self.reanalyzer.config.sentiment_weight = 0.6
        self.reanalyzer.config.technical_weight = 0.4
        
        # Analyze
        result = await self.reanalyzer.analyze("EURUSD", "call", 1, is_martingale=False)
        
        # Calculation:
        # Sentiment points: -40 (oppose_15m) -30 (oppose_5m) = -70.0
        # Final Score: (-70 * 0.6) + (80 * 0.4) = -42 + 32 = -10.0
        # Result should be REJECTED (Score -10.0 < 10.0 threshold)
        
        print(f"\n[Test Independent] Composite Score: {result.score}")
        print(f"[Test Independent] Action: {result.action}")
        print(f"[Test Independent] Reason: {result.reason}")
        
        self.assertEqual(result.action, "reject")
        self.assertIn("sentiment clash", result.reason.lower())

if __name__ == "__main__":
    unittest.main()
