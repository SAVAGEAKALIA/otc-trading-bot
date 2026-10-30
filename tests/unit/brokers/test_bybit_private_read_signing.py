import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_platform.brokers.bybit.private_read import BybitPrivateReadSigner
from trading_platform.brokers.bybit.time_sync import BybitClockSample
from trading_platform.execution.clock import ManualClock


NOW = datetime.fromtimestamp(1_800_000_000, tz=UTC)


def clock_sample(*, healthy=True, age_seconds=0, offset_ms="50"):
    received = NOW - timedelta(seconds=age_seconds)
    return BybitClockSample(
        request_started_at=received - timedelta(milliseconds=100),
        response_received_at=received,
        server_time=received
        + timedelta(microseconds=int(Decimal(offset_ms) * Decimal("1000"))),
        round_trip_ms=Decimal("100"),
        offset_ms=Decimal(offset_ms),
        healthy=healthy,
        reasons=() if healthy else ("clock_offset_limit_exceeded",),
    )


def test_builds_canonical_v5_read_signature() -> None:
    signer = BybitPrivateReadSigner(
        api_key="test-key",
        api_secret="test-secret",
        environment="testnet",
        clock=ManualClock(NOW),
    )

    request = signer.sign_get(
        "/v5/account/wallet-balance",
        {"coin": "USDT", "accountType": "UNIFIED"},
        clock_sample=clock_sample(),
    )

    assert request.url == "https://api-testnet.bybit.com/v5/account/wallet-balance"
    assert request.query_string == "accountType=UNIFIED&coin=USDT"
    assert request.headers["X-BAPI-TIMESTAMP"] == "1800000000050"
    assert request.headers["X-BAPI-SIGN"] == (
        "aa6c871a1019a80666c6d0db63f7b31e33e438bceafe12ace4c4fb7d690b4846"
    )
    assert request.headers["X-BAPI-API-KEY"] == "test-key"
    assert "test-secret" not in repr(request)


def test_signature_matches_independent_hmac_calculation() -> None:
    signer = BybitPrivateReadSigner(
        api_key="key", api_secret="secret", environment="mainnet", clock=ManualClock(NOW)
    )
    request = signer.sign_get(
        "/v5/position/list",
        {"symbol": "BTCUSDT", "category": "linear"},
        clock_sample=clock_sample(offset_ms="0"),
    )
    payload = "1800000000000key5000category=linear&symbol=BTCUSDT"

    assert request.headers["X-BAPI-SIGN"] == hmac.new(
        b"secret", payload.encode(), hashlib.sha256
    ).hexdigest()


def test_rejects_unhealthy_stale_or_future_clock_sample() -> None:
    signer = BybitPrivateReadSigner(
        api_key="key", api_secret="secret", environment="testnet", clock=ManualClock(NOW)
    )
    with pytest.raises(RuntimeError, match="unhealthy"):
        signer.sign_get(
            "/v5/position/list",
            {"category": "linear"},
            clock_sample=clock_sample(healthy=False),
        )
    with pytest.raises(RuntimeError, match="stale"):
        signer.sign_get(
            "/v5/position/list",
            {"category": "linear"},
            clock_sample=clock_sample(age_seconds=31),
        )

    future = clock_sample()
    future = BybitClockSample(
        request_started_at=NOW + timedelta(seconds=1),
        response_received_at=NOW + timedelta(seconds=2),
        server_time=NOW + timedelta(seconds=2),
        round_trip_ms=Decimal("1000"),
        offset_ms=Decimal("0"),
        healthy=True,
        reasons=(),
    )
    with pytest.raises(RuntimeError, match="future"):
        signer.sign_get(
            "/v5/position/list", {"category": "linear"}, clock_sample=future
        )


def test_rejects_write_endpoint_and_unallowlisted_parameters() -> None:
    signer = BybitPrivateReadSigner(
        api_key="key", api_secret="secret", environment="testnet", clock=ManualClock(NOW)
    )
    with pytest.raises(ValueError, match="read path"):
        signer.sign_get(
            "/v5/order/create", {}, clock_sample=clock_sample()
        )
    with pytest.raises(ValueError, match="parameters"):
        signer.sign_get(
            "/v5/account/wallet-balance",
            {"accountType": "UNIFIED", "withdraw": "true"},
            clock_sample=clock_sample(),
        )


def test_signer_exposes_only_read_request_construction() -> None:
    methods = set(dir(BybitPrivateReadSigner))
    assert "create_order" not in methods
    assert "post" not in methods
    assert "delete" not in methods
