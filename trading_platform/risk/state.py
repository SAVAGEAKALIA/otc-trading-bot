"""Immutable account and market state consumed by pre-trade risk."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId
from trading_platform.domain.time import require_utc


@dataclass(frozen=True, slots=True)
class RiskState:
    environment: TradingEnvironment
    as_of: datetime
    equity: Decimal
    peak_equity: Decimal
    total_abs_exposure: Decimal
    instrument_exposures: Mapping[InstrumentId, Decimal]
    open_order_count: int
    seen_signal_ids: frozenset[UUID] = field(default_factory=frozenset)
    market_data_as_of: Mapping[InstrumentId, datetime] = field(default_factory=dict)
    kill_switch_active: bool = False

    def __post_init__(self) -> None:
        require_utc(self.as_of, "as_of")
        if self.equity <= 0:
            raise ValueError("equity must be positive")
        if self.peak_equity <= 0 or self.peak_equity < self.equity:
            raise ValueError("peak equity must be positive and at least current equity")
        if self.total_abs_exposure < 0:
            raise ValueError("total exposure cannot be negative")
        if self.open_order_count < 0:
            raise ValueError("open order count cannot be negative")
        exposures = dict(self.instrument_exposures)
        if any(value < 0 for value in exposures.values()):
            raise ValueError("instrument absolute exposures cannot be negative")
        timestamps = dict(self.market_data_as_of)
        for timestamp in timestamps.values():
            require_utc(timestamp, "market_data_as_of")
        object.__setattr__(self, "instrument_exposures", MappingProxyType(exposures))
        object.__setattr__(self, "market_data_as_of", MappingProxyType(timestamps))
