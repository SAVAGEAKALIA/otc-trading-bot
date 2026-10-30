"""Order intent and deterministic lifecycle rules."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from .environment import TradingEnvironment, ensure_same_environment
from .instruments import InstrumentId
from .money import Money, Quantity
from .risk import RiskDecision
from .time import require_utc


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"
    BINARY = "binary"


class TimeInForce(str, Enum):
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    POST_ONLY = "post_only"


class BinaryDirection(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True, slots=True)
class BinaryOptionTerms:
    direction: BinaryDirection
    expires_at: datetime
    payout_ratio: Decimal

    def __post_init__(self) -> None:
        require_utc(self.expires_at, "expires_at")
        if not Decimal("0") < self.payout_ratio <= Decimal("1"):
            raise ValueError("binary payout ratio must be in (0, 1]")


class OrderStatus(str, Enum):
    INTENT_RECORDED = "intent_recorded"
    SUBMISSION_STARTED = "submission_started"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class InvalidOrderTransition(ValueError):
    """Raised when an order lifecycle attempts an impossible transition."""


_LEGAL_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.INTENT_RECORDED: frozenset({OrderStatus.SUBMISSION_STARTED}),
    OrderStatus.SUBMISSION_STARTED: frozenset(
        {OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED, OrderStatus.UNKNOWN}
    ),
    OrderStatus.ACKNOWLEDGED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.EXPIRED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.UNKNOWN: frozenset(
        {
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


def ensure_order_transition(current: OrderStatus, next_status: OrderStatus) -> None:
    if next_status not in _LEGAL_TRANSITIONS[current]:
        raise InvalidOrderTransition(
            f"illegal order transition: {current.value} -> {next_status.value}"
        )


@dataclass(frozen=True, slots=True)
class OrderIntent:
    client_order_id: str
    signal_id: UUID
    risk_decision: RiskDecision
    instrument: InstrumentId
    environment: TradingEnvironment
    side: OrderSide
    order_type: OrderType
    quantity: Quantity
    time_in_force: TimeInForce
    limit_price: Money | None = None
    reduce_only: bool = False
    binary_terms: BinaryOptionTerms | None = None

    def __post_init__(self) -> None:
        client_order_id = self.client_order_id.strip()
        if not client_order_id:
            raise ValueError("client_order_id must not be empty")
        if len(client_order_id) > 64:
            raise ValueError("client_order_id exceeds platform maximum length")
        if not self.risk_decision.is_approved:
            raise ValueError("order intent requires an approved risk decision")
        if self.risk_decision.signal_id != self.signal_id:
            raise ValueError("risk decision does not reference this signal")
        ensure_same_environment(self.environment, self.risk_decision.environment)
        if self.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market orders cannot include limit_price")
        if self.order_type is OrderType.BINARY:
            if self.binary_terms is None:
                raise ValueError("binary orders require fixed-expiry terms")
            expected_side = (
                OrderSide.BUY
                if self.binary_terms.direction is BinaryDirection.CALL
                else OrderSide.SELL
            )
            if self.side is not expected_side:
                raise ValueError("binary order side does not match CALL/PUT direction")
        elif self.binary_terms is not None:
            raise ValueError("binary terms are only valid for binary orders")
        object.__setattr__(self, "client_order_id", client_order_id)
