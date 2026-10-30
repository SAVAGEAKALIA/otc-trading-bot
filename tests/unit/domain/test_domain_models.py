from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading_platform.domain.environment import (
    EnvironmentMismatchError,
    TradingEnvironment,
    ensure_same_environment,
)
from trading_platform.domain.events import DomainEvent
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Money, Quantity
from trading_platform.domain.orders import (
    BinaryDirection,
    BinaryOptionTerms,
    InvalidOrderTransition,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    ensure_order_transition,
)
from trading_platform.domain.risk import RiskDecision
from trading_platform.domain.serialization import (
    domain_event_from_record,
    domain_event_to_record,
    order_intent_from_record,
    order_intent_to_record,
)
from trading_platform.domain.signals import SignalAction, SignalProposal


def test_environment_values_are_explicit() -> None:
    assert {item.value for item in TradingEnvironment} == {
        "research",
        "backtest",
        "shadow",
        "paper",
        "testnet",
        "micro_live",
        "live",
    }


def test_mixed_environments_are_rejected() -> None:
    with pytest.raises(EnvironmentMismatchError):
        ensure_same_environment(TradingEnvironment.TESTNET, TradingEnvironment.LIVE)


def test_money_is_decimal_positive_or_zero_and_immutable() -> None:
    money = Money(amount=Decimal("10.25"), currency="usdt")

    assert money.amount == Decimal("10.25")
    assert money.currency == "USDT"
    with pytest.raises(FrozenInstanceError):
        money.amount = Decimal("12")  # type: ignore[misc]


@given(st.decimals(max_value=Decimal("-0.00000001"), allow_nan=False, allow_infinity=False))
def test_money_rejects_negative_amounts(amount: Decimal) -> None:
    with pytest.raises(ValueError):
        Money(amount=amount, currency="USD")


def test_quantity_must_be_strictly_positive() -> None:
    with pytest.raises(ValueError):
        Quantity(Decimal("0"))


def test_instrument_identity_includes_venue_and_product() -> None:
    spot = InstrumentId("bybit", ProductType.SPOT, "btcusdt", "usdt")
    perpetual = InstrumentId("bybit", ProductType.LINEAR_PERPETUAL, "btcusdt", "usdt")

    assert spot.venue == "BYBIT"
    assert spot.symbol == "BTCUSDT"
    assert spot != perpetual


def test_domain_event_requires_utc_aware_times() -> None:
    with pytest.raises(ValueError):
        DomainEvent(
            name="signal.proposed",
            environment=TradingEnvironment.SHADOW,
            occurred_at=datetime.now(),
        )


def test_domain_event_has_stable_identity_and_receive_time() -> None:
    occurred = datetime.now(UTC)
    event = DomainEvent(
        name="signal.proposed",
        environment=TradingEnvironment.SHADOW,
        occurred_at=occurred,
    )

    assert isinstance(event.event_id, UUID)
    assert event.received_at >= occurred
    assert event.schema_version == 1


def test_domain_event_round_trips_through_json_safe_record() -> None:
    event = DomainEvent(
        name="risk.rejected",
        environment=TradingEnvironment.SHADOW,
        occurred_at=datetime.now(UTC),
        payload={"reason": "stale data", "age_ms": 2500},
    )

    assert domain_event_from_record(domain_event_to_record(event)) == event


def test_signal_proposal_requires_future_expiry_and_bounded_confidence() -> None:
    now = datetime.now(UTC)
    instrument = InstrumentId("iqoption", ProductType.BINARY_OPTION, "EURUSD-OTC", "USD")

    proposal = SignalProposal(
        strategy_id="otc_directional_v1",
        instrument=instrument,
        environment=TradingEnvironment.SHADOW,
        action=SignalAction.CALL,
        confidence=Decimal("0.72"),
        decision_at=now,
        expires_at=now + timedelta(seconds=10),
    )

    assert proposal.confidence == Decimal("0.72")

    with pytest.raises(ValueError):
        SignalProposal(
            strategy_id="otc_directional_v1",
            instrument=instrument,
            environment=TradingEnvironment.SHADOW,
            action=SignalAction.CALL,
            confidence=Decimal("1.1"),
            decision_at=now,
            expires_at=now + timedelta(seconds=10),
        )


def test_risk_approval_requires_limits_snapshot() -> None:
    with pytest.raises(ValueError):
        RiskDecision.approved(
            signal_id=UUID("00000000-0000-0000-0000-000000000001"),
            environment=TradingEnvironment.TESTNET,
            limits_snapshot={},
        )


def test_order_intent_requires_approved_matching_risk_decision() -> None:
    signal_id = UUID("00000000-0000-0000-0000-000000000001")
    risk = RiskDecision.rejected(
        signal_id=signal_id,
        environment=TradingEnvironment.TESTNET,
        reasons=("limit exceeded",),
    )

    with pytest.raises(ValueError):
        OrderIntent(
            client_order_id="test-001",
            signal_id=signal_id,
            risk_decision=risk,
            instrument=InstrumentId(
                "bybit", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT"
            ),
            environment=TradingEnvironment.TESTNET,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Quantity(Decimal("0.001")),
            time_in_force=TimeInForce.IOC,
        )


def test_order_intent_round_trips_through_json_safe_record() -> None:
    signal_id = UUID("00000000-0000-0000-0000-000000000001")
    risk = RiskDecision.approved(
        signal_id=signal_id,
        environment=TradingEnvironment.TESTNET,
        limits_snapshot={"max_notional": "25", "max_leverage": "1"},
    )
    intent = OrderIntent(
        client_order_id="test-001",
        signal_id=signal_id,
        risk_decision=risk,
        instrument=InstrumentId(
            "bybit", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT"
        ),
        environment=TradingEnvironment.TESTNET,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Quantity(Decimal("0.001")),
        time_in_force=TimeInForce.GTC,
        limit_price=Money(Decimal("60000.5"), "USDT"),
        reduce_only=False,
    )

    assert order_intent_from_record(order_intent_to_record(intent)) == intent


def test_binary_order_requires_and_round_trips_fixed_expiry_terms() -> None:
    signal_id = UUID("00000000-0000-0000-0000-000000000002")
    environment = TradingEnvironment.SHADOW
    risk = RiskDecision.approved(
        signal_id=signal_id,
        environment=environment,
        limits_snapshot={"max_stake": "10"},
    )
    intent = OrderIntent(
        client_order_id="binary-001",
        signal_id=signal_id,
        risk_decision=risk,
        instrument=InstrumentId(
            "iqoption", ProductType.BINARY_OPTION, "EURUSD-OTC", "USD"
        ),
        environment=environment,
        side=OrderSide.BUY,
        order_type=OrderType.BINARY,
        quantity=Quantity(Decimal("5")),
        time_in_force=TimeInForce.FOK,
        binary_terms=BinaryOptionTerms(
            BinaryDirection.CALL,
            datetime.now(UTC) + timedelta(minutes=2),
            Decimal("0.84"),
        ),
    )

    assert order_intent_from_record(order_intent_to_record(intent)) == intent


@pytest.mark.parametrize(
    ("current", "next_status"),
    (
        (OrderStatus.INTENT_RECORDED, OrderStatus.SUBMISSION_STARTED),
        (OrderStatus.SUBMISSION_STARTED, OrderStatus.ACKNOWLEDGED),
        (OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED),
        (OrderStatus.ACKNOWLEDGED, OrderStatus.CANCELED),
    ),
)
def test_legal_order_transitions(current: OrderStatus, next_status: OrderStatus) -> None:
    ensure_order_transition(current, next_status)


@pytest.mark.parametrize(
    ("current", "next_status"),
    (
        (OrderStatus.INTENT_RECORDED, OrderStatus.FILLED),
        (OrderStatus.FILLED, OrderStatus.ACKNOWLEDGED),
        (OrderStatus.CANCELED, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.REJECTED, OrderStatus.SUBMISSION_STARTED),
    ),
)
def test_illegal_order_transitions_fail_closed(
    current: OrderStatus, next_status: OrderStatus
) -> None:
    with pytest.raises(InvalidOrderTransition):
        ensure_order_transition(current, next_status)
