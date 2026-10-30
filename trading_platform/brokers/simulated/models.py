"""Immutable configuration and explicit simulator result records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Money
from trading_platform.domain.orders import OrderIntent, OrderStatus
from trading_platform.domain.time import require_utc


class ScriptedFailure(str, Enum):
    REJECT = "reject"
    DISCONNECT = "disconnect"
    TIMEOUT = "timeout"


class SimulatedConnectionError(ConnectionError):
    pass


class SimulatedTimeoutError(TimeoutError):
    pass


class BinaryDirection(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True, slots=True)
class SimulatedBrokerConfig:
    slippage_bps: Decimal = Decimal("0")
    maker_fee_bps: Decimal = Decimal("0")
    taker_fee_bps: Decimal = Decimal("0")
    partial_fill_fractions: tuple[Decimal, ...] = (Decimal("1"),)
    failure_script: tuple[ScriptedFailure, ...] = ()

    def __post_init__(self) -> None:
        if min(self.slippage_bps, self.maker_fee_bps, self.taker_fee_bps) < 0:
            raise ValueError("slippage and fee rates cannot be negative")
        if not self.partial_fill_fractions:
            raise ValueError("at least one fill fraction is required")
        if any(fraction <= 0 for fraction in self.partial_fill_fractions):
            raise ValueError("fill fractions must be positive")
        if sum(self.partial_fill_fractions) != Decimal("1"):
            raise ValueError("fill fractions must sum to one")


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    fill_id: str
    order_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    occurred_at: datetime


@dataclass(slots=True)
class SimulatedOrder:
    order_id: str
    intent: OrderIntent
    status: OrderStatus
    created_at: datetime
    fills: list[SimulatedFill] = field(default_factory=list)
    error: str | None = None

    @property
    def filled_quantity(self) -> Decimal:
        return sum((fill.quantity for fill in self.fills), Decimal("0"))

    @property
    def average_fill_price(self) -> Decimal | None:
        if not self.fills:
            return None
        notional = sum((fill.quantity * fill.price for fill in self.fills), Decimal("0"))
        return notional / self.filled_quantity


@dataclass(frozen=True, slots=True)
class BinaryOptionIntent:
    client_order_id: str
    instrument: InstrumentId
    environment: TradingEnvironment
    direction: BinaryDirection
    stake: Money
    entry_price: Decimal
    expires_at: datetime
    payout_ratio: Decimal

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("client_order_id must not be empty")
        if self.instrument.product_type is not ProductType.BINARY_OPTION:
            raise ValueError("binary intent requires a binary-option instrument")
        if self.stake.currency != self.instrument.settlement_asset:
            raise ValueError("stake currency must equal settlement asset")
        if self.entry_price <= 0:
            raise ValueError("entry price must be positive")
        if self.stake.amount <= 0:
            raise ValueError("binary stake must be positive")
        if not Decimal("0") < self.payout_ratio <= Decimal("1"):
            raise ValueError("payout ratio must be in (0, 1]")
        require_utc(self.expires_at, "expires_at")


@dataclass(slots=True)
class BinaryOptionOrder:
    order_id: str
    intent: BinaryOptionIntent
    opened_at: datetime
    outcome: str | None = None
    pnl: Decimal | None = None
    settlement_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SimulatedEvent:
    sequence: int
    occurred_at: datetime
    name: str
    reference_id: str
    details: tuple[tuple[str, str], ...] = ()
