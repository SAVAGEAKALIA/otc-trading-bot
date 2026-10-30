"""Explicit clocks for repeatable simulations and production time access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from trading_platform.domain.time import require_utc


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(slots=True)
class ManualClock:
    _current: datetime

    def __post_init__(self) -> None:
        require_utc(self._current, "current")

    def now(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ValueError("manual clock cannot move backwards")
        self._current += delta
        return self._current

    def set(self, value: datetime) -> datetime:
        require_utc(value, "value")
        if value < self._current:
            raise ValueError("manual clock cannot move backwards")
        self._current = value
        return self._current
