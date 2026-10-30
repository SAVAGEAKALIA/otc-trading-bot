"""Recover local order state from broker truth without blind resubmission."""

from trading_platform.domain.orders import OrderStatus
from trading_platform.storage.repository import LedgerOrder, LedgerRepository

from .order_manager import ExecutionGateway, apply_broker_snapshot


class OrderReconciler:
    def __init__(self, repository: LedgerRepository, gateway: ExecutionGateway) -> None:
        self.repository = repository
        self.gateway = gateway

    async def reconcile_open_orders(self) -> list[LedgerOrder]:
        results: list[LedgerOrder] = []
        for local in self.repository.list_open_orders():
            if local.status is OrderStatus.INTENT_RECORDED:
                continue
            broker = await self.gateway.get_order(local.client_order_id)
            if broker is None:
                if local.status is not OrderStatus.UNKNOWN:
                    local = self.repository.transition(
                        local.client_order_id,
                        OrderStatus.UNKNOWN,
                        payload={"reason": "broker could not confirm order"},
                    )
                results.append(local)
                continue
            results.append(
                apply_broker_snapshot(
                    self.repository,
                    broker,
                    expected_client_order_id=local.client_order_id,
                )
            )
        return results
