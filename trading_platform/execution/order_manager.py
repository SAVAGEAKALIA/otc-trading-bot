"""Crash-aware order submission service."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from trading_platform.domain.orders import OrderIntent, OrderStatus
from trading_platform.storage.repository import LedgerOrder, LedgerRepository


@dataclass(frozen=True, slots=True)
class BrokerExecution:
    execution_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.execution_id.strip():
            raise ValueError("execution_id must not be empty")
        if self.quantity <= 0 or self.price <= 0 or self.fee < 0:
            raise ValueError("execution quantity/price must be positive and fee non-negative")


@dataclass(frozen=True, slots=True)
class BrokerOrderSnapshot:
    client_order_id: str
    broker_order_id: str
    status: OrderStatus
    executions: tuple[BrokerExecution, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.client_order_id.strip() or not self.broker_order_id.strip():
            raise ValueError("broker snapshot IDs must not be empty")
        if self.status in {
            OrderStatus.INTENT_RECORDED,
            OrderStatus.SUBMISSION_STARTED,
        }:
            raise ValueError("broker cannot report a local-only order status")


class ExecutionGateway(Protocol):
    async def submit_order(self, intent: OrderIntent) -> BrokerOrderSnapshot: ...

    async def get_order(self, client_order_id: str) -> BrokerOrderSnapshot | None: ...


class OrderManager:
    def __init__(self, repository: LedgerRepository, gateway: ExecutionGateway) -> None:
        self.repository = repository
        self.gateway = gateway

    async def submit(self, intent: OrderIntent) -> LedgerOrder:
        current = self.repository.record_intent(intent)
        if current.status is not OrderStatus.INTENT_RECORDED:
            return current
        if not self.repository.claim_submission(intent.client_order_id):
            return self.repository.get_order(intent.client_order_id)
        snapshot = await self.gateway.submit_order(intent)
        return apply_broker_snapshot(
            self.repository, snapshot, expected_client_order_id=intent.client_order_id
        )


def apply_broker_snapshot(
    repository: LedgerRepository,
    snapshot: BrokerOrderSnapshot,
    *,
    expected_client_order_id: str | None = None,
) -> LedgerOrder:
    if (
        expected_client_order_id is not None
        and snapshot.client_order_id != expected_client_order_id
    ):
        raise ValueError("broker response client_order_id mismatch")
    current = repository.get_order(snapshot.client_order_id)
    if current.status is OrderStatus.SUBMISSION_STARTED and snapshot.status in {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.EXPIRED,
    }:
        current = repository.transition(
            snapshot.client_order_id,
            OrderStatus.ACKNOWLEDGED,
            broker_order_id=snapshot.broker_order_id,
        )
    if current.status is not snapshot.status:
        current = repository.transition(
            snapshot.client_order_id,
            snapshot.status,
            broker_order_id=snapshot.broker_order_id,
            payload={"error": snapshot.error} if snapshot.error else {},
            executions_to_record=snapshot.executions,
        )
    elif snapshot.executions:
        repository.record_executions(snapshot.client_order_id, snapshot.executions)
    return repository.get_order(snapshot.client_order_id)
