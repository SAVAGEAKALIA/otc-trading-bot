"""At-least-once transactional outbox delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .repository import LedgerRepository


class EventSink(Protocol):
    async def publish(
        self,
        *,
        event_key: str,
        topic: str,
        payload: Mapping[str, Any],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class OutboxRunResult:
    published: int
    failed: int


class OutboxPublisher:
    def __init__(self, repository: LedgerRepository, sink: EventSink) -> None:
        self.repository = repository
        self.sink = sink

    async def run_once(self, *, batch_size: int = 100) -> OutboxRunResult:
        published = 0
        failed = 0
        for message in self.repository.list_pending_outbox(batch_size):
            try:
                await self.sink.publish(
                    event_key=message.event_key,
                    topic=message.topic,
                    payload=message.payload,
                )
            except Exception as exc:
                self.repository.record_outbox_error(message.event_key, str(exc))
                failed += 1
                break
            self.repository.mark_outbox_published(message.event_key)
            published += 1
        return OutboxRunResult(published=published, failed=failed)
