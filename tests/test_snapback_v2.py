import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

# Import scanner and analytics components
from trading_platform.legacy.iqoption_bot.scanner import OTCScanner, ScannerConfig, ScannerTradeMode
from trading_platform.legacy.iqoption_bot.analytics import SignalGatekeeper, SignalScore

class TestSnapbackV2(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.config = ScannerConfig()
        # Default config should now have V2 values
        self.mock_api = MagicMock()
        self.mock_data_provider = MagicMock()
        # Mock get_mtf_bundle to be an AsyncMock to avoid 'object MagicMock can't be used in await'
        self.mock_data_provider.get_mtf_bundle = AsyncMock()
        
        self.mock_analyzer = MagicMock()
        self.mock_pattern_analyzer = MagicMock()
        self.mock_gatekeeper = MagicMock()
        
        self.scanner = OTCScanner(
            self.mock_api, 
            self.mock_data_provider, 
            self.mock_analyzer, 
            self.mock_pattern_analyzer, 
            self.mock_gatekeeper, 
            self.config
        )

    def test_config_v2_defaults(self):
        """Verify that ScannerConfig has the V2 hard-coded math defaults."""
        print("\n🧪 Testing ScannerConfig V2 Defaults...")
        self.assertEqual(self.config.expansion_trap_max, 1.2)
        self.assertEqual(self.config.wick_magnet_max, 0.4)
        self.assertEqual(self.config.quality_min_score, 70)
        self.assertTrue(self.config.calm_confluence_gate)
        print("   ✅ Config defaults validated.")

    async def test_expansion_veto_logic(self):
        """Verify the 1.2x Expansion Veto in scanner._analyze_asset."""
        print("\n🧪 Testing Expansion Veto (1.2x Gate)...")
        
        # Mock MTF bundle with an expansion candle
        mock_bundle = MagicMock()
        self.mock_data_provider.get_mtf_bundle.return_value = mock_bundle
        
        # Entry TF candles: prev=10 body, last=15 body (1.5x expansion > 1.2)
        mock_bundle.entry_tf.candles = [
            {'o': 100, 'c': 110, 'h': 112, 'l': 98}, # prev (10)
            {'o': 110, 'c': 125, 'h': 127, 'l': 108} # last (15) -> 1.5x
        ]
        
        # Mock engine decision
        mock_decision = MagicMock()
        mock_decision.direction = "call"
        
        # Patch quality score to bypass Gate 4 later
        with patch.object(self.scanner, '_calculate_quality_score', return_value=(80, 0.7, [])):
            res = await self.scanner._analyze_asset("EURUSD", mock_bundle, mock_decision)
            self.assertIsNone(res, "Should return None due to expansion trap (1.5x)")
            print("   ✅ Expansion trap (1.5x) correctly rejected.")

    async def test_wick_magnet_lock(self):
        """Verify the 0.4x Wick Magnet Lock in scanner._analyze_asset."""
        print("\n🧪 Testing Wick Magnet Lock (0.4x Gate)...")
        
        mock_bundle = MagicMock()
        self.mock_data_provider.get_mtf_bundle.return_value = mock_bundle
        
        # Direction CALL with long LOWER wick: low=80, open=90, close=95, high=100 (Total 20)
        # Lower wick = 90 - 80 = 10. 10/20 = 0.5 (> 0.4)
        mock_bundle.entry_tf.candles = [{'o': 90, 'c': 95, 'h': 100, 'l': 80}]
        
        mock_decision = MagicMock()
        mock_decision.direction = "call"
        
        res = await self.scanner._analyze_asset("EURUSD", mock_bundle, mock_decision)
        self.assertIsNone(res, "Should return None due to Wick Magnet (0.5 ratio)")
        print("   ✅ Wick Magnet (>0.4) correctly rejected.")

    def test_gravity_bias_boost(self):
        """Verify PUT Gravity Bias boost in score calculation."""
        print("\n🧪 Testing PUT Gravity Bias (+15 Boost)...")
        
        # Scenario: Triple-aligned PUT
        # Return signature: (score, confidence, notes)
        score, confidence, notes = self.scanner._calculate_quality_score(
            direction="put",
            indicators_2m={"trend": "bearish", "rsi": 50},
            indicators_5m={"trend": "bearish"},
            indicators_15m={"trend": "bearish"},
            candles=[],
            engine_score=-80.0,
            engine_confidence=0.8
        )
        
        has_gravity_note = any("Gravity Bias" in n for n in notes)
        self.assertTrue(has_gravity_note)
        print(f"   ✅ Gravity Bias detected. Final Score: {score}")

    def test_gatekeeper_rsi_extreme(self):
        """Verify SignalGatekeeper rejects RSI extremes."""
        print("\n🧪 Testing Gatekeeper RSI Extreme Veto...")
        
        gatekeeper = SignalGatekeeper(mode="strict")
        gatekeeper.alpha_hours_enabled = False # Bypass alpha hours for this test
        mock_analyzer = MagicMock()
        
        # Scenario: RSI 25
        indicators = {"rsi": 25.0, "volatility_regime": "normal"}
        score_obj = SignalScore(score=80.0, confidence=0.8, direction="call", reasons=[], warnings=[], should_trade=True)
        
        decision = gatekeeper.decide(mock_analyzer, indicators, pre_calculated_score=score_obj)
        self.assertFalse(decision.accept)
        self.assertIn("RSI Extreme", decision.reason)
        print("   ✅ Gatekeeper rejected RSI 25 correctly.")

if __name__ == "__main__":
    unittest.main()
