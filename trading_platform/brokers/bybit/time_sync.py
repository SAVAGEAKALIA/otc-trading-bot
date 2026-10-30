"""Measure Bybit server-clock offset before private signing is introduced."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from trading_platform.domain.time import require_utc
from trading_platform.execution.clock import Clock

from .public_client import PublicJsonTransport


def _milliseconds(delta: timedelta) -> Decimal:
    microseconds = (
        (delta.days * 86_400 + delta.seconds) * 1_000_000
        + delta.microseconds
    )
    return Decimal(microseconds) / Decimal("1000")


@dataclass(frozen=True, slots=True)
class BybitClockSample:
    request_started_at: datetime
    response_received_at: datetime
    server_time: datetime
    round_trip_ms: Decimal
    offset_ms: Decimal
    healthy: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "request_started_at",
            "response_received_at",
            "server_time",
        ):
            require_utc(getattr(self, name), name)
        if self.response_received_at < self.request_started_at:
            raise ValueError("clock response cannot precede request")
        if self.round_trip_ms < 0:
            raise ValueError("round_trip_ms cannot be negative")
        if self.healthy != (not self.reasons):
            raise ValueError("clock health must agree with reasons")


class BybitClockSynchronizer:
    def __init__(
        self,
        transport: PublicJsonTransport,
        clock: Clock,
        *,
        maximum_round_trip_ms: Decimal = Decimal("1000"),
        maximum_absolute_offset_ms: Decimal = Decimal("500"),
        maximum_envelope_difference_ms: Decimal = Decimal("1000"),
    ) -> None:
        if min(
            maximum_round_trip_ms,
            maximum_absolute_offset_ms,
            maximum_envelope_difference_ms,
        ) < 0:
            raise ValueError("clock synchronization limits cannot be negative")
        self._transport = transport
        self._clock = clock
        self._maximum_round_trip_ms = maximum_round_trip_ms
        self._maximum_absolute_offset_ms = maximum_absolute_offset_ms
        self._maximum_envelope_difference_ms = maximum_envelope_difference_ms

    async def sample(self) -> BybitClockSample:
        started = self._clock.now()
        payload = await self._transport.get_json("/v5/market/time", {})
        received = self._clock.now()
        if received < started:
            raise ValueError("local clock moved backwards during Bybit request")
        code = int(payload.get("retCode", -1))
        if code != 0:
            raise ValueError(f"Bybit API error {code}: {payload.get('retMsg', '')}")
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise ValueError("Bybit time result must be an object")
        server_time = self._parse_time_nano(result.get("timeNano"))
        try:
            time_second = int(str(result.get("timeSecond")))
        except (TypeError, ValueError) as exc:
            raise ValueError("Bybit timeSecond is invalid") from exc
        if time_second <= 0 or time_second != int(server_time.timestamp()):
            raise ValueError("Bybit timeSecond and timeNano are inconsistent")
        envelope_ms = int(payload.get("time", 0))
        if envelope_ms <= 0:
            raise ValueError("Bybit envelope time must be positive milliseconds")
        envelope_time = datetime.fromtimestamp(envelope_ms / 1000, tz=UTC)
        if abs(_milliseconds(server_time - envelope_time)) > self._maximum_envelope_difference_ms:
            raise ValueError("Bybit result and envelope times are inconsistent")
        round_trip = _milliseconds(received - started)
        midpoint = started + (received - started) / 2
        offset = _milliseconds(server_time - midpoint)
        reasons = []
        if round_trip > self._maximum_round_trip_ms:
            reasons.append("round_trip_limit_exceeded")
        if abs(offset) > self._maximum_absolute_offset_ms:
            reasons.append("clock_offset_limit_exceeded")
        return BybitClockSample(
            request_started_at=started,
            response_received_at=received,
            server_time=server_time,
            round_trip_ms=round_trip,
            offset_ms=offset,
            healthy=not reasons,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _parse_time_nano(value: Any) -> datetime:
        try:
            nanoseconds = int(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("Bybit timeNano is invalid") from exc
        if nanoseconds <= 0:
            raise ValueError("Bybit timeNano must be positive")
        seconds, remainder = divmod(nanoseconds, 1_000_000_000)
        return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(
            microseconds=remainder // 1000
        )
