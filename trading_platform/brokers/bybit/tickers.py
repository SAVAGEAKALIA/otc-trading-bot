"""Normalize Bybit V5 public ticker responses against a verified catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.market_data import MarketTicker


CATEGORY_PRODUCTS = {
    "spot": ProductType.SPOT,
    "linear": ProductType.LINEAR_PERPETUAL,
}


@dataclass(frozen=True, slots=True)
class BybitTickerPage:
    category: str
    tickers: tuple[MarketTicker, ...]
    server_time: datetime


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Bybit {name} must be an object")
    return value


def _decimal(value: Any, name: str, *, optional: bool = False) -> Decimal | None:
    if optional and value in {None, ""}:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Bybit {name} is not a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"Bybit {name} must be finite")
    return result


def _future_time(value: Any) -> datetime | None:
    if value in {None, "", "0", 0}:
        return None
    milliseconds = int(value)
    if milliseconds <= 0:
        raise ValueError("Bybit nextFundingTime must be positive milliseconds")
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def normalize_ticker_page(
    payload: Mapping[str, Any],
    *,
    expected_category: str,
    instruments: Mapping[str, InstrumentId],
) -> BybitTickerPage:
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
    server_ms = int(payload.get("time", 0))
    if server_ms <= 0:
        raise ValueError("Bybit response time must be positive Unix milliseconds")
    observed_at = datetime.fromtimestamp(server_ms / 1000, tz=UTC)
    raw_items = result.get("list")
    if not isinstance(raw_items, list):
        raise ValueError("Bybit ticker list must be an array")
    tickers = []
    for raw in raw_items:
        item = _mapping(raw, "ticker")
        symbol = str(item.get("symbol", "")).strip().upper()
        instrument = instruments.get(symbol)
        if instrument is None:
            raise ValueError(f"Bybit ticker symbol is absent from catalog: {symbol}")
        if instrument.venue != "BYBIT" or instrument.product_type is not CATEGORY_PRODUCTS[category]:
            raise ValueError(f"Bybit ticker catalog category mismatch: {symbol}")
        derivative = category == "linear"
        tickers.append(
            MarketTicker(
                instrument=instrument,
                observed_at=observed_at,
                last_price=_decimal(item.get("lastPrice"), "last_price"),
                bid_price=_decimal(item.get("bid1Price"), "bid_price"),
                bid_size=_decimal(item.get("bid1Size"), "bid_size"),
                ask_price=_decimal(item.get("ask1Price"), "ask_price"),
                ask_size=_decimal(item.get("ask1Size"), "ask_size"),
                mark_price=(
                    _decimal(item.get("markPrice"), "mark_price") if derivative else None
                ),
                index_price=(
                    _decimal(item.get("indexPrice"), "index_price")
                    if derivative
                    else None
                ),
                open_interest=(
                    _decimal(item.get("openInterest"), "open_interest", optional=True)
                    if derivative
                    else None
                ),
                funding_rate=(
                    _decimal(item.get("fundingRate"), "funding_rate", optional=True)
                    if derivative
                    else None
                ),
                next_funding_at=(
                    _future_time(item.get("nextFundingTime")) if derivative else None
                ),
            )
        )
    symbols = [item.instrument.symbol for item in tickers]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Bybit ticker page contains duplicate symbols")
    return BybitTickerPage(
        category=category,
        tickers=tuple(tickers),
        server_time=observed_at,
    )
