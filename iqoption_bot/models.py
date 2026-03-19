"""
Data models and enums for the trading bot.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


class SizingMethod(Enum):
    """Position sizing methods."""
    FIXED_AMOUNT = "fixed_amount"
    FIXED_PERCENTAGE = "fixed_percentage"
    FRACTIONAL_KELLY = "fractional_kelly"


@dataclass
class TradeSignal:
    """Represents a parsed trade signal."""
    asset: str
    direction: str  # "call" or "put"
    duration: int   # minutes
    entry_time: Optional[datetime] = None  # Scheduled entry time
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TradeRequest:
    """Request to place a trade via the API worker."""
    signal: TradeSignal
    ai_confidence: float = 1.0
    reasoning: str = ""
    skip_gatekeeper: bool = False  # Scanner signals already passed gatekeeper

    # Martingale fields
    martingale_step: int = 0  # 0 = original trade, 1-3 = recovery steps
    martingale_amount: Optional[float] = None  # Override amount for martingale
    martingale_series_id: Optional[str] = None  # Links trades in same series
    source: str = "telegram"  # "scanner" or "telegram" to select correct gatekeeper
    strategy_used: str = "" # The exact strategy name that fired
    
    # Analysis context for logic/fingerprinting
    indicators: dict = field(default_factory=dict)
    indicators_5m: Optional[dict] = None
    indicators_15m: Optional[dict] = None
    score: float = 0.0
    engine_decision: Optional[Any] = None  # Full decision from StrategyEngine
    use_mhi: bool = False
    mhi_strategy: str = "mhi"
    candles: Optional[List[Dict[str, float]]] = None

    # Sprint 4: Analytical metadata for fingerprinting
    quality_score: Optional[float] = None
    regime: Optional[str] = None

    def __lt__(self, other):
        """Tie-breaker for priority queue comparison."""
        if not isinstance(other, TradeRequest):
            return NotImplemented
        # Compare by timestamp of signal as a last resort
        return self.signal.timestamp < other.signal.timestamp

