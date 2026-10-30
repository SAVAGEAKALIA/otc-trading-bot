from datetime import UTC, datetime

import pytest

from trading_platform.brokers.bybit.private_dispatch import (
    BybitPrivateStreamDispatcher,
    normalize_private_stream_envelope,
)
from trading_platform.brokers.bybit.private_stream import PrivateStreamLifecycle
from trading_platform.domain.orders import OrderStatus


def envelope(topic="order", *, sequence=1, data=None, message_type="snapshot"):
    return {
        "topic": topic,
        "type": message_type,
        "creationTime": 1_800_000_000_000,
        "seq": sequence,
        "data": data if data is not None else [
            {
                "orderLinkId": "client-1",
                "orderId": "broker-1",
                "orderStatus": "Filled",
            }
        ],
    }


def test_normalizes_private_envelope_and_dispatches_order_snapshot() -> None:
    normalized = normalize_private_stream_envelope(envelope())
    assert normalized.topic == "order"
    assert normalized.sequence == 1
    assert normalized.created_at == datetime.fromtimestamp(1_800_000_000, tz=UTC)

    lifecycle = PrivateStreamLifecycle(("order",))
    lifecycle.connected_event()
    lifecycle.subscribed_event()
    dispatcher = BybitPrivateStreamDispatcher(lifecycle)
    snapshot = dispatcher.dispatch(envelope())
    assert snapshot.status is OrderStatus.FILLED
    assert dispatcher.healthy()


@pytest.mark.parametrize(
    "payload",
    [
        {"topic": "wallet", "type": "snapshot", "creationTime": 1, "seq": 1, "data": []},
        {"topic": "order", "type": "update", "creationTime": 1, "seq": 1, "data": [{}]},
        {"topic": "order", "type": "snapshot", "creationTime": "bad", "seq": 1, "data": [{}]},
        {"topic": "order", "type": "snapshot", "creationTime": 1, "seq": 1, "data": "bad"},
    ],
)
def test_envelope_validation_fails_closed(payload) -> None:
    with pytest.raises(ValueError):
        normalize_private_stream_envelope(payload)


def test_dispatcher_rejects_sequence_gap_and_requires_resubscription() -> None:
    lifecycle = PrivateStreamLifecycle(("order",))
    lifecycle.connected_event()
    lifecycle.subscribed_event()
    dispatcher = BybitPrivateStreamDispatcher(lifecycle)
    dispatcher.dispatch(envelope(sequence=1))
    with pytest.raises(RuntimeError, match="sequence"):
        dispatcher.dispatch(envelope(sequence=3))
    assert not dispatcher.healthy()

    lifecycle.disconnected_event()
    lifecycle.connected_event()
    lifecycle.subscribed_event()
    assert dispatcher.dispatch(envelope(sequence=1)).status is OrderStatus.FILLED


def test_dispatcher_rejects_events_before_subscription_and_unknown_topics() -> None:
    lifecycle = PrivateStreamLifecycle(("order",))
    dispatcher = BybitPrivateStreamDispatcher(lifecycle)
    with pytest.raises(RuntimeError, match="lifecycle"):
        dispatcher.dispatch(envelope())

    lifecycle.connected_event()
    lifecycle.subscribed_event()
    with pytest.raises(ValueError, match="topic"):
        dispatcher.dispatch(envelope(topic="wallet"))
