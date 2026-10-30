"""Restart-safe reconciliation of broker-confirmed binary settlements."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.settlements import BinarySettlement
from trading_platform.domain.time import require_utc
from trading_platform.storage.repository import LedgerOrder, LedgerRepository


class BinarySettlementGateway(Protocol):
    async def get_binary_settlement(
        self, order: LedgerOrder
    ) -> BinarySettlement | None: ...


class BinarySettlementReconciler:
    def __init__(
        self,
        repository: LedgerRepository,
        gateway: BinarySettlementGateway,
        environment: TradingEnvironment,
    ) -> None:
        self.repository = repository
        self.gateway = gateway
        self.environment = environment

    async def reconcile_due(self, now: datetime) -> list[BinarySettlement]:
        require_utc(now, "now")
        recorded: list[BinarySettlement] = []
        for order in self.repository.list_due_unsettled_binary_orders(
            now, self.environment
        ):
            broker_order_id = order.broker_order_id
            if broker_order_id is None:
                continue
            settlement = await self.gateway.get_binary_settlement(order)
            if settlement is None:
                continue
            if settlement.client_order_id != order.client_order_id:
                raise ValueError("settlement client_order_id does not match ledger")
            if settlement.broker_order_id != broker_order_id:
                raise ValueError("settlement broker_order_id does not match ledger")
            if self.repository.record_binary_settlement(settlement):
                recorded.append(settlement)
        return recorded
