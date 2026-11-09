"""
Unit tests for StrategyEngine.record_result() wiring and primary vs martingale accounting split.
"""
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from trading_platform.legacy.iqoption_bot.strategy_engine import StrategyEngine, StrategySlot
from trading_platform.legacy.iqoption_bot.strategies.mhi_strategy import MHIStrategy
from trading_platform.legacy.iqoption_bot.strategies.indicator_strategy import IndicatorStrategy
from trading_platform.legacy.iqoption_bot.result_checker import ResultChecker


class TestStrategySlotAccounting(unittest.TestCase):
    """Tests for StrategySlot primary vs martingale tracking separation and effective_weight."""

    def setUp(self):
        self.slot = StrategySlot(strategy=MHIStrategy(), weight=1.0)

    def test_primary_and_martingale_separation(self):
        """Primary and martingale outcomes must increment separate fields."""
        # Primary trades
        self.slot.wins += 2
        self.slot.losses += 1
        self.slot.ties += 1

        # Martingale trades
        self.slot.martingale_wins += 3
        self.slot.martingale_losses += 2
        self.slot.martingale_ties += 1

        self.assertEqual(self.slot.wins, 2)
        self.assertEqual(self.slot.losses, 1)
        self.assertEqual(self.slot.ties, 1)
        self.assertEqual(self.slot.total_primary_trades, 4)

        self.assertEqual(self.slot.martingale_wins, 3)
        self.assertEqual(self.slot.martingale_losses, 2)
        self.assertEqual(self.slot.martingale_ties, 1)
        self.assertEqual(self.slot.total_martingale_trades, 6)

        self.assertEqual(self.slot.total_trades, 10)
        # Primary win rate = 2 / 3 = 0.6667
        self.assertAlmostEqual(self.slot.win_rate, 2 / 3, places=4)
        # Martingale win rate = 3 / 5 = 0.60
        self.assertAlmostEqual(self.slot.martingale_win_rate, 0.60, places=4)

    def test_effective_weight_ignores_martingale_trades(self):
        """Effective weight must read ONLY from primary trade stats."""
        # Warm up martingale trades to > 20
        self.slot.martingale_wins = 25
        self.slot.martingale_losses = 5
        # Primary trades stay < 20
        self.slot.wins = 2
        self.slot.losses = 1

        self.assertEqual(self.slot.total_primary_trades, 3)
        self.assertEqual(self.slot.total_martingale_trades, 30)
        # Cold start because total_primary_trades < 20 -> should return base weight 1.0
        self.assertEqual(self.slot.effective_weight, 1.0)

    def test_effective_weight_threshold_scaling(self):
        """Effective weight must scale based on win_rate once total_primary_trades >= 20."""
        # 1. Strong performance (15 wins, 5 losses = 75% WR >= 60%) -> 1.5x multiplier
        self.slot.wins = 15
        self.slot.losses = 5
        self.assertEqual(self.slot.total_primary_trades, 20)
        self.assertAlmostEqual(self.slot.win_rate, 0.75, places=4)
        self.assertEqual(self.slot.effective_weight, 1.5)

        # 2. Moderate performance (11 wins, 9 losses = 55% WR) -> 1.2x multiplier
        self.slot.wins = 11
        self.slot.losses = 9
        self.assertEqual(self.slot.effective_weight, 1.2)

        # 3. Baseline performance (10 wins, 10 losses = 50% WR) -> 1.0x multiplier
        self.slot.wins = 10
        self.slot.losses = 10
        self.assertEqual(self.slot.effective_weight, 1.0)

        # 4. Weak performance (8 wins, 12 losses = 40% WR) -> 0.6x multiplier
        self.slot.wins = 8
        self.slot.losses = 12
        self.assertEqual(self.slot.effective_weight, 0.6)

        # 5. Poor performance (5 wins, 15 losses = 25% WR < 40%) -> 0.3x multiplier
        self.slot.wins = 5
        self.slot.losses = 15
        self.assertEqual(self.slot.effective_weight, 0.3)

    def test_ties_count_towards_warmup_gate_but_excluded_from_winrate(self):
        """Ties increment total_primary_trades but are excluded from win_rate denominator."""
        self.slot.wins = 12
        self.slot.losses = 4
        self.slot.ties = 4  # Total = 20
        self.assertEqual(self.slot.total_primary_trades, 20)
        # Decided = 12 + 4 = 16. WR = 12 / 16 = 75% -> 1.5x
        self.assertAlmostEqual(self.slot.win_rate, 0.75, places=4)
        self.assertEqual(self.slot.effective_weight, 1.5)


class TestStrategyEngineRecordResult(unittest.TestCase):
    """Tests for StrategyEngine.record_result()."""

    def setUp(self):
        self.engine = StrategyEngine()
        self.engine.register(MHIStrategy(), weight=1.0)
        self.engine.register(IndicatorStrategy(), weight=1.2)

    def test_record_result_primary(self):
        """record_result with is_martingale=False updates primary stats."""
        self.engine.record_result("MHI", "win", is_martingale=False)
        self.engine.record_result("MHI", "loss", is_martingale=False)
        self.engine.record_result("MHI", "tie", is_martingale=False)

        slot = self.engine.strategies["MHI"]
        self.assertEqual(slot.wins, 1)
        self.assertEqual(slot.losses, 1)
        self.assertEqual(slot.ties, 1)
        self.assertEqual(slot.martingale_wins, 0)

    def test_record_result_martingale(self):
        """record_result with is_martingale=True updates martingale stats."""
        self.engine.record_result("MHI", "win", is_martingale=True)
        self.engine.record_result("MHI", "loss", is_martingale=True)

        slot = self.engine.strategies["MHI"]
        self.assertEqual(slot.wins, 0)
        self.assertEqual(slot.losses, 0)
        self.assertEqual(slot.martingale_wins, 1)
        self.assertEqual(slot.martingale_losses, 1)

    def test_case_insensitive_strategy_lookup(self):
        """record_result should find strategy slot regardless of case."""
        self.engine.record_result("mhi", "win", is_martingale=False)
        slot = self.engine.strategies["MHI"]
        self.assertEqual(slot.wins, 1)


class TestResultCheckerWiringAndIdempotency(unittest.IsolatedAsyncioTestCase):
    """Tests for ResultChecker wiring to StrategyEngine with idempotency guards."""

    def setUp(self):
        self.engine = StrategyEngine()
        self.engine.register(MHIStrategy(), weight=1.0)

        # Mock API worker
        self.mock_worker = MagicMock()
        self.mock_worker.scanner = MagicMock()
        self.mock_worker.scanner.strategy_engine = self.engine
        self.mock_worker.logger = MagicMock()
        self.mock_worker.confidence_tracker = MagicMock()
        self.mock_worker.session_manager = None
        self.mock_worker.martingale_enabled = False
        self.mock_worker.active_martingale_series = {}

        self.checker = ResultChecker(self.mock_worker)

    async def test_handle_result_records_primary_win(self):
        """_handle_result must invoke engine.record_result and set result_recorded flag."""
        trade_info = {
            'asset': 'EURUSD-OTC',
            'direction': 'call',
            'amount': 10.0,
            'martingale_step': 0,
            'winning_strategy': 'MHI',
            'result_method': 'api',
        }

        await self.checker._handle_result(1001, trade_info, "win", 8.5, 108.5)

        slot = self.engine.strategies["MHI"]
        self.assertEqual(slot.wins, 1)
        self.assertEqual(slot.martingale_wins, 0)
        self.assertTrue(trade_info.get('result_recorded', False))

    async def test_handle_result_idempotency_guard(self):
        """Calling _handle_result twice for the same trade must NOT double count stats."""
        trade_info = {
            'asset': 'EURUSD-OTC',
            'direction': 'call',
            'amount': 10.0,
            'martingale_step': 0,
            'winning_strategy': 'MHI',
            'result_method': 'api',
        }

        # First resolution
        await self.checker._handle_result(1002, trade_info, "win", 8.5, 108.5)
        # Second resolution attempt (retry or duplicate invocation)
        await self.checker._handle_result(1002, trade_info, "win", 8.5, 108.5)

        slot = self.engine.strategies["MHI"]
        self.assertEqual(slot.wins, 1)  # Must be 1, NOT 2!

    async def test_handle_result_records_martingale_step(self):
        """_handle_result must record martingale step trades into martingale fields."""
        trade_info = {
            'asset': 'EURUSD-OTC',
            'direction': 'call',
            'amount': 22.0,
            'martingale_step': 1,
            'winning_strategy': 'MHI',
            'result_method': 'api',
        }

        await self.checker._handle_result(1003, trade_info, "win", 18.7, 127.2)

        slot = self.engine.strategies["MHI"]
        self.assertEqual(slot.wins, 0)
        self.assertEqual(slot.martingale_wins, 1)


if __name__ == '__main__':
    unittest.main()
