from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

@dataclass
class StrategyResult:
    score: float
    direction: str
    confidence: float
    reasons: List[str]
    warnings: List[str]
    should_trade: bool
    confluence: int = 0
    calibrated_win_probability: Optional[float] = None
    calibration_id: Optional[str] = None

    def __post_init__(self) -> None:
        if (self.calibrated_win_probability is None) != (self.calibration_id is None):
            raise ValueError("calibrated probability and calibration ID must appear together")
        if self.calibrated_win_probability is not None and not (
            0.0 <= self.calibrated_win_probability <= 1.0
        ):
            raise ValueError("calibrated probability must be in [0, 1]")

class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""
    
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        """Perform market analysis and return a StrategyResult."""
        pass
