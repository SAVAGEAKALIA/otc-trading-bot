"""Apply broker-authoritative private events to the local order ledger."""

from __future__ import annotations

from collections.abc import Mapping

from trading_platform.brokers.bybit.order_events import normalize_order_event
from trading_platform.storage.repository import LedgerOrder, LedgerRepository

from .order_manager import apply_broker_snapshot


class PrivateEventReconciler:
    def __init__(self, repository: LedgerRepository) -> None:
        self.repository = repository

    def apply_bybit_event(
        self, payload: Mapping[str, object], *, expected_client_order_id: str | None = None
    ) -> LedgerOrder:
        snapshot = normalize_order_event(
            payload, expected_client_order_id=expected_client_order_id
        )
        return apply_broker_snapshot(
            self.repository,
            snapshot,
            expected_client_order_id=expected_client_order_id,
        )
