"""Shadow-only OTC vertical slice through risk, OMS, and ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Quantity
from trading_platform.domain.orders import (
    BinaryDirection,
    BinaryOptionTerms,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from trading_platform.domain.risk import RiskDecision
from trading_platform.domain.signals import SignalAction, SignalProposal
from trading_platform.domain.time import require_utc
from trading_platform.execution.order_manager import BrokerOrderSnapshot, OrderManager
from trading_platform.risk.engine import RiskEngine, RiskRequest
from trading_platform.risk.state import RiskState
from trading_platform.storage.repository import LedgerOrder, LedgerRepository


@dataclass(frozen=True, slots=True)
class OTCCandidate:
    signal_id: UUID
    asset: str
    direction: BinaryDirection
    duration_minutes: int
    stake: Decimal
    payout_ratio: Decimal
    estimated_win_probability: Decimal | None
    confidence: Decimal
    decision_at: datetime
    strategy_id: str
    source: str
    calibration_version: str | None = None
    martingale_step: int = 0

    def __post_init__(self) -> None:
        require_utc(self.decision_at, "decision_at")
        if self.duration_minutes < 1:
            raise ValueError("duration must be positive")
        if self.stake <= 0:
            raise ValueError("stake must be positive")
        if not Decimal("0") < self.payout_ratio <= Decimal("1"):
            raise ValueError("payout ratio must be in (0, 1]")
        if self.estimated_win_probability is not None and not (
            Decimal("0") <= self.estimated_win_probability <= Decimal("1")
        ):
            raise ValueError("estimated win probability must be in [0, 1]")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be in [0, 1]")

    @property
    def normalized_asset(self) -> str:
        base = (
            self.asset.upper()
            .replace("-OTC", "")
            .replace("-OP", "")
            .replace("_OTC", "")
            .replace("OTC", "")
            .strip()
        )
        return f"{base}-OTC"

    @property
    def break_even_probability(self) -> Decimal:
        return Decimal("1") / (Decimal("1") + self.payout_ratio)

    @property
    def expectancy(self) -> Decimal | None:
        if self.estimated_win_probability is None:
            return None
        probability = self.estimated_win_probability
        return probability * self.payout_ratio - (Decimal("1") - probability)


@dataclass(frozen=True, slots=True)
class OTCShadowPolicy:
    min_payout_ratio: Decimal = Decimal("0.70")
    min_expectancy: Decimal = Decimal("0")
    signal_valid_for: timedelta = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class OTCShadowResult:
    signal: SignalProposal
    risk_decision: RiskDecision
    order: LedgerOrder | None
    expectancy: Decimal | None


class ShadowExecutionGateway:
    """Acknowledges shadow intents without holding any broker client."""

    async def submit_order(self, intent: OrderIntent) -> BrokerOrderSnapshot:
        if intent.environment is not TradingEnvironment.SHADOW:
            raise ValueError("shadow gateway refuses non-shadow orders")
        return BrokerOrderSnapshot(
            client_order_id=intent.client_order_id,
            broker_order_id=f"SHADOW-{intent.client_order_id}",
            status=OrderStatus.ACKNOWLEDGED,
        )

    async def get_order(self, client_order_id: str) -> BrokerOrderSnapshot | None:
        return None


class OTCShadowService:
    def __init__(
        self,
        repository: LedgerRepository,
        risk_engine: RiskEngine,
        policy: OTCShadowPolicy | None = None,
    ) -> None:
        self.repository = repository
        self.risk_engine = risk_engine
        self.policy = policy or OTCShadowPolicy()
        self.order_manager = OrderManager(repository, ShadowExecutionGateway())

    async def evaluate(
        self,
        candidate: OTCCandidate,
        state: RiskState,
        *,
        now: datetime,
        legacy_disposition: str | None = None,
    ) -> OTCShadowResult:
        require_utc(now, "now")
        instrument = InstrumentId(
            "iqoption",
            ProductType.BINARY_OPTION,
            candidate.normalized_asset,
            "USD",
        )
        action = (
            SignalAction.CALL
            if candidate.direction is BinaryDirection.CALL
            else SignalAction.PUT
        )
        signal = SignalProposal(
            signal_id=candidate.signal_id,
            strategy_id=candidate.strategy_id,
            instrument=instrument,
            environment=TradingEnvironment.SHADOW,
            action=action,
            confidence=candidate.confidence,
            model_version=candidate.calibration_version,
            decision_at=candidate.decision_at,
            expires_at=candidate.decision_at + self.policy.signal_valid_for,
            features={
                "source": candidate.source,
                "duration_minutes": candidate.duration_minutes,
                "payout_ratio": str(candidate.payout_ratio),
                "break_even_probability": str(candidate.break_even_probability),
                "estimated_win_probability": (
                    str(candidate.estimated_win_probability)
                    if candidate.estimated_win_probability is not None
                    else None
                ),
            },
        )
        generic = self.risk_engine.evaluate(
            RiskRequest(
                signal=signal,
                quantity=candidate.stake,
                reference_price=Decimal("1"),
            ),
            state,
            now=now,
        )
        reasons = list(generic.reasons)
        if candidate.martingale_step > 0:
            reasons.append("martingale is disabled in the migrated OTC path")
        if candidate.payout_ratio < self.policy.min_payout_ratio:
            reasons.append("OTC payout is below minimum")
        if candidate.estimated_win_probability is None:
            reasons.append("calibrated win probability is missing")
        else:
            provenance = (
                self.repository.find_calibration_provenance(
                    candidate.calibration_version
                )
                if candidate.calibration_version
                else None
            )
            if not candidate.calibration_version:
                reasons.append("calibration version is missing")
            elif provenance is None:
                reasons.append("calibration provenance is not registered")
            elif not provenance.offline_deployment_approved:
                reasons.append("calibration provenance is not deployment approved")
            if (
                candidate.expectancy is not None
                and candidate.expectancy <= self.policy.min_expectancy
            ):
                reasons.append("payout-dependent expectancy is not positive")

        if reasons:
            decision = RiskDecision(
                signal_id=signal.signal_id,
                environment=signal.environment,
                is_approved=False,
                limits_snapshot={},
                reasons=tuple(dict.fromkeys(reasons)),
                decision_id=uuid5(
                    NAMESPACE_URL, f"otc-shadow-risk:{signal.signal_id}:rejected"
                ),
            )
            self.repository.record_signal_decision(
                signal,
                decision,
                metadata={
                    "expectancy": str(candidate.expectancy),
                    "legacy_disposition": legacy_disposition,
                },
            )
            return OTCShadowResult(signal, decision, None, candidate.expectancy)

        limits_snapshot = dict(generic.limits_snapshot)
        limits_snapshot.update(
            {
                "otc_min_payout_ratio": str(self.policy.min_payout_ratio),
                "otc_min_expectancy": str(self.policy.min_expectancy),
            }
        )
        decision = RiskDecision(
            signal_id=signal.signal_id,
            environment=signal.environment,
            is_approved=True,
            limits_snapshot=limits_snapshot,
            decision_id=uuid5(
                NAMESPACE_URL, f"otc-shadow-risk:{signal.signal_id}:approved"
            ),
        )
        self.repository.record_signal_decision(
            signal,
            decision,
            metadata={
                "expectancy": str(candidate.expectancy),
                "legacy_disposition": legacy_disposition,
            },
        )
        terms = BinaryOptionTerms(
            direction=candidate.direction,
            expires_at=candidate.decision_at
            + timedelta(minutes=candidate.duration_minutes),
            payout_ratio=candidate.payout_ratio,
        )
        order = OrderIntent(
            client_order_id=f"otc-{candidate.signal_id.hex}",
            signal_id=signal.signal_id,
            risk_decision=decision,
            instrument=instrument,
            environment=TradingEnvironment.SHADOW,
            side=(
                OrderSide.BUY
                if candidate.direction is BinaryDirection.CALL
                else OrderSide.SELL
            ),
            order_type=OrderType.BINARY,
            quantity=Quantity(candidate.stake),
            time_in_force=TimeInForce.FOK,
            binary_terms=terms,
        )
        ledger_order = await self.order_manager.submit(order)
        return OTCShadowResult(signal, decision, ledger_order, candidate.expectancy)
