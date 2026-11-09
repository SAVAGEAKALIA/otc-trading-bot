"""Strict normalization of IQ Option closed-option history."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol

from trading_platform.domain.orders import OrderType
from trading_platform.domain.settlements import (
    BinarySettlement,
    BinarySettlementOutcome,
)
from trading_platform.storage.repository import LedgerOrder


class IQOptionClosedOptionsPort(Protocol):
    async def find_closed_option(
        self, broker_order_id: str
    ) -> Mapping[str, Any] | None: ...


class IQOptionSettlementGateway:
    """Convert one broker history record without polling or balance inference."""

    def __init__(self, history: IQOptionClosedOptionsPort) -> None:
        self.history = history

    async def get_binary_settlement(
        self, order: LedgerOrder
    ) -> BinarySettlement | None:
        if order.intent.order_type is not OrderType.BINARY:
            raise ValueError("IQ Option settlement requires a binary order")
        if order.broker_order_id is None:
            raise ValueError("IQ Option settlement requires broker_order_id")
        expected_id = str(order.broker_order_id)
        match = await self.history.find_closed_option(expected_id)
        if match is None:
            return None
        if _order_id(match.get("id")) != expected_id:
            raise ValueError("IQ Option history returned the wrong broker order")

        status = str(match.get("win", "")).strip().lower()
        if not status:
            return None
        outcomes = {
            "win": BinarySettlementOutcome.WIN,
            "loose": BinarySettlementOutcome.LOSS,
            "lose": BinarySettlementOutcome.LOSS,
            "loss": BinarySettlementOutcome.LOSS,
            "equal": BinarySettlementOutcome.TIE,
            "refund": BinarySettlementOutcome.VOID,
            "void": BinarySettlementOutcome.VOID,
        }
        if status not in outcomes:
            raise ValueError(f"unsupported IQ Option settlement status: {status}")

        stake = _decimal(match.get("amount"), "stake")
        if stake != order.intent.quantity.value:
            raise ValueError("broker settlement stake does not match order")
        outcome = outcomes[status]
        if outcome is BinarySettlementOutcome.WIN:
            gross_return = _decimal(match.get("win_amount"), "win_amount")
        elif outcome is BinarySettlementOutcome.LOSS:
            gross_return = Decimal("0")
            if match.get("win_amount") is not None and _decimal(
                match.get("win_amount"), "win_amount"
            ) != 0:
                raise ValueError("loss settlement reports non-zero gross return")
        else:
            gross_return = stake
            if match.get("win_amount") is not None and _decimal(
                match.get("win_amount"), "win_amount"
            ) != stake:
                raise ValueError("tie or void settlement does not return stake")
        settled_at = _timestamp(match)
        return BinarySettlement(
            venue_settlement_id=f"iqoption:{expected_id}:{int(settled_at.timestamp())}",
            client_order_id=order.client_order_id,
            broker_order_id=expected_id,
            outcome=outcome,
            stake=stake,
            gross_return=gross_return,
            net_pnl=gross_return - stake,
            settlement_asset=order.intent.instrument.settlement_asset,
            settled_at=settled_at,
            source="broker_api",
            evidence=dict(match),
        )


def _order_id(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value).strip()


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid broker {name}") from exc
    if not result.is_finite():
        raise ValueError(f"invalid broker {name}")
    return result


def _timestamp(record: Mapping[str, Any]) -> datetime:
    raw = record.get("close_time", record.get("expiration_time"))
    try:
        timestamp = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("broker settlement timestamp is missing or invalid") from exc
    if not timestamp.is_finite() or timestamp <= 0:
        raise ValueError("broker settlement timestamp is missing or invalid")
    while timestamp > Decimal("5000000000"):
        timestamp /= Decimal("1000")
    return datetime.fromtimestamp(float(timestamp), tz=UTC)
