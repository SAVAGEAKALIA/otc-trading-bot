"""Capability-limited Bybit V5 order execution for testnet only.

The transport is injected deliberately: this module validates intent and
normalizes exchange responses, but cannot create a network connection or load
credentials by itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import json
from typing import Any, Protocol

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.orders import OrderIntent, OrderSide, OrderStatus, OrderType
from trading_platform.execution.order_manager import BrokerOrderSnapshot

from .http_transport import RawHttpResponse, TRANSIENT_STATUSES
from .order_events import normalize_order_event


class BybitExecutionBackend(Protocol):
    async def post(
        self,
        path: str,
        payload: Mapping[str, str],
        *,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> RawHttpResponse: ...


class BybitOpenOrderReader(Protocol):
    async def get_open_orders(
        self, *, category: str, symbol: str | None = None, cursor: str | None = None
    ) -> Mapping[str, Any]: ...


class BybitPositionMode(str, Enum):
    ONE_WAY = "one_way"
    HEDGE = "hedge"


@dataclass(frozen=True, slots=True)
class BybitExecutionControls:
    category: str
    symbol: str
    position_mode: BybitPositionMode
    buy_leverage: Decimal
    sell_leverage: Decimal

    def __post_init__(self) -> None:
        category = self.category.strip().lower()
        symbol = self.symbol.strip().upper()
        if category != "linear":
            raise ValueError("Bybit execution controls require the linear category")
        if not symbol:
            raise ValueError("Bybit execution-control symbol must not be empty")
        for name in ("buy_leverage", "sell_leverage"):
            value = getattr(self, name)
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "symbol", symbol)


class BybitExecutionControlsReader(Protocol):
    async def get_execution_controls(
        self, *, category: str, symbol: str
    ) -> BybitExecutionControls: ...


@dataclass(frozen=True, slots=True)
class BybitExecutionConfig:
    timeout_seconds: float = 10.0
    maximum_response_bytes: int = 1 * 1024 * 1024
    maximum_attempts: int = 3
    expected_position_mode: BybitPositionMode = BybitPositionMode.ONE_WAY
    expected_leverage: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.maximum_response_bytes <= 0 or self.maximum_attempts < 1:
            raise ValueError("Bybit execution limits must be positive")
        if not self.expected_leverage.is_finite() or self.expected_leverage <= 0:
            raise ValueError("expected leverage must be finite and positive")


class BybitTestnetExecutionGateway:
    """ExecutionGateway implementation with create/cancel/amend only."""

    def __init__(
        self,
        backend: BybitExecutionBackend,
        *,
        environment: TradingEnvironment = TradingEnvironment.TESTNET,
        config: BybitExecutionConfig = BybitExecutionConfig(),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        private_reader: BybitOpenOrderReader | None = None,
        execution_controls: BybitExecutionControlsReader | None = None,
    ) -> None:
        if environment is not TradingEnvironment.TESTNET:
            raise ValueError("Bybit execution is restricted to TESTNET")
        self._backend = backend
        self._config = config
        self._sleep = sleep
        self._private_reader = private_reader
        self._execution_controls = execution_controls

    async def submit_order(self, intent: OrderIntent) -> BrokerOrderSnapshot:
        if intent.environment is not TradingEnvironment.TESTNET:
            raise ValueError("Bybit execution requires a TESTNET order intent")
        if intent.instrument.venue != "BYBIT":
            raise ValueError("Bybit gateway requires a BYBIT instrument")
        if intent.order_type not in {OrderType.MARKET, OrderType.LIMIT}:
            raise ValueError("Bybit gateway supports MARKET and LIMIT orders only")
        payload = self._order_payload(intent)
        if payload["category"] == "linear":
            controls = await self._verify_execution_controls(
                category=payload["category"], symbol=payload["symbol"]
            )
            payload["positionIdx"] = str(
                self._position_idx_for_side(
                    controls.position_mode,
                    "Buy" if intent.side is OrderSide.BUY else "Sell",
                )
            )
        response = await self._request(
            "/v5/order/create",
            payload,
            recovery_client_order_id=intent.client_order_id,
        )
        if isinstance(response, BrokerOrderSnapshot):
            return response
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise ValueError("Bybit create-order result must be an object")
        order_id = str(result.get("orderId", "")).strip()
        link_id = str(result.get("orderLinkId", intent.client_order_id)).strip()
        if not order_id or link_id != intent.client_order_id:
            raise ValueError("Bybit create-order response IDs are invalid")
        return BrokerOrderSnapshot(link_id, order_id, OrderStatus.ACKNOWLEDGED)

    async def get_order(self, client_order_id: str) -> BrokerOrderSnapshot | None:
        normalized_id = client_order_id.strip()
        if not normalized_id:
            raise ValueError("client_order_id must not be empty")
        if self._private_reader is None:
            raise RuntimeError("Bybit private order reader is not configured")
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            payload = await self._private_reader.get_open_orders(
                category="linear", cursor=cursor
            )
            result = payload.get("result")
            if not isinstance(result, Mapping):
                raise ValueError("Bybit realtime order result must be an object")
            raw_items = result.get("list")
            if not isinstance(raw_items, list):
                raise ValueError("Bybit realtime order list must be an array")
            matches = [
                item for item in raw_items
                if isinstance(item, Mapping)
                and str(item.get("orderLinkId", "")).strip() == normalized_id
            ]
            if len(matches) > 1:
                raise ValueError("Bybit realtime order response contains duplicate client order IDs")
            if matches:
                return normalize_order_event(
                    {"topic": "order", "data": [matches[0]]},
                    expected_client_order_id=normalized_id,
                )
            next_cursor = str(result.get("nextPageCursor", "")).strip() or None
            if next_cursor is None:
                return None
            if next_cursor in seen:
                raise ValueError("Bybit realtime order pagination cursor repeated")
            seen.add(next_cursor)
            cursor = next_cursor

    async def cancel_order(self, *, category: str, symbol: str, client_order_id: str) -> str:
        self._validate_identity(category, symbol, client_order_id)
        if category.strip().lower() == "linear":
            await self._verify_execution_controls(
                category="linear", symbol=symbol
            )
        payload = {"category": category.lower(), "symbol": symbol.upper(), "orderLinkId": client_order_id}
        result = await self._request(
            "/v5/order/cancel", payload, recovery_client_order_id=client_order_id
        )
        return self._mutation_result_order_id(result, client_order_id)

    async def amend_order(
        self, *, category: str, symbol: str, client_order_id: str,
        quantity: Decimal | None = None, price: Decimal | None = None,
    ) -> str:
        self._validate_identity(category, symbol, client_order_id)
        if category.strip().lower() == "linear":
            await self._verify_execution_controls(
                category="linear", symbol=symbol
            )
        if quantity is None and price is None:
            raise ValueError("amend requires quantity or price")
        payload = {"category": category.lower(), "symbol": symbol.upper(), "orderLinkId": client_order_id}
        if quantity is not None:
            if not quantity.is_finite() or quantity <= 0: raise ValueError("quantity must be positive")
            payload["qty"] = str(quantity)
        if price is not None:
            if not price.is_finite() or price <= 0: raise ValueError("price must be positive")
            payload["price"] = str(price)
        result = await self._request(
            "/v5/order/amend", payload, recovery_client_order_id=client_order_id
        )
        return self._mutation_result_order_id(result, client_order_id)

    async def submit_protective_exit(
        self,
        *,
        category: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        trigger_price: Decimal,
        client_order_id: str,
        position_idx: int = 0,
    ) -> BrokerOrderSnapshot:
        """Submit a testnet-only reduce-only market stop request."""
        normalized_category = category.strip().lower()
        if normalized_category != "linear":
            raise ValueError("protective exits require the linear category")
        self._validate_identity(category, symbol, client_order_id)
        normalized_side = side.strip().title()
        if normalized_side not in {"Buy", "Sell"}:
            raise ValueError("protective exit side must be Buy or Sell")
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("protective exit quantity must be positive")
        if not trigger_price.is_finite() or trigger_price <= 0:
            raise ValueError("protective exit trigger price must be positive")
        if position_idx not in {0, 1, 2}:
            raise ValueError("position_idx must be 0, 1, or 2")
        controls = await self._verify_execution_controls(
            category="linear", symbol=symbol
        )
        expected_position_idx = self._protective_position_idx_for_side(
            controls.position_mode, normalized_side
        )
        if position_idx != expected_position_idx:
            raise ValueError("protective exit position_idx does not match verified position mode")
        if position_idx == 1 and normalized_side != "Sell":
            raise ValueError("the Buy hedge leg requires a Sell protective exit")
        if position_idx == 2 and normalized_side != "Buy":
            raise ValueError("the Sell hedge leg requires a Buy protective exit")
        payload = {
            "category": "linear",
            "symbol": symbol.strip().upper(),
            "side": normalized_side,
            "orderType": "Market",
            "qty": str(quantity),
            "orderLinkId": client_order_id.strip(),
            "triggerPrice": str(trigger_price),
            "triggerDirection": "2" if normalized_side == "Sell" else "1",
            "reduceOnly": "true",
            "closeOnTrigger": "true",
            "positionIdx": str(position_idx),
        }
        result = await self._request(
            "/v5/order/create",
            payload,
            recovery_client_order_id=client_order_id,
        )
        if isinstance(result, BrokerOrderSnapshot):
            return result
        raw_result = result.get("result")
        if not isinstance(raw_result, Mapping):
            raise ValueError("Bybit protective-exit result must be an object")
        broker_order_id = str(raw_result.get("orderId", "")).strip()
        returned_client_id = str(raw_result.get("orderLinkId", client_order_id)).strip()
        if not broker_order_id or returned_client_id != client_order_id.strip():
            raise ValueError("Bybit protective-exit response IDs are invalid")
        return BrokerOrderSnapshot(
            returned_client_id, broker_order_id, OrderStatus.ACKNOWLEDGED
        )

    @staticmethod
    def _position_idx_for_side(mode: BybitPositionMode, side: str) -> int:
        if mode is BybitPositionMode.ONE_WAY:
            return 0
        return 1 if side == "Buy" else 2

    @staticmethod
    def _protective_position_idx_for_side(mode: BybitPositionMode, side: str) -> int:
        if mode is BybitPositionMode.ONE_WAY:
            return 0
        return 1 if side == "Sell" else 2

    def _order_payload(self, intent: OrderIntent) -> dict[str, str]:
        payload = {
            "category": "linear" if intent.instrument.product_type.value == "linear_perpetual" else "spot",
            "symbol": intent.instrument.symbol,
            "side": "Buy" if intent.side is OrderSide.BUY else "Sell",
            "orderType": "Market" if intent.order_type is OrderType.MARKET else "Limit",
            "qty": str(intent.quantity.value),
            "orderLinkId": intent.client_order_id,
        }
        if intent.limit_price is not None: payload["price"] = str(intent.limit_price.amount)
        if intent.reduce_only: payload["reduceOnly"] = "true"
        if intent.time_in_force.value: payload["timeInForce"] = intent.time_in_force.value.upper().replace("_", "")
        return payload

    async def _verify_execution_controls(
        self, *, category: str, symbol: str
    ) -> BybitExecutionControls:
        if self._execution_controls is None:
            raise RuntimeError("Bybit execution controls reader is not configured")
        controls = await self._execution_controls.get_execution_controls(
            category=category, symbol=symbol
        )
        if controls.category != category.strip().lower() or controls.symbol != symbol.strip().upper():
            raise ValueError("Bybit execution controls identity mismatch")
        if controls.position_mode is not self._config.expected_position_mode:
            raise ValueError("Bybit position mode mismatch")
        expected = self._config.expected_leverage
        if controls.buy_leverage != expected or controls.sell_leverage != expected:
            raise ValueError("Bybit leverage mismatch")
        return controls

    @staticmethod
    def _validate_identity(category: str, symbol: str, client_order_id: str) -> None:
        if category.strip().lower() not in {"spot", "linear"}: raise ValueError("unsupported Bybit category")
        if not symbol.strip() or not client_order_id.strip(): raise ValueError("order identity cannot be empty")

    @staticmethod
    def _result_order_id(payload: Mapping[str, Any], fallback: str) -> str:
        result = payload.get("result")
        if not isinstance(result, Mapping): raise ValueError("Bybit order result must be an object")
        return str(result.get("orderId") or result.get("orderLinkId") or fallback).strip()

    @classmethod
    def _mutation_result_order_id(
        cls,
        payload: Mapping[str, Any] | BrokerOrderSnapshot,
        fallback: str,
    ) -> str:
        if isinstance(payload, BrokerOrderSnapshot):
            return payload.broker_order_id
        return cls._result_order_id(payload, fallback)

    async def _request(
        self,
        path: str,
        payload: Mapping[str, str],
        *,
        recovery_client_order_id: str | None = None,
    ) -> Mapping[str, Any] | BrokerOrderSnapshot:
        for attempt in range(1, self._config.maximum_attempts + 1):
            try:
                response = await self._backend.post(path, payload, timeout_seconds=self._config.timeout_seconds, maximum_bytes=self._config.maximum_response_bytes)
            except (ConnectionError, TimeoutError):
                if recovery_client_order_id and self._private_reader is not None:
                    confirmed = await self.get_order(recovery_client_order_id)
                    if confirmed is not None:
                        return confirmed
                if attempt == self._config.maximum_attempts: raise
                await self._sleep(0.25 * 2 ** (attempt - 1)); continue
            if len(response.content) > self._config.maximum_response_bytes: raise ValueError("Bybit execution response exceeds maximum response bytes")
            if response.status in TRANSIENT_STATUSES or response.status == 429:
                if attempt == self._config.maximum_attempts: raise RuntimeError("Bybit execution transient HTTP retries exhausted")
                await self._sleep(0.25 * 2 ** (attempt - 1)); continue
            if not 200 <= response.status < 300: raise RuntimeError(f"Bybit execution HTTP {response.status}")
            if "application/json" not in {str(k).lower(): str(v) for k, v in response.headers.items()}.get("content-type", "").lower(): raise ValueError("Bybit execution response must be JSON")
            try: parsed = json.loads(response.content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError("Bybit execution response contains invalid JSON") from exc
            if not isinstance(parsed, Mapping): raise ValueError("Bybit execution JSON root must be an object")
            code = int(parsed.get("retCode", -1))
            if code == 10006:
                if attempt == self._config.maximum_attempts: raise RuntimeError("Bybit execution rate-limit retries exhausted")
                await self._sleep(0.25 * 2 ** (attempt - 1)); continue
            if code != 0: raise ValueError(f"Bybit API error {code}: {parsed.get('retMsg', '')}")
            return parsed
        raise RuntimeError("Bybit execution retry loop terminated unexpectedly")
