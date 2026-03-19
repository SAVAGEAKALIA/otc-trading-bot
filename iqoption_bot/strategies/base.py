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

class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""
    
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        """Perform market analysis and return a StrategyResult."""
        pass
