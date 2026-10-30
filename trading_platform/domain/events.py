"""Common immutable event envelope."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID, uuid4

from .environment import TradingEnvironment
from .time import require_utc


@dataclass(frozen=True, slots=True)
class DomainEvent:
    name: str
    environment: TradingEnvironment
    occurred_at: datetime
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: UUID = field(default_factory=uuid4)
    schema_version: int = 1
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("event name must not be empty")
        require_utc(self.occurred_at, "occurred_at")
        require_utc(self.received_at, "received_at")
        if self.received_at < self.occurred_at:
            raise ValueError("received_at cannot precede occurred_at")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

