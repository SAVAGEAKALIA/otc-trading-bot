from datetime import UTC, datetime, timedelta

import pytest

from trading_platform.execution.clock import ManualClock


def test_manual_clock_advances_deterministically() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = ManualClock(start)

    assert clock.now() == start
    assert clock.advance(timedelta(seconds=5)) == start + timedelta(seconds=5)


def test_manual_clock_rejects_naive_time_and_backwards_movement() -> None:
    with pytest.raises(ValueError):
        ManualClock(datetime(2026, 1, 1))

    clock = ManualClock(datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError):
        clock.advance(timedelta(seconds=-1))
