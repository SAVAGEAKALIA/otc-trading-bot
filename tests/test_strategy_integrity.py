import time

from trading_platform.legacy.iqoption_bot.analytics import MarketAnalyzer
from trading_platform.legacy.iqoption_bot.strategy_engine import StrategyEngine
from trading_platform.legacy.iqoption_bot.strategies.base import StrategyResult
from trading_platform.legacy.iqoption_bot.strategies.compression_breakout import (
    CompressionBreakoutStrategy,
)
from trading_platform.legacy.iqoption_bot.strategies.mhi_strategy import MHIStrategy


class StubStrategy:
    def __init__(self, name, direction="call", score=80.0):
        self.name = name
        self.direction = direction
        self.score = score
        self.calls = 0

    def analyze(self, candles, **kwargs):
        self.calls += 1
        return StrategyResult(
            score=self.score if self.direction == "call" else -self.score,
            direction=self.direction,
            confidence=0.80,
            reasons=["stub"],
            warnings=[],
            should_trade=True,
        )


def test_unknown_active_strategy_fails_closed():
    strategy = StubStrategy("Known")
    engine = StrategyEngine()
    engine.register(strategy)

    decision = engine.evaluate([], active_strategies=["Typo"])

    assert not decision.should_trade
    assert strategy.calls == 0
    assert "registered" in decision.warnings[0]


def test_correlated_votes_do_not_pass_independent_family_gate():
    engine = StrategyEngine()
    engine.register(StubStrategy("MHI"))
    engine.register(StubStrategy("Majority"))

    decision = engine.evaluate(
        [],
        active_strategies=["MHI", "Majority"],
        min_agreement=2,
        min_independent_families=2,
    )

    assert not decision.should_trade
    assert decision.confluence_count == 2
    assert decision.independent_family_count == 1
    assert decision.agreeing_families == ["candle_reversal"]


def test_distinct_strategy_families_can_pass():
    engine = StrategyEngine()
    engine.register(StubStrategy("Indicators"))
    engine.register(StubStrategy("Late Candle Sniper"))

    decision = engine.evaluate(
        [],
        active_strategies=["Indicators", "Late Candle Sniper"],
        min_agreement=2,
        min_independent_families=2,
    )

    assert decision.should_trade
    assert decision.independent_family_count == 2


def test_live_lose_spelling_updates_loss_stats():
    engine = StrategyEngine()
    engine.register(StubStrategy("Indicators"))

    engine.record_result("Indicators", "lose")

    assert engine.strategies["Indicators"].losses == 1


def _candle(timestamp, price, candle_range, bullish=True):
    body = candle_range * 0.8
    if bullish:
        open_price = price
        close_price = price + body
    else:
        open_price = price + body
        close_price = price
    return {
        "from": timestamp,
        "open": open_price,
        "close": close_price,
        "min": price - candle_range * 0.1,
        "max": price + candle_range * 0.9,
        "volume": 0,
    }


def test_compression_baseline_excludes_expansion_candle():
    start = int(time.time()) - 26 * 120 - 3600
    candles = []
    price = 100.0
    for index in range(20):
        candles.append(_candle(start + index * 120, price, 1.0))
        price += 0.1
    for index in range(20, 25):
        candles.append(_candle(start + index * 120, price, 0.5))
        price += 0.1
    candles.append(_candle(start + 25 * 120, price, 0.65))

    result = CompressionBreakoutStrategy().analyze(candles)

    assert result.should_trade
    assert result.direction == "call"
    assert any("Expansion 1.3x" in reason for reason in result.reasons)


def test_mhi_doji_detection_is_scale_independent():
    start = int(time.time()) - 4 * 120 - 3600
    candles = [
        {
            "from": start + index * 120,
            "open": 100.0,
            "close": 100.001,
            "min": 99.95,
            "max": 100.05,
        }
        for index in range(3)
    ]

    result = MHIStrategy().analyze(candles)

    assert not result.should_trade
    assert result.direction == "neutral"


def test_indicator_payload_exposes_bollinger_width():
    start = int(time.time()) - 40 * 120 - 3600
    candles = [
        _candle(start + index * 120, 100.0 + index * 0.01, 0.5)
        for index in range(40)
    ]

    indicators = MarketAnalyzer().calculate_indicators(
        candles,
        symbol="TEST",
    )

    assert indicators is not None
    assert "bb_width_pct" in indicators
    assert indicators["bb_width_pct"] >= 0
