"""Normalize Bybit V5 linear positions while preserving hedge-mode legs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.orders import OrderSide
from trading_platform.storage.projections import PositionProjection


@dataclass(frozen=True, slots=True)
class BybitPositionRecord:
    instrument: InstrumentId
    position_index: int
    side: OrderSide
    signed_quantity: Decimal
    average_entry_price: Decimal
    mark_price: Decimal
    position_value: Decimal
    unrealized_pnl: Decimal
    leverage: Decimal | None
    liquidation_price: Decimal | None
    initial_margin: Decimal | None
    maintenance_margin: Decimal | None

    def __post_init__(self) -> None:
        if self.position_index not in {0, 1, 2}:
            raise ValueError("position_index must be 0, 1, or 2")
        if self.position_index == 1 and self.side is not OrderSide.BUY:
            raise ValueError("Bybit positionIdx 1 must be the Buy hedge leg")
        if self.position_index == 2 and self.side is not OrderSide.SELL:
            raise ValueError("Bybit positionIdx 2 must be the Sell hedge leg")
        expected_positive = self.side is OrderSide.BUY
        if (self.signed_quantity > 0) != expected_positive:
            raise ValueError("signed position quantity does not match side")
        if self.signed_quantity == 0:
            raise ValueError("position record must be open")
        for name in ("average_entry_price", "mark_price", "position_value"):
            value = getattr(self, name)
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not self.unrealized_pnl.is_finite():
            raise ValueError("unrealized_pnl must be finite")
        for name in ("leverage", "liquidation_price"):
            value = getattr(self, name)
            if value is not None and (not value.is_finite() or value <= 0):
                raise ValueError(f"{name} must be finite and positive when reported")
        for name in ("initial_margin", "maintenance_margin"):
            value = getattr(self, name)
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError(f"{name} must be finite and non-negative when reported")


@dataclass(frozen=True, slots=True)
class BybitPositionPage:
    category: str
    positions: tuple[BybitPositionRecord, ...]
    next_cursor: str | None
    server_time: datetime


def to_projection(record: BybitPositionRecord) -> PositionProjection:
    """Map an adapter-owned hedge leg without collapsing its identity."""
    if record.leverage is None:
        raise ValueError("cannot project a position with unknown leverage")
    return PositionProjection(
        instrument=record.instrument,
        signed_quantity=record.signed_quantity,
        average_entry_price=record.average_entry_price,
        mark_price=record.mark_price,
        unrealized_pnl=record.unrealized_pnl,
        leverage=record.leverage,
        liquidation_price=record.liquidation_price,
        position_idx=record.position_index,
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Bybit {name} must be an object")
    return value


def _decimal(value: Any, name: str, *, optional: bool = False) -> Decimal | None:
    if optional and value in {None, ""}:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Bybit {name} is not a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"Bybit {name} must be finite")
    return result


def normalize_position_page(
    payload: Mapping[str, Any],
    *,
    expected_category: str,
    instruments: Mapping[str, InstrumentId],
) -> BybitPositionPage:
    category = expected_category.strip().lower()
    if category != "linear":
        raise ValueError("Phase 8 position normalization supports only linear")
    code = int(payload.get("retCode", -1))
    if code != 0:
        raise ValueError(f"Bybit API error {code}: {payload.get('retMsg', '')}")
    result = _mapping(payload.get("result"), "result")
    actual_category = str(result.get("category", "")).strip().lower()
    if actual_category != category:
        raise ValueError(
            f"Bybit response category {actual_category!r} does not match {category!r}"
        )
    raw_items = result.get("list")
    if not isinstance(raw_items, list):
        raise ValueError("Bybit position list must be an array")
    records = []
    for raw in raw_items:
        item = _mapping(raw, "position")
        symbol = str(item.get("symbol", "")).strip().upper()
        instrument = instruments.get(symbol)
        if instrument is None:
            raise ValueError(f"Bybit position symbol is absent from catalog: {symbol}")
        if (
            instrument.venue != "BYBIT"
            or instrument.product_type is not ProductType.LINEAR_PERPETUAL
        ):
            raise ValueError(f"Bybit position catalog category mismatch: {symbol}")
        size = _decimal(item.get("size"), "size")
        assert size is not None
        if size < 0:
            raise ValueError("Bybit position size cannot be negative")
        if size == 0:
            continue
        raw_side = str(item.get("side", "")).strip()
        sides = {"Buy": OrderSide.BUY, "Sell": OrderSide.SELL}
        if raw_side not in sides:
            raise ValueError("Bybit open position side must be Buy or Sell")
        side = sides[raw_side]
        signed_quantity = size if side is OrderSide.BUY else -size
        records.append(
            BybitPositionRecord(
                instrument=instrument,
                position_index=int(item.get("positionIdx", -1)),
                side=side,
                signed_quantity=signed_quantity,
                average_entry_price=_decimal(
                    item.get("avgPrice"), "average_entry_price"
                ),
                mark_price=_decimal(item.get("markPrice"), "mark_price"),
                position_value=_decimal(
                    item.get("positionValue"), "position_value"
                ),
                unrealized_pnl=_decimal(
                    item.get("unrealisedPnl"), "unrealized_pnl"
                ),
                leverage=_decimal(item.get("leverage"), "leverage", optional=True),
                liquidation_price=_decimal(
                    item.get("liqPrice"), "liquidation_price", optional=True
                ),
                initial_margin=_decimal(
                    item.get("positionIM"), "initial_margin", optional=True
                ),
                maintenance_margin=_decimal(
                    item.get("positionMM"), "maintenance_margin", optional=True
                ),
            )
        )
    identities = [
        (item.instrument.symbol, item.position_index) for item in records
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("Bybit position page contains a duplicate position leg")
    server_ms = int(payload.get("time", 0))
    if server_ms <= 0:
        raise ValueError("Bybit response time must be positive Unix milliseconds")
    cursor = str(result.get("nextPageCursor", "")).strip() or None
    return BybitPositionPage(
        category=category,
        positions=tuple(records),
        next_cursor=cursor,
        server_time=datetime.fromtimestamp(server_ms / 1000, tz=UTC),
    )
