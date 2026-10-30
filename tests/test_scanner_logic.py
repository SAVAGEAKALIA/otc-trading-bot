
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

class TestScannerLogic(unittest.IsolatedAsyncioTestCase):
    
    async def test_single_mode_queue_check(self):
        print("\n🧪 Testing Single Mode Queue Check...")
        
        # Import Worker
        from trading_platform.legacy.iqoption_bot.worker import APIWorker
        
        # Patches to prevent actual init/connecting
        with patch('trading_platform.legacy.iqoption_bot.worker.MartingaleManager'), \
             patch('trading_platform.legacy.iqoption_bot.worker.AssetResolver'), \
             patch('trading_platform.legacy.iqoption_bot.worker.ResultChecker'), \
             patch('trading_platform.legacy.iqoption_bot.worker.ConnectionManager'), \
             patch('trading_platform.legacy.iqoption_bot.worker.MarketDataProvider'), \
             patch('trading_platform.legacy.iqoption_bot.worker.OTCScanner') as MockScanner, \
             patch('trading_platform.legacy.iqoption_bot.worker.ConfidenceTracker'), \
             patch('trading_platform.legacy.iqoption_bot.worker.PatternAnalyzer'):
             
             # Setup mocks
             mock_api = MagicMock()
             mock_logger = MagicMock()
             mock_sizer = MagicMock()
             mock_analyzer = MagicMock()
             
             worker = APIWorker(mock_api, mock_logger, mock_sizer, mock_analyzer)
             
             # Setup worker state manually
             mock_scanner_instance = MockScanner.return_value
             # Need to set trade_mode on config inside scanner
             # Since it's mocked, we can just set attribute
             from trading_platform.legacy.iqoption_bot.scanner import ScannerTradeMode
             worker.scanner = mock_scanner_instance
             worker.scanner.config.trade_mode = ScannerTradeMode.SINGLE
             
             worker.active_trades = {}
             worker.active_martingale_series = {}
             # Ensure queue is empty initially
             # APIWorker init sets self.trade_queue = asyncio.Queue()
             
             # Test 1: Empty Queue
             can, reason = worker.can_place_trade(from_scanner=True)
             print(f"   [1] Empty Queue -> Allowed: {can} ({reason})")
             self.assertTrue(can, "Should be allowed with empty queue")
             
             # Test 2: Active Trade Exists
             worker.active_trades = {1: {'asset': 'EURUSD'}}
             can, reason = worker.can_place_trade(from_scanner=True)
             print(f"   [2] Active Trade -> Allowed: {can} ({reason})")
             self.assertFalse(can, "Should depend on active trades")
             worker.active_trades = {} # Reset
             
             # Test 3: Queue Has Pending Item (The Fix)
             pending_request = MagicMock()
             pending_request.signal.asset = "EURUSD-OTC"
             await worker.trade_queue.put(pending_request)
             can, reason = worker.can_place_trade(from_scanner=True)
             print(f"   [3] Queued Item -> Allowed: {can} ({reason})")
             self.assertFalse(can, "Should block if queue has items")
             self.assertIn("pending", reason.lower())
             
             # Test 4: Pending Execution Count (The NEW Fix)
             # Simulate queue processed but trade not yet active
             while not worker.trade_queue.empty():
                await worker.trade_queue.get()
                 
             worker.pending_execution_count = 1
             can, reason = worker.can_place_trade(from_scanner=True)
             print(f"   [4] Pending Execution Count -> Allowed: {can} ({reason})")
             self.assertFalse(can, "Should block if pending_execution_count > 0")
             self.assertIn("being processed", reason.lower())
             
             worker.pending_execution_count = 0
             can, reason = worker.can_place_trade(from_scanner=True)
             self.assertTrue(can, "Should allow if count is 0")

    async def test_tie_logic(self):
        print("\n🧪 Testing Tie Result Logic...")
        
        # Import Result Checker
        from trading_platform.legacy.iqoption_bot.result_checker import ResultChecker
        
        mock_worker = MagicMock()
        mock_worker.use_gatekeeper = True
        mock_worker.gatekeeper_telegram = MagicMock()
        mock_worker.gatekeeper_scanner = MagicMock()
        mock_worker.active_martingale_series = {}
        mock_worker.session_manager = None # Disable session manager to skip stats printing
        
        checker = ResultChecker(mock_worker)
        
        # Sim tie result
        trade_info = {'asset': 'EURUSD', 'direction': 'call', 'amount': 10, 'source': 'telegram'}
        await checker._handle_result(123, trade_info, 'tie', 0.0, 1000.0)
        
        # Verify gatekeeper NOT called
        mock_worker.gatekeeper_telegram.record_result.assert_not_called()
        print("   ✅ Tie result: Gatekeeper record_result NOT called")

    async def test_duration_selection(self):
        print("\n🧪 Testing Scanner Duration Selection...")
        from trading_platform.legacy.iqoption_bot.scanner import OTCScanner, ScannerConfig
        
        # Setup scanner with mock
        mock_api = MagicMock()
        mock_data_provider = MagicMock()
        mock_analyzer = MagicMock()
        mock_pattern_analyzer = MagicMock()
        mock_gatekeeper = MagicMock()
        
        config = ScannerConfig()
        config.dynamic_timeframe = True
        scanner = OTCScanner(mock_api, mock_data_provider, mock_analyzer, mock_pattern_analyzer, mock_gatekeeper, config)

        
        # Test Case 1: Normal Volatility, Decent Signal
        # At the configured base duration, ordinary aligned confluence stays
        # at 2m; only volatility and exceptional confidence alter it.
        dur = scanner._select_duration(
            volatility_regime="normal",
            confluence=4,
            mtf_5m_aligned=True,
            mtf_15m_aligned=False,
            confidence=0.65,
            score=65
        )
        print(f"   [1] Normal Vol, Confluence 4 -> Duration: {dur}m (Expected: 2m)")
        self.assertEqual(dur, 2)
        
        # Test Case 2: High Volatility, Strong Signal
        # Confluence 5 + Both MTF aligned -> 3m (capped for high vol)
        dur = scanner._select_duration(
            volatility_regime="high",
            confluence=5,
            mtf_5m_aligned=True,
            mtf_15m_aligned=True,
            confidence=0.85,
            score=85
        )
        print(f"   [2] High Vol, Confluence 5 -> Duration: {dur}m (Expected: 3m)")
        self.assertEqual(dur, 3)
        
        # Test Case 3: Extreme Volatility
        # Extreme volatility plus no higher-timeframe alignment is capped at 3m.
        dur = scanner._select_duration(
            volatility_regime="extreme",
            confluence=3,
            mtf_5m_aligned=False,
            mtf_15m_aligned=False,
            confidence=0.65,
            score=65
        )
        print(f"   [3] Extreme Vol -> Duration: {dur}m (Expected: 3m)")
        self.assertEqual(dur, 3)

        # Hybrid means every registered strategy, including ML_LSTM.  The
        # scanner must therefore request enough warm-up candles instead of
        # treating the literal word "hybrid" as a strategy name.
        config.scanner_strategy = "hybrid"
        config.active_strategies = []
        active_names = scanner._get_active_strategy_names()
        self.assertIn("ML_LSTM", active_names)
        self.assertNotIn("hybrid", active_names)
        self.assertTrue(scanner._needs_lstm_history())

        # Regime routing replaces hybrid with non-ML strategy groups.
        config.regime_routing_enabled = True
        self.assertFalse(
            scanner._needs_lstm_history(precision_triggered=False)
        )
        
        # Test Case 4: Weak Signal
        # Weak, unaligned signals receive extra time rather than a faster expiry.
        dur = scanner._select_duration(
            volatility_regime="normal",
            confluence=2,
            mtf_5m_aligned=False,
            mtf_15m_aligned=False,
            confidence=0.55,
            score=50
        )
        print(f"   [4] Weak Signal -> Duration: {dur}m (Expected: 3m)")
        self.assertEqual(dur, 3)

if __name__ == "__main__":
    unittest.main()
