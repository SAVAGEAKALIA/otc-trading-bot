import time

import pytest

from trading_platform.brokers.iqoption.history import IQOptionClosedOptionsHistory


def record(order_id: int, **overrides):
    value = {
        "id": [order_id],
        "win": "win",
        "amount": 5,
        "win_amount": 9.2,
        "close_time": 1_767_268_800,
    }
    value.update(overrides)
    return value


class FakeHistoryAPI:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get_position_history_v2(self, instrument_type, limit, offset, start, end):
        self.calls.append((instrument_type, limit, offset, start, end))
        if not self.responses:
            raise AssertionError("unexpected history request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_finds_exact_order_across_bounded_pages() -> None:
    api = FakeHistoryAPI(
        [
            (True, {"positions": [record(1001), record(1002)]}),
            (True, {"positions": [record(9001)]}),
        ]
    )
    history = IQOptionClosedOptionsHistory(
        api,
        page_size=2,
        max_pages=3,
        instrument_types=("turbo-option",),
    )

    result = await history.find_closed_option("9001")

    assert result == record(9001)
    assert api.calls == [
        ("turbo-option", 2, 0, 0, 0),
        ("turbo-option", 2, 2, 0, 0),
    ]


@pytest.mark.asyncio
async def test_short_page_stops_current_instrument_before_trying_next() -> None:
    api = FakeHistoryAPI(
        [
            (True, {"closed_options": [record(1001)]}),
            (True, {"closed_options": []}),
        ]
    )
    history = IQOptionClosedOptionsHistory(
        api,
        page_size=20,
        instrument_types=("turbo-option", "binary-option"),
    )

    assert await history.find_closed_option("9001") is None
    assert [call[0] for call in api.calls] == ["turbo-option", "binary-option"]


@pytest.mark.asyncio
async def test_repeated_page_stops_without_looping() -> None:
    repeated = (True, {"positions": [record(1001), record(1002)]})
    api = FakeHistoryAPI([repeated, repeated])
    history = IQOptionClosedOptionsHistory(
        api,
        page_size=2,
        max_pages=10,
        instrument_types=("turbo-option",),
    )

    assert await history.find_closed_option("9001") is None
    assert len(api.calls) == 2


@pytest.mark.asyncio
async def test_page_limit_bounds_full_pages() -> None:
    api = FakeHistoryAPI(
        [
            (True, {"positions": [record(1001)]}),
            (True, {"positions": [record(1002)]}),
        ]
    )
    history = IQOptionClosedOptionsHistory(
        api,
        page_size=1,
        max_pages=2,
        instrument_types=("turbo-option",),
    )

    assert await history.find_closed_option("9001") is None
    assert len(api.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        (False, None),
        {"status": 5000, "msg": {}},
        (True, {"positions": "not-a-list"}),
        (True, {"unexpected": []}),
    ],
)
async def test_unsuccessful_or_malformed_pages_fail_closed(response) -> None:
    history = IQOptionClosedOptionsHistory(
        FakeHistoryAPI([response]),
        instrument_types=("turbo-option",),
    )

    assert await history.find_closed_option("9001") is None


@pytest.mark.asyncio
async def test_timeout_and_connection_errors_remain_pending() -> None:
    class SlowAPI(FakeHistoryAPI):
        def get_position_history_v2(self, *args):
            time.sleep(0.05)
            return True, {"positions": [record(9001)]}

    timeout_history = IQOptionClosedOptionsHistory(
        SlowAPI([]),
        request_timeout=0.001,
        instrument_types=("turbo-option",),
    )
    error_history = IQOptionClosedOptionsHistory(
        FakeHistoryAPI([ConnectionError("socket closed")]),
        instrument_types=("turbo-option",),
    )

    assert await timeout_history.find_closed_option("9001") is None
    assert await error_history.find_closed_option("9001") is None


@pytest.mark.asyncio
async def test_empty_order_identity_is_rejected_before_api_access() -> None:
    api = FakeHistoryAPI([])
    history = IQOptionClosedOptionsHistory(api)

    with pytest.raises(ValueError, match="broker_order_id"):
        await history.find_closed_option(" ")

    assert api.calls == []
