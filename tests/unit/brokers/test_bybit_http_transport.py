import json
from types import SimpleNamespace

import pytest

from trading_platform.brokers.bybit.http_transport import (
    BybitPublicHttpTransport,
    RawHttpResponse,
    RequestsHttpBackend,
)


class Backend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, params, *, timeout_seconds, maximum_bytes):
        self.calls.append((url, dict(params), timeout_seconds, maximum_bytes))
        return self.responses.pop(0)


def response(status=200, payload=None, headers=None):
    content = json.dumps(payload or {"retCode": 0, "result": {}}).encode()
    return RawHttpResponse(
        status=status,
        headers={"content-type": "application/json", **(headers or {})},
        content=content,
    )


@pytest.mark.asyncio
async def test_allows_only_public_bybit_host_and_paths() -> None:
    backend = Backend([response()])
    transport = BybitPublicHttpTransport(backend, environment="testnet")

    result = await transport.get_json(
        "/v5/market/tickers", {"category": "linear"}
    )

    assert result["retCode"] == 0
    assert backend.calls[0][0] == "https://api-testnet.bybit.com/v5/market/tickers"
    with pytest.raises(ValueError, match="allowlisted"):
        await transport.get_json("/v5/order/create", {})
    with pytest.raises(ValueError, match="environment"):
        BybitPublicHttpTransport(backend, environment="live")


@pytest.mark.asyncio
async def test_retries_transient_status_then_succeeds() -> None:
    backend = Backend([response(503), response()])
    delays = []

    async def sleep(delay):
        delays.append(delay)

    transport = BybitPublicHttpTransport(
        backend, environment="mainnet", sleep=sleep, maximum_attempts=2
    )

    await transport.get_json("/v5/market/instruments-info", {"category": "spot"})

    assert len(backend.calls) == 2
    assert delays == [pytest.approx(0.25)]


@pytest.mark.asyncio
async def test_retries_bybit_rate_limit_code_with_bounded_delay() -> None:
    limited = response(
        payload={"retCode": 10006, "retMsg": "Too many visits"},
        headers={"retry-after": "99"},
    )
    backend = Backend([limited, response()])
    delays = []

    async def sleep(delay):
        delays.append(delay)

    transport = BybitPublicHttpTransport(
        backend,
        environment="mainnet",
        sleep=sleep,
        maximum_attempts=2,
        maximum_retry_delay=2.0,
    )
    await transport.get_json("/v5/market/tickers", {"category": "spot"})

    assert delays == [2.0]


@pytest.mark.asyncio
async def test_rejects_oversized_non_json_and_non_retryable_responses() -> None:
    oversized = RawHttpResponse(
        200, {"content-type": "application/json"}, b"x" * 101
    )
    with pytest.raises(ValueError, match="maximum"):
        await BybitPublicHttpTransport(
            Backend([oversized]), environment="mainnet", maximum_response_bytes=100
        ).get_json("/v5/market/tickers", {"category": "spot"})


@pytest.mark.asyncio
async def test_requests_backend_translates_library_timeout(monkeypatch) -> None:
    class LibraryTimeout(Exception):
        pass

    class LibraryConnectionError(Exception):
        pass

    def fail(*args, **kwargs):
        raise LibraryTimeout("timeout")

    backend = object.__new__(RequestsHttpBackend)
    backend._requests = SimpleNamespace(
        get=fail,
        exceptions=SimpleNamespace(
            Timeout=LibraryTimeout,
            ConnectionError=LibraryConnectionError,
        ),
    )

    with pytest.raises(TimeoutError, match="timed out"):
        await backend.get(
            "https://api.bybit.com/v5/market/tickers",
            {"category": "spot"},
            timeout_seconds=1,
            maximum_bytes=100,
        )

    not_json = RawHttpResponse(200, {"content-type": "text/html"}, b"<html>")
    with pytest.raises(ValueError, match="JSON content type"):
        await BybitPublicHttpTransport(
            Backend([not_json]), environment="mainnet"
        ).get_json("/v5/market/tickers", {"category": "spot"})

    with pytest.raises(RuntimeError, match="HTTP 400"):
        await BybitPublicHttpTransport(
            Backend([response(400)]), environment="mainnet"
        ).get_json("/v5/market/tickers", {"category": "spot"})
