"""Normalize Bybit private order and execution events into OMS snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from trading_platform.domain.orders import OrderStatus
from trading_platform.execution.order_manager import BrokerExecution, BrokerOrderSnapshot


_STATUS = {
    "New": OrderStatus.ACKNOWLEDGED,
    "Created": OrderStatus.ACKNOWLEDGED,
    "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
    "Filled": OrderStatus.FILLED,
    "Cancelled": OrderStatus.CANCELED,
    "Rejected": OrderStatus.REJECTED,
    "Deactivated": OrderStatus.CANCELED,
    "Expired": OrderStatus.EXPIRED,
}


def _decimal(value: Any, field: str, *, zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Bybit {field} is not decimal") from exc
    if not parsed.is_finite() or (parsed < 0 if zero else parsed <= 0):
        raise ValueError(f"Bybit {field} has invalid value")
    return parsed


def normalize_order_event(
    payload: Mapping[str, Any], *, expected_client_order_id: str | None = None
) -> BrokerOrderSnapshot:
    if str(payload.get("topic", "")).strip() not in {"order", "execution"}:
        raise ValueError("Bybit private payload is not an order/execution event")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ValueError("Bybit private order event must contain one object")
    item = data[0]
    client_id = str(item.get("orderLinkId", "")).strip()
    broker_id = str(item.get("orderId", "")).strip()
    status_name = str(item.get("orderStatus", "")).strip()
    if not client_id or not broker_id or status_name not in _STATUS:
        raise ValueError("Bybit private order event identity/status is invalid")
    if expected_client_order_id is not None and client_id != expected_client_order_id:
        raise ValueError("Bybit private event client order ID mismatch")
    executions: tuple[BrokerExecution, ...] = ()
    execution_id = str(item.get("execId", "")).strip()
    if execution_id:
        executions = (BrokerExecution(
            execution_id=execution_id,
            quantity=_decimal(item.get("execQty"), "execution quantity"),
            price=_decimal(item.get("execPrice"), "execution price"),
            fee=_decimal(item.get("execFee", "0"), "execution fee", zero=True),
        ),)
    return BrokerOrderSnapshot(client_id, broker_id, _STATUS[status_name], executions)
