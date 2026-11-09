"""Capability-based application ports.

Ports remain deliberately narrow: binary-option execution has materially
different semantics from spot and derivatives execution.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from trading_platform.brokers.iqoption.execution import (
        BinaryOrderCommand,
        BinaryOrderSubmission,
    )


@runtime_checkable
class BinaryExecutionPort(Protocol):
    """Submit a fixed-expiry binary-option order."""

    async def place_binary_order(
        self, command: "BinaryOrderCommand"
    ) -> "BinaryOrderSubmission": ...
