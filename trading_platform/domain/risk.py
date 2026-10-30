"""Risk decisions tied to an exact signal and environment."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID, uuid4

from .environment import TradingEnvironment


@dataclass(frozen=True, slots=True)
class RiskDecision:
    signal_id: UUID
    environment: TradingEnvironment
    is_approved: bool
    limits_snapshot: Mapping[str, Any]
    reasons: tuple[str, ...] = ()
    decision_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.is_approved and not self.limits_snapshot:
            raise ValueError("approved risk decisions require a limits snapshot")
        if not self.is_approved and not self.reasons:
            raise ValueError("rejected risk decisions require at least one reason")
        object.__setattr__(
            self, "limits_snapshot", MappingProxyType(dict(self.limits_snapshot))
        )
        object.__setattr__(
            self,
            "reasons",
            tuple(reason.strip() for reason in self.reasons if reason.strip()),
        )

    @classmethod
    def approved(
        cls,
        *,
        signal_id: UUID,
        environment: TradingEnvironment,
        limits_snapshot: Mapping[str, Any],
    ) -> "RiskDecision":
        return cls(
            signal_id=signal_id,
            environment=environment,
            is_approved=True,
            limits_snapshot=limits_snapshot,
        )

    @classmethod
    def rejected(
        cls,
        *,
        signal_id: UUID,
        environment: TradingEnvironment,
        reasons: tuple[str, ...],
    ) -> "RiskDecision":
        return cls(
            signal_id=signal_id,
            environment=environment,
            is_approved=False,
            limits_snapshot={},
            reasons=reasons,
        )

