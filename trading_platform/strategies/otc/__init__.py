"""IQ Option OTC compatibility workflow."""

from .reporting import OTCParityReport, build_otc_parity_report
from .shadow import (
    OTCCandidate,
    OTCShadowPolicy,
    OTCShadowResult,
    OTCShadowService,
    ShadowExecutionGateway,
)
from .implementations import (
    BaseStrategy, StrategyResult, IndicatorStrategy, MHIStrategy, CCV2Strategy,
    AdaptiveStrategy, RubberBandStrategy, ApexExhaustionStrategy,
    MomentumCascadeStrategy, CompressionBreakoutStrategy,
    LateCandleSniperStrategy, ExhaustionFadeStrategy, SqueezeBreakoutStrategy,
)
from .strategy_engine import DEFAULT_STRATEGY_FAMILIES, StrategyEngine, StrategySlot, TradeDecision

__all__ = [
    "OTCCandidate",
    "OTCShadowPolicy",
    "OTCShadowResult",
    "OTCShadowService",
    "ShadowExecutionGateway",
    "OTCParityReport",
    "build_otc_parity_report",
    "BaseStrategy", "StrategyResult", "IndicatorStrategy", "MHIStrategy",
    "CCV2Strategy", "AdaptiveStrategy", "RubberBandStrategy",
    "ApexExhaustionStrategy", "MomentumCascadeStrategy",
    "CompressionBreakoutStrategy", "LateCandleSniperStrategy",
    "ExhaustionFadeStrategy", "SqueezeBreakoutStrategy",
    "StrategyEngine", "StrategySlot",
    "TradeDecision", "DEFAULT_STRATEGY_FAMILIES",
]
