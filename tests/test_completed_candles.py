"""
Unit tests for completed-bar access and look-ahead bias elimination across all 11 strategies.
"""
import unittest
import time
from trading_platform.legacy.iqoption_bot.data_provider import get_completed_candles
from trading_platform.legacy.iqoption_bot.strategies.indicator_strategy import IndicatorStrategy
from trading_platform.legacy.iqoption_bot.strategies.mhi_strategy import MHIStrategy
from trading_platform.legacy.iqoption_bot.strategies.ccv2_strategy import CCV2Strategy
from trading_platform.legacy.iqoption_bot.strategies.adaptive_strategy import AdaptiveStrategy
from trading_platform.legacy.iqoption_bot.strategies.rubber_band_strategy import RubberBandStrategy
from trading_platform.legacy.iqoption_bot.strategies.apex_exhaustion_strategy import ApexExhaustionStrategy
from trading_platform.legacy.iqoption_bot.strategies.momentum_cascade import MomentumCascadeStrategy
from trading_platform.legacy.iqoption_bot.strategies.compression_breakout import CompressionBreakoutStrategy
from trading_platform.legacy.iqoption_bot.strategies.late_candle_sniper import LateCandleSniperStrategy
from trading_platform.legacy.iqoption_bot.strategies.exhaustion_fade import ExhaustionFadeStrategy
from trading_platform.legacy.iqoption_bot.strategies.squeeze_strategy import SqueezeBreakoutStrategy


class TestCompletedCandlesAccessor(unittest.TestCase):
    """Tests for get_completed_candles() accessor in data_provider.py."""

    def test_empty_or_insufficient_candles(self):
        """Should return empty list if candles list is empty or smaller than min_required."""
        self.assertEqual(get_completed_candles([]), [])
        candles = [{'open': 1.0, 'close': 1.1}]
        self.assertEqual(get_completed_candles(candles, min_required=2), [])

    def test_strips_live_forming_candle(self):
        """Should slice off the last element if it is a live forming candle."""
        now = time.time()
        c1 = {'open': 1.0, 'close': 1.1, 'from': now - 240, 'at': now - 240}
        c2 = {'open': 1.1, 'close': 1.2, 'from': now - 120, 'at': now - 120}
        c3_forming = {'open': 1.2, 'close': 0.5, 'from': now - 10, 'at': now - 10}

        raw = [c1, c2, c3_forming]
        completed = get_completed_candles(raw, min_required=1)
        self.assertEqual(len(completed), 2)
        self.assertEqual(completed[-1], c2)

    def test_idempotency_on_already_completed(self):
        """Should not drop a second candle if the input list is already completed."""
        now = time.time()
        c1 = {'open': 1.0, 'close': 1.1, 'from': now - 360, 'at': now - 360}
        c2 = {'open': 1.1, 'close': 1.2, 'from': now - 240, 'at': now - 240}
        # c2 ended at now - 120, which is > 120s in the past

        already_completed = [c1, c2]
        res = get_completed_candles(already_completed, min_required=1)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[-1], c2)


class TestStrategyCompletedBarIsolation(unittest.TestCase):
    """Verifies that all 11 strategies evaluate against second-to-last candle, ignoring a forming last candle."""

    def setUp(self):
        now = time.time()
        # Build 30 baseline 2m candles (closed)
        self.base_candles = []
        base_price = 1.1000
        for i in range(30):
            t = now - (30 - i) * 120
            # Gradual uptrend
            op = base_price + i * 0.0002
            cl = op + 0.00015
            hi = cl + 0.00005
            lo = op - 0.00005
            self.base_candles.append({
                'open': op, 'close': cl, 'max': hi, 'min': lo,
                'high': hi, 'low': lo, 'volume': 100,
                'from': t, 'at': t
            })

        # Create a 31st candle that is a massive, contradictory spike/crash (forming)
        t_forming = now - 5
        last_op = self.base_candles[-1]['close']
        self.forming_candle = {
            'open': last_op, 'close': last_op - 0.0500, 'max': last_op + 0.0010, 'min': last_op - 0.0510,
            'high': last_op + 0.0010, 'low': last_op - 0.0510, 'volume': 9999,
            'from': t_forming, 'at': t_forming
        }
        self.raw_with_forming = self.base_candles + [self.forming_candle]

    def test_indicator_strategy_ignores_forming_candle(self):
        strat = IndicatorStrategy()
        ind_base = {'trend': 'bullish', 'adx': 30.0, 'ema_14': 1.09, 'candle_close': 1.105, 'rsi': 60.0, 'macd_histogram': 0.001, 'stoch_k': 60, 'stoch_d': 50}
        res_base = strat.analyze(self.base_candles, indicators_2m=ind_base)
        res_raw = strat.analyze(self.raw_with_forming, indicators_2m=ind_base)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_mhi_strategy_ignores_forming_candle(self):
        strat = MHIStrategy(variant='mhi')
        res_base = strat.analyze(self.base_candles)
        res_raw = strat.analyze(self.raw_with_forming)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_ccv2_strategy_ignores_forming_candle(self):
        strat = CCV2Strategy()
        res_base = strat.analyze(self.base_candles)
        res_raw = strat.analyze(self.raw_with_forming)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_adaptive_strategy_ignores_forming_candle(self):
        strat = AdaptiveStrategy()
        res_base = strat.analyze(self.base_candles)
        res_raw = strat.analyze(self.raw_with_forming)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_rubber_band_strategy_ignores_forming_candle(self):
        strat = RubberBandStrategy()
        ind_2m = {'rsi': 25.0, 'bb_position': 0.02, 'stoch_k': 15.0, 'macd_histogram': 0.001, 'adx': 25.0}
        ind_5m = {'trend': 'bullish'}
        ind_15m = {'trend': 'bullish'}
        res_base = strat.analyze(self.base_candles, indicators_2m=ind_2m, indicators_5m=ind_5m, indicators_15m=ind_15m)
        res_raw = strat.analyze(self.raw_with_forming, indicators_2m=ind_2m, indicators_5m=ind_5m, indicators_15m=ind_15m)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_apex_exhaustion_strategy_ignores_forming_candle(self):
        strat = ApexExhaustionStrategy()
        ind_2m = {'rsi': 82.0, 'bb_position': 0.98, 'adx': 42.0}
        ind_prev = {'adx': 39.0}
        ind_15m = {'trend': 'neutral'}
        res_base = strat.analyze(self.base_candles, indicators_2m=ind_2m, indicators_2m_prev=ind_prev, indicators_15m=ind_15m)
        res_raw = strat.analyze(self.raw_with_forming, indicators_2m=ind_2m, indicators_2m_prev=ind_prev, indicators_15m=ind_15m)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_momentum_cascade_ignores_forming_candle(self):
        strat = MomentumCascadeStrategy()
        res_base = strat.analyze(self.base_candles)
        res_raw = strat.analyze(self.raw_with_forming)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_compression_breakout_ignores_forming_candle(self):
        strat = CompressionBreakoutStrategy()
        res_base = strat.analyze(self.base_candles)
        res_raw = strat.analyze(self.raw_with_forming)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_late_candle_sniper_ignores_forming_candle(self):
        strat = LateCandleSniperStrategy()
        res_base = strat.analyze(self.base_candles)
        res_raw = strat.analyze(self.raw_with_forming)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_exhaustion_fade_ignores_forming_candle(self):
        strat = ExhaustionFadeStrategy()
        ind_2m = {'rsi': 50.0, 'stoch_k': 20.0, 'bb_position': 0.05, 'adx': 20.0}
        res_base = strat.analyze(self.base_candles, indicators_2m=ind_2m)
        res_raw = strat.analyze(self.raw_with_forming, indicators_2m=ind_2m)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)

    def test_squeeze_strategy_ignores_forming_candle(self):
        strat = SqueezeBreakoutStrategy()
        ind_2m = {'volatility_regime': 'normal', 'bb_width_pct': 0.2, 'in_squeeze': True, 'rsi': 50.0, 'sma_20': 1.1000, 'macd_histogram': 0.001}
        ind_5m = {'trend': 'bullish'}
        res_base = strat.analyze(self.base_candles, indicators_2m=ind_2m, indicators_5m=ind_5m)
        res_raw = strat.analyze(self.raw_with_forming, indicators_2m=ind_2m, indicators_5m=ind_5m)
        self.assertEqual(res_base.direction, res_raw.direction)
        self.assertEqual(res_base.score, res_raw.score)


if __name__ == '__main__':
    unittest.main()
