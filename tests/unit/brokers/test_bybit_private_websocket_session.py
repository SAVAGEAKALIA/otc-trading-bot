import asyncio
from datetime import UTC, datetime
import hashlib
import hmac
import json

import pytest

from trading_platform.brokers.bybit.private_stream import PrivateStreamLifecycle
from trading_platform.brokers.bybit.private_websocket import (
    BybitPrivateWebSocketSession,
    build_private_stream_auth,
)
from trading_platform.execution.clock import ManualClock
from trading_platform.execution.order_manager import BrokerOrderSnapshot
from trading_platform.domain.orders import OrderStatus


NOW = datetime.fromtimestamp(1_800_000_000, tz=UTC)


def order_event(sequence=1):
    return {
        "topic": "order",
        "type": "snapshot",
        "creationTime": 1_800_000_000_000,
        "seq": sequence,
        "data": [
            {
                "orderLinkId": "client-1",
                "orderId": "broker-1",
                "orderStatus": "Filled",
            }
        ],
    }


class Socket:
    def __init__(self, incoming=()):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = False

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_json(self):
        if not self.incoming:
            await asyncio.sleep(0)
            raise EOFError("socket exhausted")
        return self.incoming.pop(0)

    async def close(self):
        self.closed = True


class Connector:
    def __init__(self, sockets):
        self.sockets = list(sockets)
        self.urls = []

    async def connect(self, url):
        self.urls.append(url)
        return self.sockets.pop(0)


class Reconciler:
    def __init__(self, outcomes=(True,)):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def reconcile(self):
        self.calls += 1
        return self.outcomes.pop(0) if self.outcomes else True


def ack(op, req_id=1):
    return {"req_id": req_id, "op": op, "retCode": 0, "retMsg": "OK"}


def session(connector, reconciler=None, *, clock=None):
    return BybitPrivateWebSocketSession(
        connector,
        lifecycle=PrivateStreamLifecycle(("order", "execution")),
        api_key="test-key",
        api_secret="test-secret",
        environment="testnet",
        clock=clock or ManualClock(NOW),
        reconciler=reconciler or Reconciler(),
    )


def test_private_auth_is_canonical_and_secret_is_not_exposed() -> None:
    request = build_private_stream_auth(
        api_key="key", api_secret="secret", expires_at_ms=1_800_000_005_000
    )
    expected_payload = "GET/realtime1800000005000"
    assert request["op"] == "auth"
    assert request["args"] == [
        "key",
        1_800_000_005_000,
        hmac.new(b"secret", expected_payload.encode(), hashlib.sha256).hexdigest(),
    ]
    assert "secret" not in repr(request)


@pytest.mark.asyncio
async def test_session_authenticates_subscribes_reconciles_and_dispatches() -> None:
    socket = Socket([
        ack("auth"),
        ack("subscribe"),
        order_event(),
    ])
    reconciler = Reconciler()
    service = session(Connector([socket]), reconciler)

    await service.connect()
    assert service.submission_ready() is True
    snapshot = await service.receive_once()
    assert isinstance(snapshot, BrokerOrderSnapshot)
    assert snapshot.status is OrderStatus.FILLED
    assert reconciler.calls == 1
    assert [item["op"] for item in socket.sent] == ["auth", "subscribe"]
    assert socket.sent[1]["args"] == ["order", "execution"]


@pytest.mark.asyncio
async def test_session_stays_suspended_until_reconciliation_succeeds() -> None:
    socket = Socket([ack("auth"), ack("subscribe")])
    reconciler = Reconciler((False, True))
    service = session(Connector([socket]), reconciler)

    with pytest.raises(RuntimeError, match="reconciliation"):
        await service.connect()
    assert service.submission_ready() is False

    await service.reconcile_current_generation()
    assert service.submission_ready() is True
    assert reconciler.calls == 2


@pytest.mark.asyncio
async def test_disconnect_reconnects_and_resubscribes_with_new_generation() -> None:
    first = Socket([ack("auth"), ack("subscribe")])
    second = Socket([ack("auth"), ack("subscribe")])
    connector = Connector([first, second])
    service = session(connector)

    await service.connect()
    generation = service.generation
    await service.handle_disconnect()
    assert service.submission_ready() is False
    await service.reconnect()

    assert service.generation == generation + 1
    assert service.submission_ready() is True
    assert len(connector.urls) == 2
    assert [item["op"] for item in second.sent] == ["auth", "subscribe"]


@pytest.mark.asyncio
async def test_heartbeat_is_allowlisted_and_sequence_gap_suspends() -> None:
    socket = Socket([
        ack("auth"),
        ack("subscribe"),
        {"op": "ping", "retCode": 0, "retMsg": "pong"},
        order_event(1),
        order_event(3),
    ])
    service = session(Connector([socket]))
    await service.connect()
    await service.heartbeat()
    assert socket.sent[-1] == {"op": "ping"}
    await service.receive_once()
    with pytest.raises(RuntimeError, match="sequence"):
        await service.receive_once()
    assert service.submission_ready() is False


@pytest.mark.asyncio
async def test_handshake_failure_retries_with_fresh_socket_and_reconciles_once() -> None:
    rejected = Socket([{"op": "auth", "retCode": 10004, "retMsg": "bad sign"}])
    accepted = Socket([ack("auth"), ack("subscribe")])
    reconciler = Reconciler()
    connector = Connector([rejected, accepted])
    service = session(connector, reconciler)

    await service.connect()

    assert rejected.closed is True
    assert len(connector.urls) == 2
    assert reconciler.calls == 1
    assert service.submission_ready() is True


@pytest.mark.asyncio
async def test_invalid_heartbeat_suspends_readiness() -> None:
    socket = Socket([ack("auth"), ack("subscribe"), {"op": "pong"}])
    service = session(Connector([socket]))
    await service.connect()
    with pytest.raises(ValueError, match="heartbeat"):
        await service.heartbeat()
    assert service.submission_ready() is False


def test_session_does_not_expose_order_mutation_methods() -> None:
    methods = set(dir(BybitPrivateWebSocketSession))
    assert "create_order" not in methods
    assert "cancel_order" not in methods
    assert "amend_order" not in methods
