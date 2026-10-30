"""Legacy compatibility exports; canonical strategy contracts live in trading_platform."""
from trading_platform.strategies.otc.implementations.base import BaseStrategy, StrategyResult
__all__ = ["BaseStrategy", "StrategyResult"]
