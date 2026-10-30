import pytest

from trading_platform.brokers.bybit.private_stream import PrivateStreamLifecycle


def test_private_stream_requires_resubscription_after_reconnect():
    state = PrivateStreamLifecycle(("order", "execution"))
    assert state.connected_event() == ("order", "execution")
    with pytest.raises(RuntimeError): state.accept_event("order", 1)
    state.subscribed_event()
    assert state.accept_event("order", 1)
    state.disconnected_event()
    assert not state.healthy()
    state.connected_event()
    state.subscribed_event()
    assert state.accept_event("order", 1)


def test_private_stream_rejects_unknown_topics_and_sequence_gaps():
    with pytest.raises(ValueError): PrivateStreamLifecycle(("orders",))
    state = PrivateStreamLifecycle(("wallet",))
    state.connected_event(); state.subscribed_event()
    assert state.accept_event("wallet", 10)
    assert not state.accept_event("wallet", 12)
    assert not state.healthy()
