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
    ) -> None:
        if active_codes is None:
            import trading_platform.vendor.iqoptionapi.iqoptionapi.constants as operation_codes

            active_codes = operation_codes.ACTIVES
        self._api = api
        self._active_codes = active_codes
        self._asset_id_lookup = asset_id_lookup
        self._on_connection_lost = on_connection_lost

    async def place_binary_order(
        self, command: BinaryOrderCommand
    ) -> BinaryOrderSubmission:
        base = self._base_symbol(command.asset)
        candidates = (f"{base}-OTC", f"{base}-op")
        available: list[tuple[str, int]] = []

        for symbol in candidates:
            asset_id = self._active_codes.get(symbol)
            if asset_id is None and self._asset_id_lookup is not None:
                asset_id = self._asset_id_lookup(symbol)
            if asset_id is not None:
                available.append((symbol, asset_id))

        if not available:
            return BinaryOrderSubmission(
                accepted=False,
                error=(
                    f"No OTC variant found for {command.asset}. "
                    "This adapter only executes OTC markets."
                ),
            )

        return await asyncio.to_thread(self._submit_available, command, available)

    def _submit_available(
        self,
        command: BinaryOrderCommand,
        available: list[tuple[str, int]],
    ) -> BinaryOrderSubmission:
        """Run the complete blocking broker fallback sequence in one worker."""
        last_error = "Unknown error"
        for symbol, asset_id in available:
            self._active_codes[symbol] = asset_id
            try:
                result = self._api.buy(
                    float(command.amount),
                    symbol,
                    command.direction.value,
                    command.duration_minutes,
                )
            except Exception as exc:
                message = str(exc)
                if self._is_connection_error(exc, message):
                    if self._on_connection_lost is not None:
                        self._on_connection_lost()
                    return BinaryOrderSubmission(
                        accepted=False,
                        error="Connection lost",
                        broker_symbol=symbol,
                    )
                last_error = message
                continue

            if isinstance(result, tuple) and len(result) >= 2:
                accepted, order_id = bool(result[0]), result[1]
                if accepted and order_id:
                    return BinaryOrderSubmission(
                        accepted=True,
                        order_id=order_id,
                        broker_symbol=symbol,
                    )
                last_error = str(order_id) if order_id else "Rejected"
            elif result is None:
                last_error = "No response"
            else:
                last_error = str(result)

        return BinaryOrderSubmission(accepted=False, error=last_error)

    @staticmethod
    def _base_symbol(asset: str) -> str:
        return (
            asset.upper()
            .replace("-OTC", "")
            .replace("-OP", "")
            .replace("_OTC", "")
            .replace("OTC", "")
            .strip()
        )

    @staticmethod
    def _is_connection_error(exc: Exception, message: str) -> bool:
        return isinstance(exc, ConnectionError) or any(
            marker in message.lower() for marker in ("closed", "connection")
        )
