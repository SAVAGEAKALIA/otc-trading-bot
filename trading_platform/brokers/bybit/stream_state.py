"""Fail-closed sequence tracking for Bybit WebSocket topics."""

from dataclasses import dataclass


@dataclass(slots=True)
class SequenceTracker:
    last: int | None = None
    healthy: bool = True

    def accept(self, sequence: int) -> bool:
        if sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.last is not None and sequence <= self.last:
            self.healthy = False
            return False
        if self.last is not None and sequence != self.last + 1:
            self.healthy = False
            return False
        self.last = sequence
        return True

    def reset(self) -> None:
        self.last = None
        self.healthy = True
