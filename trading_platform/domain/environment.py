"""Explicit trading-environment identity and compatibility checks."""

from enum import Enum


class TradingEnvironment(str, Enum):
    RESEARCH = "research"
    BACKTEST = "backtest"
    SHADOW = "shadow"
    PAPER = "paper"
    TESTNET = "testnet"
    MICRO_LIVE = "micro_live"
    LIVE = "live"


class EnvironmentMismatchError(ValueError):
    """Raised when records from different environments are combined."""


def ensure_same_environment(
    expected: TradingEnvironment,
    actual: TradingEnvironment,
) -> None:
    """Reject accidental crossover between research, test, and live state."""
    if expected is not actual:
        raise EnvironmentMismatchError(
            f"environment mismatch: expected {expected.value}, got {actual.value}"
        )

