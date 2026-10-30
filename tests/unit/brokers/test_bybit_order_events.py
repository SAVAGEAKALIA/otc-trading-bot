import pytest

from trading_platform.brokers.bybit.order_events import normalize_order_event
from trading_platform.domain.orders import OrderStatus


def test_normalizes_filled_event_and_execution():
    snapshot = normalize_order_event({"topic": "order", "data": [{
        "orderLinkId": "client-1", "orderId": "broker-1", "orderStatus": "Filled",
        "execId": "exec-1", "execQty": "0.01", "execPrice": "100", "execFee": "0.01",
    }]}, expected_client_order_id="client-1")
    assert snapshot.status is OrderStatus.FILLED
    assert snapshot.executions[0].execution_id == "exec-1"


@pytest.mark.parametrize("status", ["Cancelled", "Rejected", "Expired"])
def test_maps_terminal_statuses(status):
    snapshot = normalize_order_event({"topic": "order", "data": [{
        "orderLinkId": "client-1", "orderId": "broker-1", "orderStatus": status,
    }]})
    assert snapshot.status in {OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}


def test_rejects_mismatch_unknown_status_and_bad_payload():
    base = {"topic": "order", "data": [{"orderLinkId": "client-1", "orderId": "b", "orderStatus": "New"}]}
    with pytest.raises(ValueError): normalize_order_event(base, expected_client_order_id="other")
    with pytest.raises(ValueError): normalize_order_event({**base, "data": [{**base["data"][0], "orderStatus": "Unknown"}]})
    with pytest.raises(ValueError): normalize_order_event({"topic": "wallet", "data": []})
