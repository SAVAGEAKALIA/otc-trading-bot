"""Replace local account projections with a broker-authoritative snapshot."""

from typing import Protocol

from trading_platform.storage.projections import AccountSnapshot
from trading_platform.storage.repository import LedgerRepository


class AccountStateGateway(Protocol):
    async def get_account_snapshot(self) -> AccountSnapshot: ...


class AccountReconciler:
    def __init__(self, repository: LedgerRepository, gateway: AccountStateGateway) -> None:
        self.repository = repository
        self.gateway = gateway

    async def reconcile(self) -> AccountSnapshot:
        snapshot = await self.gateway.get_account_snapshot()
        self.repository.replace_account_snapshot(snapshot)
        return snapshot
