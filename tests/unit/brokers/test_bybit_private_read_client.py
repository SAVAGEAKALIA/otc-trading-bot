import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_platform.brokers.bybit.http_transport import RawHttpResponse
from trading_platform.brokers.bybit.private_client import BybitPrivateReadClient
from trading_platform.brokers.bybit.private_read import BybitPrivateReadSigner
from trading_platform.brokers.bybit.time_sync import BybitClockSample
from trading_platform.execution.clock import ManualClock


class Samples:
    def __init__(self, clock):
        self.clock = clock
        self.calls = 0

    async def sample(self):
        self.calls += 1
        now = self.clock.now()
        result = BybitClockSample(
            request_started_at=now - timedelta(milliseconds=10),
            response_received_at=now,
            server_time=now,
            round_trip_ms=Decimal("10"),
            offset_ms=Decimal("0"),
            healthy=True,
            reasons=(),
        )
        self.clock.advance(timedelta(milliseconds=1))
        return result


class Backend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, params, headers, *, timeout_seconds, maximum_bytes):
        self.calls.append((url, dict(params), dict(headers)))
        return self.responses.pop(0)


def response(status=200, payload=None):
    return RawHttpResponse(
        status,
        {"content-type": "application/json"},
        json.dumps(payload or {"retCode": 0, "retMsg": "OK", "result": {}}).encode(),
    )


def client(responses):
    clock = ManualClock(datetime.fromtimestamp(1_800_000_000, tz=UTC))
    backend = Backend(responses)
    samples = Samples(clock)
    signer = BybitPrivateReadSigner(
        api_key="key", api_secret="secret", environment="testnet", clock=clock
    )
    return BybitPrivateReadClient(signer, samples, backend), backend, samples


@pytest.mark.asyncio
async def test_executes_only_explicit_wallet_position_and_open_order_reads() -> None:
    service, backend, _ = client([response(), response(), response()])

    await service.get_wallet_balance(account_type="UNIFIED", coins=("USDT", "BTC"))
    await service.get_positions(category="linear", settle_coin="USDT")
    await service.get_open_orders(category="linear", symbol="BTCUSDT")

    assert [call[0].split(".com")[-1] for call in backend.calls] == [
        "/v5/account/wallet-balance",
        "/v5/position/list",
        "/v5/order/realtime",
    ]
    assert backend.calls[0][1] == {"accountType": "UNIFIED", "coin": "USDT,BTC"}
    assert all("X-BAPI-SIGN" in call[2] for call in backend.calls)


@pytest.mark.asyncio
async def test_transient_retry_gets_fresh_clock_sample_and_signature() -> None:
    service, backend, samples = client([response(503), response()])

    await service.get_positions(category="linear", symbol="BTCUSDT")

    assert samples.calls == 2
    assert len(backend.calls) == 2
    assert (
        backend.calls[0][2]["X-BAPI-TIMESTAMP"]
        != backend.calls[1][2]["X-BAPI-TIMESTAMP"]
    )


@pytest.mark.asyncio
async def test_rate_limit_retries_but_other_api_error_fails_closed() -> None:
    limited = response(payload={"retCode": 10006, "retMsg": "rate limit"})
    service, _, samples = client([limited, response()])
    await service.get_wallet_balance(account_type="UNIFIED")
    assert samples.calls == 2

    failed = response(payload={"retCode": 10001, "retMsg": "parameter error"})
    service, _, _ = client([failed])
    with pytest.raises(ValueError, match="10001"):
        await service.get_positions(category="linear")


def test_private_client_has_no_order_mutation_methods() -> None:
    methods = set(dir(BybitPrivateReadClient))
    assert "create_order" not in methods
    assert "cancel_order" not in methods
    assert "amend_order" not in methods
