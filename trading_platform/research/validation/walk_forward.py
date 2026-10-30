from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from trading_platform.domain.time import require_utc


@dataclass(frozen=True, slots=True)
class PurgedWindow:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


def build_purged_walk_forward(*, start_at: datetime, end_at: datetime, train_duration: timedelta, test_duration: timedelta, purge_duration: timedelta, step: timedelta = timedelta(0)) -> tuple[PurgedWindow, ...]:
    require_utc(start_at, "start_at")
    require_utc(end_at, "end_at")
    if end_at <= start_at:
        raise ValueError("end_at must follow start_at")
    if min(train_duration, test_duration, purge_duration) <= timedelta(0):
        raise ValueError("durations must be positive")
    step = step or test_duration
    if step <= timedelta(0):
        raise ValueError("step must be positive")
    windows: list[PurgedWindow] = []
    cursor = start_at
    while True:
        train_end = cursor + train_duration
        test_start = train_end + purge_duration
        test_end = test_start + test_duration
        if test_end > end_at:
            break
        windows.append(PurgedWindow(cursor, train_end, test_start, test_end))
        cursor += step
    if not windows:
        raise ValueError("not enough data for one purged window")
    return tuple(windows)
