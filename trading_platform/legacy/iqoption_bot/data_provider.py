"""Legacy compatibility exports; implementation lives under trading_platform."""

from trading_platform.market_data.provider import (
    CandleData,
    MTFBundle,
    MarketDataProvider,
    get_completed_candles,
)

__all__ = ["CandleData", "MTFBundle", "MarketDataProvider", "get_completed_candles"]
