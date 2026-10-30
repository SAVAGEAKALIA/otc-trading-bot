"""Authoritative fixed-expiry binary-option settlement records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .time import require_utc


class BinarySettlementOutcome(str, Enum):
    WIN = "win"
    LOSS = "loss"
    TIE = "tie"
    VOID = "void"


@dataclass(frozen=True, slots=True)
class BinarySettlement:
    venue_settlement_id: str
    client_order_id: str
    broker_order_id: str
    outcome: BinarySettlementOutcome
    stake: Decimal
    gross_return: Decimal
    net_pnl: Decimal
    settlement_asset: str
    settled_at: datetime
    source: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_utc(self.settled_at, "settled_at")
        for name in (
            "venue_settlement_id",
            "client_order_id",
            "broker_order_id",
            "settlement_asset",
        ):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "settlement_asset", self.settlement_asset.upper())
        if self.source != "broker_api":
            raise ValueError("authoritative settlement source must be broker_api")
        if self.stake <= 0 or self.gross_return < 0:
            raise ValueError("stake must be positive and gross return non-negative")
        if self.net_pnl != self.gross_return - self.stake:
            raise ValueError("net PnL must equal gross return minus stake")
        if self.outcome is BinarySettlementOutcome.WIN and self.net_pnl <= 0:
            raise ValueError("win settlement must have positive net PnL")
        if self.outcome is BinarySettlementOutcome.LOSS and self.gross_return != 0:
            raise ValueError("loss settlement must have zero gross return")
        if self.outcome in {BinarySettlementOutcome.TIE, BinarySettlementOutcome.VOID} and (
            self.gross_return != self.stake or self.net_pnl != 0
        ):
            raise ValueError("tie or void settlement must return the full stake")
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
