"""IQ Option broker integration."""

from .execution import (
    BinaryDirection,
    BinaryOrderCommand,
    BinaryOrderSubmission,
    IQOptionBinaryExecutionAdapter,
)
from .history import IQOptionClosedOptionsHistory, IQOptionHistoryAPI
from .api import IQOptionAPI, build_legacy_api
from .settlement import IQOptionClosedOptionsPort, IQOptionSettlementGateway

__all__ = [
    "BinaryDirection",
    "BinaryOrderCommand",
    "BinaryOrderSubmission",
    "IQOptionBinaryExecutionAdapter",
    "IQOptionClosedOptionsPort",
    "IQOptionSettlementGateway",
    "IQOptionClosedOptionsHistory",
    "IQOptionHistoryAPI",
    "IQOptionAPI",
    "build_legacy_api",
]
