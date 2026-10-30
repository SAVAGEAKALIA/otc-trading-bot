"""Deterministic conversion of proposals and state into risk authority."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_platform.domain.risk import RiskDecision
from trading_platform.domain.signals import SignalProposal
from trading_platform.domain.time import require_utc

from .policies import RiskLimits, evaluate_policies
from .state import RiskState


@dataclass(frozen=True, slots=True)
class RiskRequest:
    signal: SignalProposal
    quantity: Decimal
    reference_price: Decimal
    requested_leverage: Decimal = Decimal("1")
    liquidation_buffer_fraction: Decimal | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.reference_price <= 0:
            raise ValueError("reference price must be positive")
        if self.requested_leverage <= 0:
            raise ValueError("requested leverage must be positive")
        if self.liquidation_buffer_fraction is not None and not (
            Decimal("0") <= self.liquidation_buffer_fraction <= Decimal("1")
        ):
            raise ValueError("liquidation buffer fraction must be in [0, 1]")


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def evaluate(
        self, request: RiskRequest, state: RiskState, *, now: datetime
    ) -> RiskDecision:
        require_utc(now, "now")
        reasons = evaluate_policies(request, state, self.limits, now)
        if reasons:
            return RiskDecision.rejected(
                signal_id=request.signal.signal_id,
                environment=request.signal.environment,
                reasons=reasons,
            )
        return RiskDecision.approved(
            signal_id=request.signal.signal_id,
            environment=request.signal.environment,
            limits_snapshot=self.limits.snapshot(),
        )
