"""Small deterministic execution simulator, not a profitability model."""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId
from trading_platform.domain.orders import OrderIntent, OrderSide, OrderStatus, OrderType
from trading_platform.execution.clock import Clock

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


class SimulatedBroker:
    def __init__(self, clock: Clock, config: SimulatedBrokerConfig | None = None) -> None:
        self.clock = clock
        self.config = config or SimulatedBrokerConfig()
        self.orders: dict[str, SimulatedOrder] = {}
        self.binary_orders: dict[str, BinaryOptionOrder] = {}
        self.events: list[SimulatedEvent] = []
        self._quotes: dict[InstrumentId, tuple[Decimal, Decimal]] = {}
        self._failures = deque(self.config.failure_script)
        self._order_sequence = 0
        self._fill_sequence = 0
        self._event_sequence = 0

    def update_quote(
        self, instrument: InstrumentId, *, bid: Decimal, ask: Decimal
    ) -> list[SimulatedOrder]:
        if bid <= 0 or ask <= 0 or bid > ask:
            raise ValueError("quote requires 0 < bid <= ask")
        self._quotes[instrument] = (bid, ask)
        changed: list[SimulatedOrder] = []
        for current in self.orders.values():
            if current.status is not OrderStatus.ACKNOWLEDGED:
                continue
            if current.intent.instrument != instrument:
                continue
            if self._can_fill_limit(current.intent, bid, ask):
                self._fill(current, self._reference_price(current.intent, bid, ask))
                changed.append(current)
        return changed

    def submit(self, intent: OrderIntent) -> SimulatedOrder:
        existing = self.orders.get(intent.client_order_id)
        if existing is not None:
            return existing
        if intent.environment in {
            TradingEnvironment.MICRO_LIVE,
            TradingEnvironment.LIVE,
        }:
            return self._reject(intent, "simulated broker cannot accept live orders")
        if intent.order_type not in {OrderType.MARKET, OrderType.LIMIT}:
            return self._reject(intent, "order type is not implemented by simulator")
        quote = self._quotes.get(intent.instrument)
        if intent.order_type is OrderType.MARKET and quote is None:
            return self._reject(intent, "market order requires a current quote")
        failed_order = self._apply_next_failure(intent)
        if failed_order is not None:
            return failed_order
        now = self.clock.now()
        self._order_sequence += 1
        current = SimulatedOrder(
            order_id=f"SIM-{self._order_sequence:08d}",
            intent=intent,
            status=OrderStatus.ACKNOWLEDGED,
            created_at=now,
        )
        self.orders[intent.client_order_id] = current
        self._record("order.acknowledged", current.order_id)

        if quote is None:
            return current
        bid, ask = quote
        if intent.order_type is OrderType.MARKET or self._can_fill_limit(intent, bid, ask):
            self._fill(current, self._reference_price(intent, bid, ask))
        return current

    def _apply_next_failure(self, intent: OrderIntent) -> SimulatedOrder | None:
        if not self._failures:
            return None
        failure = self._failures.popleft()
        if failure is ScriptedFailure.DISCONNECT:
            raise SimulatedConnectionError("scripted broker disconnect")
        if failure is ScriptedFailure.TIMEOUT:
            raise SimulatedTimeoutError("scripted broker timeout")
        return self._reject(intent, "scripted rejection")

    def _reject(self, intent: OrderIntent, error: str) -> SimulatedOrder:
        self._order_sequence += 1
        current = SimulatedOrder(
            order_id=f"SIM-{self._order_sequence:08d}",
            intent=intent,
            status=OrderStatus.REJECTED,
            created_at=self.clock.now(),
            error=error,
        )
        self.orders[intent.client_order_id] = current
        self._record("order.rejected", current.order_id, error=error)
        return current

    def _fill(self, current: SimulatedOrder, reference_price: Decimal) -> None:
        intent = current.intent
        rate = self.config.slippage_bps / Decimal("10000")
        multiplier = Decimal("1") + rate if intent.side is OrderSide.BUY else Decimal("1") - rate
        fill_price = reference_price * multiplier
        fee_bps = (
            self.config.taker_fee_bps
            if intent.order_type is OrderType.MARKET
            else self.config.maker_fee_bps
        )
        for index, fraction in enumerate(self.config.partial_fill_fractions):
            quantity = intent.quantity.value * fraction
            fee = quantity * fill_price * fee_bps / Decimal("10000")
            self._fill_sequence += 1
            current.fills.append(
                SimulatedFill(
                    fill_id=f"FILL-{self._fill_sequence:08d}",
                    order_id=current.order_id,
                    quantity=quantity,
                    price=fill_price,
                    fee=fee,
                    occurred_at=self.clock.now(),
                )
            )
            current.status = (
                OrderStatus.FILLED
                if index == len(self.config.partial_fill_fractions) - 1
                else OrderStatus.PARTIALLY_FILLED
            )
            self._record(
                "order.filled" if current.status is OrderStatus.FILLED else "order.partially_filled",
                current.order_id,
                quantity=str(quantity),
                price=str(fill_price),
            )

    @staticmethod
    def _can_fill_limit(intent: OrderIntent, bid: Decimal, ask: Decimal) -> bool:
        if intent.order_type not in {OrderType.LIMIT, OrderType.STOP_LIMIT}:
            return False
        assert intent.limit_price is not None
        return (
            ask <= intent.limit_price.amount
            if intent.side is OrderSide.BUY
            else bid >= intent.limit_price.amount
        )

    @staticmethod
    def _reference_price(intent: OrderIntent, bid: Decimal, ask: Decimal) -> Decimal:
        return ask if intent.side is OrderSide.BUY else bid

    def apply_funding(
        self,
        *,
        instrument: InstrumentId,
        signed_quantity: Decimal,
        mark_price: Decimal,
        funding_rate: Decimal,
    ) -> Decimal:
        if mark_price <= 0:
            raise ValueError("mark price must be positive")
        payment = -(signed_quantity * mark_price * funding_rate)
        self._record(
            "position.funding_applied",
            instrument.symbol,
            payment=str(payment),
            rate=str(funding_rate),
        )
        return payment

    def submit_binary(self, intent: BinaryOptionIntent) -> BinaryOptionOrder:
        existing = self.binary_orders.get(intent.client_order_id)
        if existing is not None:
            return existing
        if intent.environment in {
            TradingEnvironment.MICRO_LIVE,
            TradingEnvironment.LIVE,
        }:
            raise ValueError("simulated broker cannot accept live binary orders")
        if intent.expires_at <= self.clock.now():
            raise ValueError("binary expiry must be in the future")
        self._order_sequence += 1
        current = BinaryOptionOrder(
            order_id=f"SIM-BINARY-{self._order_sequence:08d}",
            intent=intent,
            opened_at=self.clock.now(),
        )
        self.binary_orders[intent.client_order_id] = current
        self._record("binary.opened", current.order_id)
        return current

    def settle_binary(self, order_id: str, settlement_price: Decimal) -> BinaryOptionOrder:
        if settlement_price <= 0:
            raise ValueError("settlement price must be positive")
        current = next(
            (item for item in self.binary_orders.values() if item.order_id == order_id),
            None,
        )
        if current is None:
            raise KeyError(order_id)
        if current.outcome is not None:
            return current
        if self.clock.now() < current.intent.expires_at:
            raise ValueError("binary order cannot settle before expiry")
        difference = settlement_price - current.intent.entry_price
        won = difference > 0 if current.intent.direction is BinaryDirection.CALL else difference < 0
        if difference == 0:
            current.outcome = "tie"
            current.pnl = Decimal("0")
        elif won:
            current.outcome = "win"
            current.pnl = current.intent.stake.amount * current.intent.payout_ratio
        else:
            current.outcome = "loss"
            current.pnl = -current.intent.stake.amount
        current.settlement_price = settlement_price
        self._record("binary.settled", current.order_id, outcome=current.outcome, pnl=str(current.pnl))
        return current

    def _record(self, name: str, reference_id: str, **details: str) -> None:
        self._event_sequence += 1
        self.events.append(
            SimulatedEvent(
                sequence=self._event_sequence,
                occurred_at=self.clock.now(),
                name=name,
                reference_id=reference_id,
                details=tuple(sorted(details.items())),
            )
        )
