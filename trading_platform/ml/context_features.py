"""Compatibility exports for platform-owned market-context features."""

from trading_platform.research.context_features import (
    ALL_CONTEXT_FEATURES,
    CONTEXT_FEATURES,
    CONTEXT_SCHEMA_VERSION,
    LEGACY_CONTEXT_ALIASES,
    ContextPolicy,
    MarketContextProvider,
    candle_decision_ms,
    canonical_asset,
    epoch_ms,
    missing_context,
)

__all__ = [
    "ALL_CONTEXT_FEATURES",
    "CONTEXT_FEATURES",
    "CONTEXT_SCHEMA_VERSION",
    "LEGACY_CONTEXT_ALIASES",
    "ContextPolicy",
    "MarketContextProvider",
    "candle_decision_ms",
    "canonical_asset",
    "epoch_ms",
    "missing_context",
]
