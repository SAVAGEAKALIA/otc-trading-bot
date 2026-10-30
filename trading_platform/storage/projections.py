"""Validated broker account snapshots and current projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId
from trading_platform.domain.time import require_utc


@dataclass(frozen=True, slots=True)
class BalanceProjection:
    asset: str
    total: Decimal
    available: Decimal

    def __post_init__(self) -> None:
        asset = self.asset.strip().upper()
        if not asset:
            raise ValueError("balance asset must not be empty")
        if self.total < 0 or self.available < 0 or self.available > self.total:
            raise ValueError("balance requires 0 <= available <= total")
        object.__setattr__(self, "asset", asset)


@dataclass(frozen=True, slots=True)
class PositionProjection:
    instrument: InstrumentId
    signed_quantity: Decimal
    average_entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    leverage: Decimal
    liquidation_price: Decimal | None = None
    position_idx: int = 0

    def __post_init__(self) -> None:
        if self.average_entry_price < 0 or self.mark_price <= 0:
            raise ValueError("position prices must be non-negative entry and positive mark")
        if self.signed_quantity != 0 and self.average_entry_price <= 0:
            raise ValueError("open position requires a positive entry price")
        if self.leverage <= 0:
            raise ValueError("position leverage must be positive")
        if self.liquidation_price is not None and self.liquidation_price <= 0:
            raise ValueError("liquidation price must be positive")
        if self.position_idx not in (0, 1, 2):
            raise ValueError("position_idx must be 0 (one-way), 1 (buy), or 2 (sell)")


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    snapshot_id: str
    venue: str
    environment: TradingEnvironment
    as_of: datetime
    balances: tuple[BalanceProjection, ...]
    positions: tuple[PositionProjection, ...]

    def __post_init__(self) -> None:
        snapshot_id = self.snapshot_id.strip()
        venue = self.venue.strip().upper()
        if not snapshot_id or not venue:
            raise ValueError("snapshot_id and venue must not be empty")
        require_utc(self.as_of, "as_of")
        if len({item.asset for item in self.balances}) != len(self.balances):
            raise ValueError("account snapshot contains duplicate balance assets")
        if any(item.instrument.venue != venue for item in self.positions):
            raise ValueError("position venue must match account snapshot venue")
        identities = {(item.instrument, item.position_idx) for item in self.positions}
        if len(identities) != len(self.positions):
            raise ValueError("account snapshot contains duplicate position legs")
        object.__setattr__(self, "snapshot_id", snapshot_id)
        object.__setattr__(self, "venue", venue)
