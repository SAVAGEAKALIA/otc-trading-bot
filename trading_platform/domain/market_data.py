"""Immutable normalized market-data snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .instruments import InstrumentId, ProductType
from .time import require_utc


@dataclass(frozen=True, slots=True)
class MarketTicker:
    instrument: InstrumentId
    observed_at: datetime
    last_price: Decimal
    bid_price: Decimal
    bid_size: Decimal
    ask_price: Decimal
    ask_size: Decimal
    mark_price: Decimal | None = None
    index_price: Decimal | None = None
    open_interest: Decimal | None = None
    funding_rate: Decimal | None = None
    next_funding_at: datetime | None = None

    def __post_init__(self) -> None:
        require_utc(self.observed_at, "observed_at")
        for name in ("last_price", "bid_price", "ask_price", "bid_size", "ask_size"):
            value = getattr(self, name)
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.bid_price > self.ask_price:
            raise ValueError("bid_price cannot exceed ask_price")
        for name in ("mark_price", "index_price"):
            value = getattr(self, name)
            if value is not None and (not value.is_finite() or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
        if self.open_interest is not None and (
            not self.open_interest.is_finite() or self.open_interest < 0
        ):
            raise ValueError("open_interest must be finite and non-negative")
        if self.funding_rate is not None and not self.funding_rate.is_finite():
            raise ValueError("funding_rate must be finite")
        if self.next_funding_at is not None:
            require_utc(self.next_funding_at, "next_funding_at")
        derivative_fields = (
            self.mark_price,
            self.index_price,
            self.open_interest,
            self.funding_rate,
            self.next_funding_at,
        )
        if self.instrument.product_type is ProductType.SPOT and any(
            value is not None for value in derivative_fields
        ):
            raise ValueError("spot ticker cannot contain derivative fields")
        if self.instrument.product_type is ProductType.LINEAR_PERPETUAL and (
            self.mark_price is None or self.index_price is None
        ):
            raise ValueError("linear perpetual ticker requires mark and index prices")
