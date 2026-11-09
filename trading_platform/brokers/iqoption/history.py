"""Bounded, read-only IQ Option closed-option history transport."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .settlement import IQOptionClosedOptionsPort


class IQOptionHistoryAPI(Protocol):
    def get_position_history_v2(
        self,
        instrument_type: str,
        limit: int,
        offset: int,
        start: int,
        end: int,
    ) -> Any: ...


class IQOptionClosedOptionsHistory(IQOptionClosedOptionsPort):
    """Adapt the blocking vendor history call to the async settlement port.

    The vendored client waits indefinitely for websocket state. Calls are
    therefore isolated in a daemon thread and bounded by ``request_timeout``.
    A timeout or malformed/unsuccessful response remains pending rather than
    being converted into a guessed settlement.
    """

    def __init__(
        self,
        api: IQOptionHistoryAPI,
        *,
        request_timeout: float = 5.0,
        page_size: int = 100,
        max_pages: int = 5,
        instrument_types: Sequence[str] = ("turbo-option", "binary-option"),
    ) -> None:
        if request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        normalized_types = tuple(
            str(value).strip() for value in instrument_types if str(value).strip()
        )
        if not normalized_types:
            raise ValueError("at least one instrument type is required")
        self.api = api
        self.request_timeout = float(request_timeout)
        self.page_size = int(page_size)
        self.max_pages = int(max_pages)
        self.instrument_types = normalized_types

    async def find_closed_option(
        self, broker_order_id: str
    ) -> Mapping[str, Any] | None:
        expected_id = str(broker_order_id).strip()
        if not expected_id:
            raise ValueError("broker_order_id is required")

        pages_read = 0
        for instrument_type in self.instrument_types:
            offset = 0
            previous_page_fingerprint: str | None = None
            previous_ids: set[str] = set()

            while pages_read < self.max_pages:
                page = await self._request_page(
                    instrument_type, self.page_size, offset
                )
                pages_read += 1
                if page is None:
                    return None
                records = _extract_records(page)
                if records is None:
                    return None

                page_fingerprint = _fingerprint(records)
                if page_fingerprint == previous_page_fingerprint:
                    return None
                previous_page_fingerprint = page_fingerprint

                page_ids = {
                    record_id
                    for record in records
                    if (record_id := _record_id(record)) is not None
                }
                match = next(
                    (
                        record
                        for record in records
                        if _record_id(record) == expected_id
                    ),
                    None,
                )
                if match is not None:
                    return dict(match)

                if not records or len(records) < self.page_size:
                    break
                if page_ids and page_ids.issubset(previous_ids):
                    return None
                previous_ids.update(page_ids)
                offset += len(records)

        return None

    async def _request_page(
        self, instrument_type: str, limit: int, offset: int
    ) -> Any | None:
        result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def request() -> None:
            try:
                result = self.api.get_position_history_v2(
                    instrument_type, limit, offset, 0, 0
                )
            except BaseException as exc:
                result_queue.put((False, exc))
            else:
                result_queue.put((True, result))

        threading.Thread(
            target=request,
            name="iqoption-history-read",
            daemon=True,
        ).start()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.request_timeout
        while loop.time() < deadline:
            try:
                succeeded, value = result_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(min(0.01, max(0.0, deadline - loop.time())))
                continue
            if succeeded:
                return value
            if isinstance(value, (ConnectionError, OSError, RuntimeError)):
                return None
            raise value
        return None


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _unwrap_response(response: Any) -> Any | None:
    if isinstance(response, tuple) and len(response) == 2:
        success, payload = response
        return payload if success is True else None
    if not isinstance(response, Mapping):
        return response if _is_sequence(response) else None

    if "status" not in response:
        return response
    status = response.get("status")
    successful = status in {True, 2000, "2000", "ok", "success"}
    return response.get("msg") if successful else None


def _extract_records(response: Any) -> list[Mapping[str, Any]] | None:
    payload = _unwrap_response(response)
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        for key in ("positions", "closed_options", "history", "items", "data"):
            if key in payload:
                payload = payload[key]
                break
        else:
            return None
    if not _is_sequence(payload):
        return None
    records = list(payload)
    if not all(isinstance(record, Mapping) for record in records):
        return None
    return [record for record in records if isinstance(record, Mapping)]


def _record_id(record: Mapping[str, Any]) -> str | None:
    for key in ("id", "order_id", "position_id", "external_id"):
        if key not in record:
            continue
        value = record[key]
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _fingerprint(records: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps(list(records), sort_keys=True, default=str, separators=(",", ":"))


__all__ = ["IQOptionHistoryAPI", "IQOptionClosedOptionsHistory"]
