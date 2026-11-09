"""Legacy compatibility exports; strategy orchestration is platform-owned."""
from trading_platform.strategies.otc.strategy_engine import (
    DEFAULT_STRATEGY_FAMILIES, StrategyEngine, StrategySlot, TradeDecision,
)
__all__ = ["DEFAULT_STRATEGY_FAMILIES", "StrategyEngine", "StrategySlot", "TradeDecision"]
