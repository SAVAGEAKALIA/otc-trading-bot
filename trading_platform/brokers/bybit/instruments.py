"""Normalize Bybit V5 instruments-info responses without network access."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from trading_platform.domain.instruments import InstrumentId, InstrumentSpec, ProductType


CATEGORY_PRODUCTS = {
    "spot": ProductType.SPOT,
    "linear": ProductType.LINEAR_PERPETUAL,
}


@dataclass(frozen=True, slots=True)
class BybitInstrumentPage:
    category: str
    instruments: tuple[InstrumentSpec, ...]
    next_cursor: str | None
    server_time: datetime


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Bybit {name} must be an object")
    return value


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Bybit {name} is not a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"Bybit {name} must be finite")
    return result


def _required_text(item: Mapping[str, Any], name: str) -> str:
    result = str(item.get(name, "")).strip()
    if not result:
        raise ValueError(f"Bybit instrument is missing {name}")
    return result


def normalize_instrument_page(
    payload: Mapping[str, Any], *, expected_category: str
) -> BybitInstrumentPage:
    """Convert one verified REST page into exact platform constraints."""
    category = expected_category.strip().lower()
    if category not in CATEGORY_PRODUCTS:
        raise ValueError("Bybit category must be spot or linear")
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
        raise ValueError("Bybit instrument list must be an array")
    instruments = []
    for raw in raw_items:
        item = _mapping(raw, "instrument")
        price = _mapping(item.get("priceFilter"), "priceFilter")
        lot = _mapping(item.get("lotSizeFilter"), "lotSizeFilter")
        quote_asset = _required_text(item, "quoteCoin")
        settlement = str(item.get("settleCoin", "")).strip() or quote_asset
        leverage = item.get("leverageFilter")
        maximum_leverage = None
        if category == "linear":
            leverage_filter = _mapping(leverage, "leverageFilter")
            maximum_leverage = _decimal(
                leverage_filter.get("maxLeverage"), "maximum_leverage"
            )
        maximum_quantity = lot.get("maxOrderQty", lot.get("maxLimitOrderQty"))
        minimum_notional = lot.get("minNotionalValue", lot.get("minOrderAmt"))
        status = _required_text(item, "status")
        instruments.append(
            InstrumentSpec(
                instrument=InstrumentId(
                    venue="BYBIT",
                    product_type=CATEGORY_PRODUCTS[category],
                    symbol=_required_text(item, "symbol"),
                    settlement_asset=settlement,
                ),
                base_asset=_required_text(item, "baseCoin"),
                quote_asset=quote_asset,
                status=status,
                is_trading=status == "Trading",
                price_tick=_decimal(price.get("tickSize"), "price_tick"),
                quantity_step=_decimal(lot.get("qtyStep"), "quantity_step"),
                minimum_quantity=_decimal(
                    lot.get("minOrderQty"), "minimum_quantity"
                ),
                maximum_quantity=_decimal(maximum_quantity, "maximum_quantity"),
                minimum_price=_decimal(price.get("minPrice"), "minimum_price"),
                maximum_price=_decimal(price.get("maxPrice"), "maximum_price"),
                minimum_notional=(
                    _decimal(minimum_notional, "minimum_notional")
                    if minimum_notional not in {None, ""}
                    else None
                ),
                maximum_leverage=maximum_leverage,
            )
        )
    symbols = [item.instrument.symbol for item in instruments]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Bybit instrument page contains duplicate symbols")
    server_ms = int(payload.get("time", 0))
    if server_ms <= 0:
        raise ValueError("Bybit response time must be positive Unix milliseconds")
    cursor = str(result.get("nextPageCursor", "")).strip() or None
    return BybitInstrumentPage(
        category=category,
        instruments=tuple(instruments),
        next_cursor=cursor,
        server_time=datetime.fromtimestamp(server_ms / 1000, tz=UTC),
    )
