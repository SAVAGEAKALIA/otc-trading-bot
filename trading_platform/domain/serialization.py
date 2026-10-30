"""Explicit JSON-safe records for domain boundaries and durable messages."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from .environment import TradingEnvironment
from .events import DomainEvent
from .instruments import InstrumentId, ProductType
from .money import Money, Quantity
from .orders import (
    BinaryDirection,
    BinaryOptionTerms,
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
)
from .risk import RiskDecision


def _instrument_to_record(instrument: InstrumentId) -> dict[str, str]:
    return {
        "venue": instrument.venue,
        "product_type": instrument.product_type.value,
        "symbol": instrument.symbol,
        "settlement_asset": instrument.settlement_asset,
    }


def _instrument_from_record(record: Mapping[str, Any]) -> InstrumentId:
    return InstrumentId(
        venue=str(record["venue"]),
        product_type=ProductType(str(record["product_type"])),
        symbol=str(record["symbol"]),
        settlement_asset=str(record["settlement_asset"]),
    )


def _risk_to_record(decision: RiskDecision) -> dict[str, Any]:
    return {
        "decision_id": str(decision.decision_id),
        "signal_id": str(decision.signal_id),
        "environment": decision.environment.value,
        "is_approved": decision.is_approved,
        "limits_snapshot": dict(decision.limits_snapshot),
        "reasons": list(decision.reasons),
    }


def _risk_from_record(record: Mapping[str, Any]) -> RiskDecision:
    return RiskDecision(
        decision_id=UUID(str(record["decision_id"])),
        signal_id=UUID(str(record["signal_id"])),
        environment=TradingEnvironment(str(record["environment"])),
        is_approved=bool(record["is_approved"]),
        limits_snapshot=dict(record["limits_snapshot"]),
        reasons=tuple(str(reason) for reason in record["reasons"]),
    )


def domain_event_to_record(event: DomainEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "name": event.name,
        "environment": event.environment.value,
        "occurred_at": event.occurred_at.isoformat(),
        "received_at": event.received_at.isoformat(),
        "schema_version": event.schema_version,
        "correlation_id": str(event.correlation_id) if event.correlation_id else None,
        "causation_id": str(event.causation_id) if event.causation_id else None,
        "payload": dict(event.payload),
    }


def domain_event_from_record(record: Mapping[str, Any]) -> DomainEvent:
    correlation_id = record.get("correlation_id")
    causation_id = record.get("causation_id")
    return DomainEvent(
        event_id=UUID(str(record["event_id"])),
        name=str(record["name"]),
        environment=TradingEnvironment(str(record["environment"])),
        occurred_at=datetime.fromisoformat(str(record["occurred_at"])),
        received_at=datetime.fromisoformat(str(record["received_at"])),
        schema_version=int(record["schema_version"]),
        correlation_id=UUID(str(correlation_id)) if correlation_id else None,
        causation_id=UUID(str(causation_id)) if causation_id else None,
        payload=dict(record["payload"]),
    )


def order_intent_to_record(intent: OrderIntent) -> dict[str, Any]:
    limit_price = None
    if intent.limit_price is not None:
        limit_price = {
            "amount": str(intent.limit_price.amount),
            "currency": intent.limit_price.currency,
        }
    return {
        "client_order_id": intent.client_order_id,
        "signal_id": str(intent.signal_id),
        "risk_decision": _risk_to_record(intent.risk_decision),
        "instrument": _instrument_to_record(intent.instrument),
        "environment": intent.environment.value,
        "side": intent.side.value,
        "order_type": intent.order_type.value,
        "quantity": str(intent.quantity.value),
        "time_in_force": intent.time_in_force.value,
        "limit_price": limit_price,
        "reduce_only": intent.reduce_only,
        "binary_terms": (
            {
                "direction": intent.binary_terms.direction.value,
                "expires_at": intent.binary_terms.expires_at.isoformat(),
                "payout_ratio": str(intent.binary_terms.payout_ratio),
            }
            if intent.binary_terms is not None
            else None
        ),
    }


def order_intent_from_record(record: Mapping[str, Any]) -> OrderIntent:
    raw_price = record.get("limit_price")
    limit_price = None
    if raw_price is not None:
        limit_price = Money(
            amount=Decimal(str(raw_price["amount"])),
            currency=str(raw_price["currency"]),
        )
    raw_binary_terms = record.get("binary_terms")
    binary_terms = None
    if raw_binary_terms is not None:
        binary_terms = BinaryOptionTerms(
            direction=BinaryDirection(str(raw_binary_terms["direction"])),
            expires_at=datetime.fromisoformat(str(raw_binary_terms["expires_at"])),
            payout_ratio=Decimal(str(raw_binary_terms["payout_ratio"])),
        )
    return OrderIntent(
        client_order_id=str(record["client_order_id"]),
        signal_id=UUID(str(record["signal_id"])),
        risk_decision=_risk_from_record(record["risk_decision"]),
        instrument=_instrument_from_record(record["instrument"]),
        environment=TradingEnvironment(str(record["environment"])),
        side=OrderSide(str(record["side"])),
        order_type=OrderType(str(record["order_type"])),
        quantity=Quantity(Decimal(str(record["quantity"]))),
        time_in_force=TimeInForce(str(record["time_in_force"])),
        limit_price=limit_price,
        reduce_only=bool(record["reduce_only"]),
        binary_terms=binary_terms,
    )
