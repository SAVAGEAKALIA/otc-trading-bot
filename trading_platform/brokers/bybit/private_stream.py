"""Capability-limited private stream lifecycle state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .stream_state import SequenceTracker


ALLOWED_TOPICS = frozenset({"order", "execution", "wallet", "position"})


@dataclass(slots=True)
class PrivateStreamLifecycle:
    topics: tuple[str, ...]
    connected: bool = False
    subscribed: bool = False
    generation: int = 0
    _sequences: dict[str, SequenceTracker] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        normalized = tuple(dict.fromkeys(topic.strip() for topic in self.topics))
        if not normalized or any(topic not in ALLOWED_TOPICS for topic in normalized):
            raise ValueError("private stream topics are not allowlisted")
        self.topics = normalized
        self._sequences = {topic: SequenceTracker() for topic in normalized}

    def connected_event(self) -> tuple[str, ...]:
        self.connected = True
        self.subscribed = False
        self.generation += 1
        for tracker in self._sequences.values():
            tracker.reset()
        return self.subscription_topics()

    def subscription_topics(self) -> tuple[str, ...]:
        return tuple(self.topics)

    def subscribed_event(self) -> None:
        if not self.connected:
            raise RuntimeError("cannot subscribe before stream connection")
        self.subscribed = True

    def disconnected_event(self) -> None:
        self.connected = False
        self.subscribed = False

    def accept_event(self, topic: str, sequence: int) -> bool:
        if not self.connected or not self.subscribed:
            raise RuntimeError("private event received before subscription")
        tracker = self._sequences.get(topic)
        if tracker is None:
            raise ValueError("private event topic is not subscribed")
        return tracker.accept(sequence)

    def healthy(self) -> bool:
        return self.connected and self.subscribed and all(
            tracker.healthy for tracker in self._sequences.values()
        )
