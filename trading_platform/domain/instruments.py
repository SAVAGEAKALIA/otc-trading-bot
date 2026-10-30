"""Venue-aware instrument identity."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class ProductType(str, Enum):
    BINARY_OPTION = "binary_option"
    SPOT = "spot"
    LINEAR_PERPETUAL = "linear_perpetual"
    INVERSE_PERPETUAL = "inverse_perpetual"


@dataclass(frozen=True, slots=True)
class InstrumentId:
    venue: str
    product_type: ProductType
    symbol: str
    settlement_asset: str

    def __post_init__(self) -> None:
        for field_name in ("venue", "symbol", "settlement_asset"):
            value = getattr(self, field_name).strip().upper()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """Venue-reported trading constraints normalized without float conversion."""

    instrument: InstrumentId
    base_asset: str
    quote_asset: str
    status: str
    is_trading: bool
    price_tick: Decimal
    quantity_step: Decimal
    minimum_quantity: Decimal
    maximum_quantity: Decimal
    minimum_price: Decimal
    maximum_price: Decimal
    minimum_notional: Decimal | None = None
    maximum_leverage: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("base_asset", "quote_asset"):
            value = getattr(self, name).strip().upper()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        status = self.status.strip()
        if not status:
            raise ValueError("instrument status must not be empty")
        object.__setattr__(self, "status", status)
        positive = (
            "price_tick",
            "quantity_step",
            "minimum_quantity",
            "maximum_quantity",
            "minimum_price",
            "maximum_price",
        )
        for name in positive:
            value = getattr(self, name)
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.minimum_quantity > self.maximum_quantity:
            raise ValueError("minimum_quantity cannot exceed maximum_quantity")
        if self.minimum_price > self.maximum_price:
            raise ValueError("minimum_price cannot exceed maximum_price")
        for name in ("minimum_notional", "maximum_leverage"):
            value = getattr(self, name)
            if value is not None and (not value.is_finite() or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
