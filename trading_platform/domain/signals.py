"""Immutable strategy/model proposals."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID, uuid4

from .environment import TradingEnvironment
from .instruments import InstrumentId
from .time import require_utc


class SignalAction(str, Enum):
    ABSTAIN = "abstain"
    CALL = "call"
    PUT = "put"
    BUY = "buy"
    SELL = "sell"
    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class SignalProposal:
    strategy_id: str
    instrument: InstrumentId
    environment: TradingEnvironment
    action: SignalAction
    confidence: Decimal
    decision_at: datetime
    expires_at: datetime
    signal_id: UUID = field(default_factory=uuid4)
    model_version: str | None = None
    config_version: str | None = None
    features: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("strategy_id must not be empty")
        if not self.confidence.is_finite() or not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be finite and within [0, 1]")
        require_utc(self.decision_at, "decision_at")
        require_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.decision_at:
            raise ValueError("expires_at must be later than decision_at")
        object.__setattr__(self, "strategy_id", self.strategy_id.strip())
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))
