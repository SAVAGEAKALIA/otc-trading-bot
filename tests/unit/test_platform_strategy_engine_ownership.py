from trading_platform.legacy.iqoption_bot.strategy_engine import StrategyEngine as LegacyStrategyEngine
from trading_platform.strategies.otc.strategy_engine import StrategyEngine


def test_strategy_engine_is_platform_owned():
    assert LegacyStrategyEngine is StrategyEngine
