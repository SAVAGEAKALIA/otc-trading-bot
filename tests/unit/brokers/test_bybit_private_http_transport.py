from types import SimpleNamespace

import pytest

from trading_platform.brokers.bybit.http_transport import RawHttpResponse
from trading_platform.brokers.bybit.private_http_transport import (
    BybitPrivateHttpTransport,
    RequestsPrivateHttpBackend,
)


SIGNED_HEADERS = {
    "X-BAPI-API-KEY": "key",
    "X-BAPI-TIMESTAMP": "1800000000000",
    "X-BAPI-SIGN": "a" * 64,
    "X-BAPI-RECV-WINDOW": "5000",
    "X-BAPI-SIGN-TYPE": "2",
    "Accept": "application/json",
}


class Backend:
    def __init__(self, response=None):
        self.response = response or RawHttpResponse(
            200, {"content-type": "application/json"}, b'{"retCode":0}'
        )
        self.calls = []

    async def get(self, url, params, headers, *, timeout_seconds, maximum_bytes):
        self.calls.append((url, dict(params), dict(headers), timeout_seconds, maximum_bytes))
        return self.response


@pytest.mark.asyncio
async def test_forwards_only_allowlisted_signed_private_read() -> None:
    backend = Backend()
    transport = BybitPrivateHttpTransport(backend, environment="testnet")

    response = await transport.get(
        "https://api-testnet.bybit.com/v5/position/list",
        {"category": "linear", "settleCoin": "USDT"},
        SIGNED_HEADERS,
        timeout_seconds=3,
        maximum_bytes=1000,
    )

    assert response.status == 200
    assert backend.calls[0][0] == "https://api-testnet.bybit.com/v5/position/list"
    assert backend.calls[0][2]["X-BAPI-SIGN"] == "a" * 64


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "params", "headers"),
    [
        ("https://evil.example/v5/position/list", {"category": "linear"}, SIGNED_HEADERS),
        ("http://api-testnet.bybit.com/v5/position/list", {"category": "linear"}, SIGNED_HEADERS),
        ("https://api.bybit.com/v5/position/list", {"category": "linear"}, SIGNED_HEADERS),
        ("https://api-testnet.bybit.com/v5/order/create", {}, SIGNED_HEADERS),
        ("https://api-testnet.bybit.com/v5/position/list?category=linear", {"category": "linear"}, SIGNED_HEADERS),
        ("https://api-testnet.bybit.com/v5/position/list", {"category": "linear", "withdraw": "true"}, SIGNED_HEADERS),
        ("https://api-testnet.bybit.com/v5/position/list", {"category": "linear"}, {**SIGNED_HEADERS, "Cookie": "secret"}),
        ("https://api-testnet.bybit.com/v5/position/list", {"category": "linear"}, {key: value for key, value in SIGNED_HEADERS.items() if key != "X-BAPI-SIGN"}),
    ],
)
async def test_rejects_ssrf_write_tampering_and_unallowlisted_headers(
    url, params, headers
) -> None:
    backend = Backend()
    transport = BybitPrivateHttpTransport(backend, environment="testnet")
    with pytest.raises(ValueError):
        await transport.get(
            url,
            params,
            headers,
            timeout_seconds=3,
            maximum_bytes=1000,
        )
    assert backend.calls == []


@pytest.mark.asyncio
async def test_rejects_backend_response_larger_than_requested_bound() -> None:
    transport = BybitPrivateHttpTransport(
        Backend(RawHttpResponse(200, {"content-type": "application/json"}, b"x" * 11)),
        environment="testnet",
    )
    with pytest.raises(ValueError, match="maximum"):
        await transport.get(
            "https://api-testnet.bybit.com/v5/position/list",
            {"category": "linear"},
            SIGNED_HEADERS,
            timeout_seconds=3,
            maximum_bytes=10,
        )


@pytest.mark.asyncio
async def test_requests_backend_denies_redirects_streams_and_translates_timeout(monkeypatch) -> None:
    class LibraryTimeout(Exception):
        pass

    class LibraryConnectionError(Exception):
        pass

    class Response:
        status_code = 200
        headers = {"content-type": "application/json", "content-length": "2"}

        def iter_content(self, chunk_size):
            yield b"{}"

        def close(self):
            self.closed = True

    calls = []

    def get(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    backend = object.__new__(RequestsPrivateHttpBackend)
    backend._requests = SimpleNamespace(
        get=get,
        exceptions=SimpleNamespace(
            Timeout=LibraryTimeout,
            ConnectionError=LibraryConnectionError,
        ),
    )
    result = backend._get_sync(
        "https://api-testnet.bybit.com/v5/position/list",
        {"category": "linear"},
        SIGNED_HEADERS,
        1,
        10,
    )
    assert result.content == b"{}"
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["stream"] is True

    def timeout(*args, **kwargs):
        raise LibraryTimeout()

    backend._requests.get = timeout

    async def inline_to_thread(function, *args):
        return function(*args)

    monkeypatch.setattr(
        "trading_platform.brokers.bybit.private_http_transport.asyncio.to_thread",
        inline_to_thread,
    )
    with pytest.raises(TimeoutError):
        await backend.get(
            "https://api-testnet.bybit.com/v5/position/list",
            {"category": "linear"},
            SIGNED_HEADERS,
            timeout_seconds=1,
            maximum_bytes=10,
        )
