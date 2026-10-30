import json
from decimal import Decimal
from uuid import UUID

import pytest

from trading_platform.brokers.bybit.execution import (
    BybitExecutionConfig,
    BybitExecutionControls,
    BybitPositionMode,
    BybitTestnetExecutionGateway,
)
from trading_platform.brokers.bybit.http_transport import RawHttpResponse
from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Money, Quantity
from trading_platform.domain.orders import OrderIntent, OrderSide, OrderStatus, OrderType, TimeInForce
from trading_platform.domain.risk import RiskDecision


class Backend:
    def __init__(self, payload, *, failures=()): self.payload = payload; self.calls = []; self.failures = list(failures)
    async def post(self, path, payload, **kwargs):
        self.calls.append((path, dict(payload)))
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        return RawHttpResponse(200, {"content-type": "application/json"}, json.dumps(self.payload).encode())


class Reader:
    def __init__(self, pages): self.pages = list(pages); self.calls = []
    async def get_open_orders(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.pop(0)


class ControlsReader:
    def __init__(
        self,
        *,
        mode=BybitPositionMode.ONE_WAY,
        buy_leverage=Decimal("1"),
        sell_leverage=Decimal("1"),
    ):
        self.mode = mode
        self.buy_leverage = buy_leverage
        self.sell_leverage = sell_leverage
        self.calls = []

    async def get_execution_controls(self, **kwargs):
        self.calls.append(kwargs)
        return BybitExecutionControls(
            category=kwargs["category"],
            symbol=kwargs["symbol"],
            position_mode=self.mode,
            buy_leverage=self.buy_leverage,
            sell_leverage=self.sell_leverage,
        )


def controlled_gateway(backend, *, mode=BybitPositionMode.ONE_WAY, config=None, **kwargs):
    controls = ControlsReader(mode=mode)
    gateway = BybitTestnetExecutionGateway(
        backend,
        execution_controls=controls,
        config=config or BybitExecutionConfig(expected_position_mode=mode),
        **kwargs,
    )
    return gateway, controls


class SnapshotReader:
    def __init__(self, snapshot, *, price="", qty=""): self.snapshot = snapshot; self.calls = []; self.price = price; self.qty = qty
    async def get_open_orders(self, **kwargs):
        self.calls.append(kwargs)
        if self.snapshot is None:
            return {"result": {"list": [], "nextPageCursor": ""}}
        return {
            "result": {
                "list": [{
                    "orderLinkId": self.snapshot.client_order_id,
                    "orderId": self.snapshot.broker_order_id,
                    "orderStatus": {
                        OrderStatus.FILLED: "Filled",
                        OrderStatus.CANCELED: "Cancelled",
                    }.get(self.snapshot.status, "New"),
                    "price": self.price,
                    "qty": self.qty,
                    "execId": "exec-1" if self.snapshot.executions else "",
                    "execQty": str(self.snapshot.executions[0].quantity) if self.snapshot.executions else "",
                    "execPrice": str(self.snapshot.executions[0].price) if self.snapshot.executions else "",
                    "execFee": str(self.snapshot.executions[0].fee) if self.snapshot.executions else "0",
                }],
                "nextPageCursor": "",
            }
        }


def intent(*, side=OrderSide.BUY, reduce_only=False):
    signal = UUID("00000000-0000-0000-0000-000000000001")
    return OrderIntent(
        client_order_id="client-1", signal_id=signal,
        risk_decision=RiskDecision.approved(signal_id=signal, environment=TradingEnvironment.TESTNET, limits_snapshot={"max": "1"}),
        instrument=InstrumentId("BYBIT", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT"),
        environment=TradingEnvironment.TESTNET, side=side, order_type=OrderType.LIMIT,
        quantity=Quantity(Decimal("0.01")), time_in_force=TimeInForce.GTC,
        limit_price=Money(Decimal("100"), "USDT"),
        reduce_only=reduce_only,
    )


@pytest.mark.asyncio
async def test_matching_linear_controls_permit_submission():
    backend = Backend({"retCode": 0, "result": {"orderId": "oid", "orderLinkId": "client-1"}})
    controls = ControlsReader()

    result = await BybitTestnetExecutionGateway(
        backend, execution_controls=controls
    ).submit_order(intent())

    assert result.broker_order_id == "oid"
    assert controls.calls == [{"category": "linear", "symbol": "BTCUSDT"}]
    assert backend.calls[0][1]["positionIdx"] == "0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("controls", "message"),
    [
        (ControlsReader(buy_leverage=Decimal("2")), "leverage mismatch"),
        (ControlsReader(mode=BybitPositionMode.HEDGE), "position mode mismatch"),
    ],
)
async def test_control_mismatch_rejects_before_backend_access(controls, message):
    backend = Backend({"retCode": 0, "result": {"orderId": "must-not-run"}})
    gateway = BybitTestnetExecutionGateway(backend, execution_controls=controls)

    with pytest.raises(ValueError, match=message):
        await gateway.submit_order(intent())

    assert backend.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("side", "expected_position_idx"),
    [(OrderSide.BUY, "1"), (OrderSide.SELL, "2")],
)
async def test_hedge_entries_map_side_to_position_idx(side, expected_position_idx):
    backend = Backend({"retCode": 0, "result": {"orderId": "oid", "orderLinkId": "client-1"}})
    gateway, _ = controlled_gateway(backend, mode=BybitPositionMode.HEDGE)

    await gateway.submit_order(intent(side=side))

    assert backend.calls[0][1]["positionIdx"] == expected_position_idx


@pytest.mark.asyncio
async def test_hedge_reduce_only_entry_preserves_entry_side_index():
    backend = Backend({"retCode": 0, "result": {"orderId": "oid", "orderLinkId": "client-1"}})
    gateway, _ = controlled_gateway(backend, mode=BybitPositionMode.HEDGE)

    await gateway.submit_order(intent(side=OrderSide.SELL, reduce_only=True))

    assert backend.calls[0][1]["positionIdx"] == "2"


@pytest.mark.asyncio
async def test_create_order_maps_intent_and_returns_ack():
    backend = Backend({"retCode": 0, "result": {"orderId": "oid", "orderLinkId": "client-1"}})
    gateway, _ = controlled_gateway(backend)
    result = await gateway.submit_order(intent())
    assert result.broker_order_id == "oid"
    assert backend.calls[0][0] == "/v5/order/create"
    assert backend.calls[0][1]["timeInForce"] == "GTC"


@pytest.mark.asyncio
async def test_cancel_and_amend_are_allowlisted_operations():
    backend = Backend({"retCode": 0, "result": {"orderId": "oid"}})
    gateway, _ = controlled_gateway(backend)
    assert await gateway.cancel_order(category="linear", symbol="BTCUSDT", client_order_id="client-1") == "oid"
    assert await gateway.amend_order(category="linear", symbol="BTCUSDT", client_order_id="client-1", price=Decimal("101")) == "oid"
    assert [path for path, _ in backend.calls] == ["/v5/order/cancel", "/v5/order/amend"]


def test_gateway_rejects_non_testnet_and_unsupported_orders():
    backend = Backend({"retCode": 0, "result": {"orderId": "oid"}})
    with pytest.raises(ValueError): BybitTestnetExecutionGateway(backend, environment=TradingEnvironment.LIVE)
    with pytest.raises(ValueError): BybitTestnetExecutionGateway(backend)._validate_identity("inverse", "BTCUSDT", "x")


@pytest.mark.asyncio
async def test_get_order_paginates_and_normalizes_matching_record():
    reader = Reader([
        {"result": {"list": [], "nextPageCursor": "next"}},
        {"result": {"list": [{"orderLinkId": "client-1", "orderId": "oid", "orderStatus": "PartiallyFilled"}], "nextPageCursor": ""}},
    ])
    gateway = BybitTestnetExecutionGateway(Backend({}), private_reader=reader)
    result = await gateway.get_order("client-1")
    assert result.status is OrderStatus.PARTIALLY_FILLED
    assert reader.calls[1]["cursor"] == "next"


@pytest.mark.asyncio
async def test_get_order_returns_none_and_rejects_repeated_cursor():
    gateway = BybitTestnetExecutionGateway(Backend({}), private_reader=Reader([
        {"result": {"list": [], "nextPageCursor": ""}},
    ]))
    assert await gateway.get_order("missing") is None
    repeating = BybitTestnetExecutionGateway(Backend({}), private_reader=Reader([
        {"result": {"list": [], "nextPageCursor": "same"}},
        {"result": {"list": [], "nextPageCursor": "same"}},
    ]))
    with pytest.raises(ValueError, match="cursor repeated"):
        await repeating.get_order("missing")


@pytest.mark.asyncio
async def test_timeout_after_accept_recovers_by_client_id_without_duplicate_create():
    from trading_platform.execution.order_manager import BrokerExecution, BrokerOrderSnapshot

    accepted = BrokerOrderSnapshot(
        "client-1", "oid-accepted", OrderStatus.FILLED,
        (BrokerExecution("exec-1", Decimal("0.01"), Decimal("100")),),
    )
    backend = Backend({}, failures=(TimeoutError("after accept"),))
    reader = SnapshotReader(accepted)
    gateway = BybitTestnetExecutionGateway(
        backend,
        private_reader=reader,
        config=BybitExecutionConfig(maximum_attempts=1),
        execution_controls=ControlsReader(),
    )

    result = await gateway.submit_order(intent())

    assert result.status is OrderStatus.FILLED
    assert result.broker_order_id == "oid-accepted"
    assert len(backend.calls) == 1
    assert reader.calls[0]["cursor"] is None


@pytest.mark.asyncio
async def test_timeout_without_broker_confirmation_retries_create():
    backend = Backend(
        {"retCode": 0, "result": {"orderId": "oid-retry", "orderLinkId": "client-1"}},
        failures=(TimeoutError("connection lost"), None),
    )
    reader = SnapshotReader(None)
    gateway = BybitTestnetExecutionGateway(backend, private_reader=reader, execution_controls=ControlsReader())

    result = await gateway.submit_order(intent())

    assert result.broker_order_id == "oid-retry"
    assert len(backend.calls) == 2
    assert reader.calls


@pytest.mark.asyncio
async def test_cancel_and_amend_timeout_recover_by_client_id_before_retry():
    from trading_platform.execution.order_manager import BrokerOrderSnapshot

    confirmed = BrokerOrderSnapshot("client-1", "oid-confirmed", OrderStatus.CANCELED)
    backend = Backend({}, failures=(TimeoutError("cancel ambiguous"),))
    gateway = BybitTestnetExecutionGateway(
        backend,
        private_reader=SnapshotReader(confirmed),
        config=BybitExecutionConfig(maximum_attempts=1),
        execution_controls=ControlsReader(),
    )
    assert await gateway.cancel_order(
        category="linear", symbol="BTCUSDT", client_order_id="client-1"
    ) == "oid-confirmed"
    assert len(backend.calls) == 1

    amended = BrokerOrderSnapshot("client-1", "oid-amended", OrderStatus.ACKNOWLEDGED)
    backend = Backend({}, failures=(TimeoutError("amend ambiguous"),))
    gateway = BybitTestnetExecutionGateway(
        backend,
        private_reader=SnapshotReader(amended, price="101"),
        config=BybitExecutionConfig(maximum_attempts=1),
        execution_controls=ControlsReader(),
    )
    assert await gateway.amend_order(
        category="linear", symbol="BTCUSDT", client_order_id="client-1", price=Decimal("101")
    ) == "oid-amended"
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_protective_exit_is_reduce_only_and_directional():
    backend = Backend({
        "retCode": 0,
        "result": {"orderId": "protect-1", "orderLinkId": "protect-client-1"},
    })
    gateway, _ = controlled_gateway(backend, mode=BybitPositionMode.HEDGE)

    result = await gateway.submit_protective_exit(
        category="linear",
        symbol="BTCUSDT",
        side="Sell",
        quantity=Decimal("0.01"),
        trigger_price=Decimal("59000"),
        client_order_id="protect-client-1",
        position_idx=1,
    )

    assert result.broker_order_id == "protect-1"
    payload = backend.calls[0][1]
    assert payload["reduceOnly"] == "true"
    assert payload["closeOnTrigger"] == "true"
    assert payload["triggerDirection"] == "2"
    assert payload["positionIdx"] == "1"


@pytest.mark.asyncio
async def test_protective_exit_rejects_non_linear_invalid_values_and_identity():
    backend = Backend({"retCode": 0, "result": {"orderId": "oid"}})
    gateway, _ = controlled_gateway(backend, mode=BybitPositionMode.HEDGE)
    cases = [
        {"category": "spot"},
        {"symbol": ""},
        {"side": "Hold"},
        {"quantity": Decimal("0")},
        {"trigger_price": Decimal("0")},
        {"client_order_id": ""},
        {"position_idx": 3},
        {"side": "Buy", "position_idx": 1},
        {"side": "Sell", "position_idx": 2},
    ]
    for override in cases:
        values = {
            "category": "linear",
            "symbol": "BTCUSDT",
            "side": "Sell",
            "quantity": Decimal("0.01"),
            "trigger_price": Decimal("59000"),
            "client_order_id": "protect-client-1",
            "position_idx": 1,
        }
        values.update(override)
        with pytest.raises(ValueError):
            await gateway.submit_protective_exit(**values)


@pytest.mark.asyncio
async def test_protective_exit_requires_matching_verified_mode_before_backend_access():
    backend = Backend({"retCode": 0, "result": {"orderId": "must-not-run"}})
    gateway, _ = controlled_gateway(backend, mode=BybitPositionMode.ONE_WAY)

    with pytest.raises(ValueError, match="position_idx does not match"):
        await gateway.submit_protective_exit(
            category="linear",
            symbol="BTCUSDT",
            side="Sell",
            quantity=Decimal("0.01"),
            trigger_price=Decimal("59000"),
            client_order_id="protect-client-1",
            position_idx=1,
        )

    assert backend.calls == []
