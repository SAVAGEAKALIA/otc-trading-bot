from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_platform.brokers.bybit.time_sync import BybitClockSynchronizer
from trading_platform.execution.clock import ManualClock


class TimeTransport:
    def __init__(self, clock, payload, latency):
        self.clock = clock
        self.payload = payload
        self.latency = latency
        self.calls = []

    async def get_json(self, path, params):
        self.calls.append((path, dict(params)))
        self.clock.advance(self.latency)
        return self.payload


def payload(time_nano: str = "1800000000150000000") -> dict:
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"timeSecond": "1800000000", "timeNano": time_nano},
        "time": 1_800_000_000_150,
    }


@pytest.mark.asyncio
async def test_measures_midpoint_offset_and_round_trip() -> None:
    clock = ManualClock(datetime.fromtimestamp(1_800_000_000, tz=UTC))
    transport = TimeTransport(clock, payload(), timedelta(milliseconds=200))
    synchronizer = BybitClockSynchronizer(
        transport,
        clock,
        maximum_round_trip_ms=Decimal("500"),
        maximum_absolute_offset_ms=Decimal("100"),
    )

    sample = await synchronizer.sample()

    assert sample.round_trip_ms == Decimal("200")
    assert sample.offset_ms == Decimal("50")
    assert sample.healthy is True
    assert sample.reasons == ()
    assert transport.calls == [("/v5/market/time", {})]


@pytest.mark.asyncio
async def test_marks_excess_latency_and_clock_drift_unhealthy() -> None:
    clock = ManualClock(datetime.fromtimestamp(1_800_000_000, tz=UTC))
    transport = TimeTransport(
        clock,
        payload("1800000005000000000"),
        timedelta(seconds=3),
    )
    transport.payload["time"] = 1_800_000_005_000
    transport.payload["result"]["timeSecond"] = "1800000005"
    sample = await BybitClockSynchronizer(
        transport,
        clock,
        maximum_round_trip_ms=Decimal("1000"),
        maximum_absolute_offset_ms=Decimal("500"),
    ).sample()

    assert sample.healthy is False
    assert set(sample.reasons) == {"round_trip_limit_exceeded", "clock_offset_limit_exceeded"}


@pytest.mark.asyncio
async def test_rejects_api_error_and_inconsistent_exchange_times() -> None:
    clock = ManualClock(datetime.fromtimestamp(1_800_000_000, tz=UTC))
    failed = payload()
    failed["retCode"] = 10001
    with pytest.raises(ValueError, match="10001"):
        await BybitClockSynchronizer(
            TimeTransport(clock, failed, timedelta()), clock
        ).sample()

    inconsistent = payload()
    inconsistent["time"] += 10_000
    with pytest.raises(ValueError, match="inconsistent"):
        await BybitClockSynchronizer(
            TimeTransport(clock, inconsistent, timedelta()), clock
        ).sample()

    inconsistent = payload()
    inconsistent["result"]["timeSecond"] = "1800000001"
    with pytest.raises(ValueError, match="timeSecond and timeNano"):
        await BybitClockSynchronizer(
            TimeTransport(clock, inconsistent, timedelta()), clock
        ).sample()
