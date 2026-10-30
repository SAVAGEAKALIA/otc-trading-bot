"""Offline validation and dispatch for Bybit private stream messages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from trading_platform.execution.order_manager import BrokerOrderSnapshot

from .order_events import normalize_order_event
from .private_stream import PrivateStreamLifecycle


@dataclass(frozen=True, slots=True)
class BybitPrivateStreamEnvelope:
    topic: str
    message_type: str
    created_at: datetime
    sequence: int
    data: tuple[Mapping[str, Any], ...]


def normalize_private_stream_envelope(
    payload: Mapping[str, Any],
) -> BybitPrivateStreamEnvelope:
    topic = str(payload.get("topic", "")).strip()
    if topic not in {"order", "execution", "wallet", "position"}:
        raise ValueError("Bybit private stream topic is not allowlisted")
    message_type = str(payload.get("type", "")).strip().lower()
    if message_type not in {"snapshot", "delta"}:
        raise ValueError("Bybit private stream message type is invalid")
    try:
        created_ms = int(payload.get("creationTime", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Bybit private stream creationTime must be integer milliseconds") from exc
    if created_ms <= 0:
        raise ValueError("Bybit private stream creationTime must be positive")
    try:
        sequence = int(payload.get("seq", -1))
    except (TypeError, ValueError) as exc:
        raise ValueError("Bybit private stream sequence must be an integer") from exc
    if sequence < 0:
        raise ValueError("Bybit private stream sequence must be non-negative")
    raw_data = payload.get("data")
    if not isinstance(raw_data, list) or not raw_data or any(
        not isinstance(item, Mapping) for item in raw_data
    ):
        raise ValueError("Bybit private stream data must be a non-empty object list")
    return BybitPrivateStreamEnvelope(
        topic=topic,
        message_type=message_type,
        created_at=datetime.fromtimestamp(created_ms / 1000, tz=UTC),
        sequence=sequence,
        data=tuple(raw_data),
    )


class BybitPrivateStreamDispatcher:
    """Sequence-gated dispatcher for normalized order/execution events."""

    def __init__(self, lifecycle: PrivateStreamLifecycle) -> None:
        self._lifecycle = lifecycle

    def dispatch(self, payload: Mapping[str, Any]) -> BrokerOrderSnapshot:
        envelope = normalize_private_stream_envelope(payload)
        if envelope.topic not in {"order", "execution"}:
            raise ValueError("Bybit private dispatcher supports order/execution topics only")
        if not self._lifecycle.connected or not self._lifecycle.subscribed:
            raise RuntimeError("Bybit private stream lifecycle is not subscribed")
        if not self._lifecycle.accept_event(envelope.topic, envelope.sequence):
            raise RuntimeError("Bybit private stream sequence gap or replay detected")
        return normalize_order_event(
            {
                "topic": envelope.topic,
                "type": envelope.message_type,
                "creationTime": int(envelope.created_at.timestamp() * 1000),
                "seq": envelope.sequence,
                "data": list(envelope.data),
            }
        )

    def healthy(self) -> bool:
        return self._lifecycle.healthy()
