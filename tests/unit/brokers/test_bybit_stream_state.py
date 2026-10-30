import pytest

from trading_platform.brokers.bybit.stream_state import SequenceTracker


def test_sequence_tracker_accepts_contiguous_events_and_resets():
    tracker = SequenceTracker()
    assert tracker.accept(10)
    assert tracker.accept(11)
    assert tracker.healthy
    tracker.reset()
    assert tracker.accept(2)


@pytest.mark.parametrize("sequence", [9, 12])
def test_sequence_tracker_fails_closed_on_duplicate_or_gap(sequence):
    tracker = SequenceTracker()
    tracker.accept(10)
    assert not tracker.accept(sequence)
    assert not tracker.healthy
