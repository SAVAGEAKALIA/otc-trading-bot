from datetime import UTC, datetime, timedelta

import pytest

from trading_platform.research.validation import build_purged_walk_forward


START = datetime(2026, 1, 1, tzinfo=UTC)


def test_walk_forward_windows_are_chronological_and_purged() -> None:
    windows = build_purged_walk_forward(
        start_at=START,
        end_at=START + timedelta(days=20),
        train_duration=timedelta(days=5),
        test_duration=timedelta(days=2),
        purge_duration=timedelta(days=1),
        step=timedelta(days=2),
    )

    assert len(windows) == 7
    for window in windows:
        assert window.train_end + timedelta(days=1) <= window.test_start
        assert window.train_start < window.train_end < window.test_start < window.test_end


def test_walk_forward_rejects_impossible_or_non_utc_ranges() -> None:
    with pytest.raises(ValueError, match="positive"):
        build_purged_walk_forward(
            start_at=START,
            end_at=START + timedelta(days=2),
            train_duration=timedelta(0),
            test_duration=timedelta(days=1),
            purge_duration=timedelta(days=1),
        )

    with pytest.raises(ValueError, match="not enough"):
        build_purged_walk_forward(
            start_at=START,
            end_at=START + timedelta(days=2),
            train_duration=timedelta(days=2),
            test_duration=timedelta(days=1),
            purge_duration=timedelta(days=1),
        )
