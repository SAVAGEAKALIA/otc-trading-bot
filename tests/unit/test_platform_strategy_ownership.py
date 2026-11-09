from trading_platform.legacy.iqoption_bot import data_provider as legacy_data
from trading_platform.legacy.iqoption_bot.strategies import base as legacy_base
from trading_platform.legacy.iqoption_bot.strategies import indicator_strategy as legacy_indicator
from trading_platform.market_data import provider
from trading_platform.strategies.otc.implementations import base, indicator_strategy


def test_market_data_is_platform_owned_with_legacy_identity():
    assert legacy_data.MarketDataProvider is provider.MarketDataProvider
    assert legacy_data.get_completed_candles is provider.get_completed_candles


def test_strategy_contracts_and_implementations_are_platform_owned():
    assert legacy_base.BaseStrategy is base.BaseStrategy
    assert legacy_base.StrategyResult is base.StrategyResult
    assert legacy_indicator.IndicatorStrategy is indicator_strategy.IndicatorStrategy
