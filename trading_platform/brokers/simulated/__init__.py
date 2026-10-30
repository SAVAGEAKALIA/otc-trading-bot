"""Deterministic broker used by backtests, replay, and paper tests."""

from .broker import SimulatedBroker
from .models import (
    BinaryDirection,
    BinaryOptionIntent,
    BinaryOptionOrder,
    ScriptedFailure,
    SimulatedBrokerConfig,
    SimulatedConnectionError,
    SimulatedEvent,
    SimulatedFill,
    SimulatedOrder,
    SimulatedTimeoutError,
)

__all__ = [
    "BinaryDirection",
    "BinaryOptionIntent",
    "BinaryOptionOrder",
    "ScriptedFailure",
    "SimulatedBroker",
    "SimulatedBrokerConfig",
    "SimulatedConnectionError",
    "SimulatedEvent",
    "SimulatedFill",
    "SimulatedOrder",
    "SimulatedTimeoutError",
]
