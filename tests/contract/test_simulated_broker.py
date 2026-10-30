from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from trading_platform.brokers.simulated import (
    BinaryDirection,
    BinaryOptionIntent,
    ScriptedFailure,
    SimulatedBroker,
    SimulatedBrokerConfig,
    SimulatedConnectionError,
)
from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Money, Quantity
from trading_platform.domain.orders import (
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from trading_platform.domain.risk import RiskDecision
from trading_platform.execution.clock import ManualClock


START = datetime(2026, 1, 1, tzinfo=UTC)
BTC = InstrumentId("sim", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT")


def order(
    client_order_id: str = "order-1",
    *,
    order_type: OrderType = OrderType.MARKET,
    side: OrderSide = OrderSide.BUY,
    quantity: str = "2",
    limit: str | None = None,
    environment: TradingEnvironment = TradingEnvironment.BACKTEST,
) -> OrderIntent:
    signal_id = UUID("00000000-0000-0000-0000-000000000001")
    return OrderIntent(
        client_order_id=client_order_id,
        signal_id=signal_id,
        risk_decision=RiskDecision.approved(
            signal_id=signal_id,
            environment=environment,
            limits_snapshot={"max_notional": "1000000"},
        ),
        instrument=BTC,
        environment=environment,
        side=side,
        order_type=order_type,
        quantity=Quantity(Decimal(quantity)),
        time_in_force=TimeInForce.GTC,
        limit_price=Money(Decimal(limit), "USDT") if limit else None,
    )


def broker(**config) -> SimulatedBroker:
    instance = SimulatedBroker(
        ManualClock(START),
        SimulatedBrokerConfig(**config),
    )
    instance.update_quote(BTC, bid=Decimal("99"), ask=Decimal("100"))
    return instance


def test_market_order_fills_with_slippage_and_fee() -> None:
    sim = broker(slippage_bps=Decimal("10"), taker_fee_bps=Decimal("5"))

    result = sim.submit(order())

    assert result.status is OrderStatus.FILLED
    assert result.filled_quantity == Decimal("2")
    assert result.average_fill_price == Decimal("100.100")
    assert result.fills[0].fee == Decimal("0.1001000")


def test_limit_order_waits_then_fills_on_crossing_quote() -> None:
    sim = broker()
    pending = sim.submit(order(order_type=OrderType.LIMIT, limit="98"))
    assert pending.status is OrderStatus.ACKNOWLEDGED

    changed = sim.update_quote(BTC, bid=Decimal("97"), ask=Decimal("98"))

    assert changed[0].status is OrderStatus.FILLED
    assert changed[0].average_fill_price == Decimal("98")


def test_configured_partial_fills_are_reproducible() -> None:
    sim = broker(partial_fill_fractions=(Decimal("0.25"), Decimal("0.75")))

    result = sim.submit(order())

    assert [fill.quantity for fill in result.fills] == [Decimal("0.50"), Decimal("1.50")]
    assert result.status is OrderStatus.FILLED


def test_duplicate_client_order_id_is_idempotent() -> None:
    sim = broker()
    first = sim.submit(order())
    second = sim.submit(order())

    assert second is first
    assert len(sim.orders) == 1


def test_failure_script_can_reject_or_disconnect_without_ordering() -> None:
    rejecting = broker(failure_script=(ScriptedFailure.REJECT,))
    assert rejecting.submit(order()).status is OrderStatus.REJECTED

    disconnected = broker(failure_script=(ScriptedFailure.DISCONNECT,))
    with pytest.raises(SimulatedConnectionError):
        disconnected.submit(order())
    assert disconnected.orders == {}


def test_simulator_fails_closed_for_live_unsupported_or_unpriced_orders() -> None:
    sim = broker()
    assert sim.submit(order(environment=TradingEnvironment.LIVE)).status is OrderStatus.REJECTED
    assert sim.submit(order("stop", order_type=OrderType.STOP_MARKET)).status is OrderStatus.REJECTED

    unpriced = SimulatedBroker(ManualClock(START))
    assert unpriced.submit(order("unpriced")).status is OrderStatus.REJECTED


def test_funding_cashflow_uses_signed_position_notional() -> None:
    sim = broker()

    payment = sim.apply_funding(
        instrument=BTC,
        signed_quantity=Decimal("2"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
    )

    assert payment == Decimal("-0.200")


def test_binary_option_settles_at_fixed_expiry_and_payout() -> None:
    sim = broker()
    binary = BinaryOptionIntent(
        client_order_id="binary-1",
        instrument=InstrumentId(
            "sim", ProductType.BINARY_OPTION, "EURUSD-OTC", "USD"
        ),
        environment=TradingEnvironment.BACKTEST,
        direction=BinaryDirection.CALL,
        stake=Money(Decimal("10"), "USD"),
        entry_price=Decimal("1.1000"),
        expires_at=START + timedelta(minutes=1),
        payout_ratio=Decimal("0.85"),
    )
    opened = sim.submit_binary(binary)

    with pytest.raises(ValueError):
        sim.settle_binary(opened.order_id, Decimal("1.1010"))

    sim.clock.advance(timedelta(minutes=1))
    settled = sim.settle_binary(opened.order_id, Decimal("1.1010"))

    assert settled.outcome == "win"
    assert settled.pnl == Decimal("8.50")


def test_identical_inputs_produce_identical_event_ledger() -> None:
    first = broker(slippage_bps=Decimal("2"))
    second = broker(slippage_bps=Decimal("2"))

    first.submit(order())
    second.submit(order())

    assert first.events == second.events
    assert first.orders["order-1"].fills == second.orders["order-1"].fills
