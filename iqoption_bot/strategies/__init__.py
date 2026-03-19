"""
Trading strategy modules.

All strategies inherit from BaseStrategy and implement analyze().
"""
from .base import BaseStrategy, StrategyResult
from .indicator_strategy import IndicatorStrategy
from .mhi_strategy import MHIStrategy
from .ccv2_strategy import CCV2Strategy
from .adaptive_strategy import AdaptiveStrategy
from .rubber_band_strategy import RubberBandStrategy
from .apex_exhaustion_strategy import ApexExhaustionStrategy
from .momentum_cascade import MomentumCascadeStrategy
from .compression_breakout import CompressionBreakoutStrategy
from .late_candle_sniper import LateCandleSniperStrategy
from .exhaustion_fade import ExhaustionFadeStrategy

__all__ = [
    "BaseStrategy",
    "StrategyResult",
    "IndicatorStrategy",
    "MHIStrategy",
    "CCV2Strategy",
    "AdaptiveStrategy",
    "RubberBandStrategy",
    "ApexExhaustionStrategy",
    "MomentumCascadeStrategy",
    "CompressionBreakoutStrategy",
    "LateCandleSniperStrategy",
    "ExhaustionFadeStrategy",
]
