"""Capability-limited orchestration for Bybit V5 public REST data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol

from trading_platform.domain.instruments import InstrumentSpec

from .instruments import normalize_instrument_page
from .tickers import BybitTickerPage, normalize_ticker_page


class PublicJsonTransport(Protocol):
    async def get_json(
        self, path: str, params: Mapping[str, str]
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BybitInstrumentCatalog:
    category: str
    instruments: tuple[InstrumentSpec, ...]
    pages: int
    server_time: datetime

    @property
    def by_symbol(self) -> Mapping[str, InstrumentSpec]:
        return MappingProxyType(
            {item.instrument.symbol: item for item in self.instruments}
        )


class BybitPublicDataClient:
    """Expose only public instrument and ticker capabilities."""

    def __init__(self, transport: PublicJsonTransport) -> None:
        self._transport = transport

    async def get_instruments(
        self, category: str, *, maximum_pages: int = 20
    ) -> BybitInstrumentCatalog:
        if maximum_pages <= 0:
            raise ValueError("maximum_pages must be positive")
        normalized_category = category.strip().lower()
        cursor: str | None = None
        seen_cursors: set[str] = set()
        instruments: list[InstrumentSpec] = []
        latest_server_time: datetime | None = None
        for page_number in range(1, maximum_pages + 1):
            params = {"category": normalized_category, "limit": "1000"}
            if cursor is not None:
                params["cursor"] = cursor
            payload = await self._transport.get_json(
                "/v5/market/instruments-info", params
            )
            page = normalize_instrument_page(
                payload, expected_category=normalized_category
            )
            instruments.extend(page.instruments)
            latest_server_time = page.server_time
            if page.next_cursor is None:
                symbols = [item.instrument.symbol for item in instruments]
                if len(symbols) != len(set(symbols)):
                    raise ValueError("Bybit instrument catalog contains duplicate symbol")
                return BybitInstrumentCatalog(
                    category=normalized_category,
                    instruments=tuple(instruments),
                    pages=page_number,
                    server_time=latest_server_time,
                )
            if page.next_cursor in seen_cursors:
                raise RuntimeError("Bybit instrument pagination returned a repeated cursor")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        raise RuntimeError("Bybit instrument pagination exceeded maximum_pages")

    async def get_tickers(
        self, category: str, *, catalog: BybitInstrumentCatalog
    ) -> BybitTickerPage:
        normalized_category = category.strip().lower()
        if catalog.category != normalized_category:
            raise ValueError("ticker category does not match instrument catalog")
        payload = await self._transport.get_json(
            "/v5/market/tickers", {"category": normalized_category}
        )
        instruments = {
            symbol: spec.instrument for symbol, spec in catalog.by_symbol.items()
        }
        return normalize_ticker_page(
            payload,
            expected_category=normalized_category,
            instruments=instruments,
        )
