"""Compatibility adapter for IQ Option fixed-expiry OTC execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any


class BinaryDirection(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True, slots=True)
class BinaryOrderCommand:
    asset: str
    direction: BinaryDirection
    amount: Decimal
    duration_minutes: int
    metadata: dict | None = None


@dataclass(frozen=True, slots=True)
class BinaryOrderSubmission:
    accepted: bool
    order_id: Any | None = None
    error: str | None = None
    broker_symbol: str | None = None


class IQOptionBinaryExecutionAdapter:
    """Translate a binary command into the legacy IQ Option ``buy`` call."""

    def __init__(
        self,
        api: Any,
        *,
        active_codes: MutableMapping[str, int] | None = None,
        asset_id_lookup: Callable[[str], int | None] | None = None,
        on_connection_lost: Callable[[], None] | None = None,
        ledger_path: str | None = None,
        enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        if active_codes is None:
            import trading_platform.vendor.iqoptionapi.iqoptionapi.constants as operation_codes

            active_codes = operation_codes.ACTIVES
        import os
        from .practice import PracticeExecution
        self.practice = PracticeExecution(api, ledger_path or os.path.join(os.environ.get("DATA_DIR", "data"), "practice-orders.sqlite3"), enabled)
        self._api = api
        self._active_codes = active_codes
        self._asset_id_lookup = asset_id_lookup
        self._on_connection_lost = on_connection_lost

    async def place_binary_order(self, command: BinaryOrderCommand) -> BinaryOrderSubmission:
        accepted, result = await asyncio.to_thread(self.practice.submit, command)
        return BinaryOrderSubmission(accepted=accepted,
            order_id=result if accepted else None,
            error=None if accepted else str(result), broker_symbol=command.asset)
