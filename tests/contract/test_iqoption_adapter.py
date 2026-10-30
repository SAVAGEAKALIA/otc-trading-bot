from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_platform.legacy.iqoption_bot.asset_resolver import AssetResolver
from trading_platform.application.ports import BinaryExecutionPort
from trading_platform.brokers.iqoption.execution import (
    BinaryDirection,
    BinaryOrderCommand,
    IQOptionBinaryExecutionAdapter,
)


class FakeIQOptionAPI:
    def __init__(self, responses=None, error: Exception | None = None):
        self.responses = list(responses or [(True, 12345)])
        self.error = error
        self.calls: list[tuple[float, str, str, int]] = []

    def buy(self, amount: float, asset: str, direction: str, duration: int):
        self.calls.append((amount, asset, direction, duration))
        if self.error:
            raise self.error
        return self.responses.pop(0)


def command(asset: str = "EURUSD") -> BinaryOrderCommand:
    return BinaryOrderCommand(
        asset=asset,
        direction=BinaryDirection.CALL,
        amount=Decimal("1.25"),
        duration_minutes=2,
    )


def test_iqoption_adapter_satisfies_binary_execution_port() -> None:
    adapter = IQOptionBinaryExecutionAdapter(
        FakeIQOptionAPI(), active_codes={"EURUSD-OTC": 1}
    )
    assert isinstance(adapter, BinaryExecutionPort)


@pytest.mark.asyncio
async def test_adapter_prefers_otc_symbol_and_submits_blocking_call() -> None:
    api = FakeIQOptionAPI()
    adapter = IQOptionBinaryExecutionAdapter(api, active_codes={"EURUSD-OTC": 1})

    result = await adapter.place_binary_order(command())

    assert result.accepted is True
    assert result.order_id == 12345
    assert result.broker_symbol == "EURUSD-OTC"
    assert api.calls == [(1.25, "EURUSD-OTC", "call", 2)]


@pytest.mark.asyncio
async def test_adapter_falls_back_to_op_alias_after_rejection() -> None:
    api = FakeIQOptionAPI(
        responses=[(False, "instrument closed"), (True, 67890)]
    )
    adapter = IQOptionBinaryExecutionAdapter(
        api,
        active_codes={"EURUSD-OTC": 1, "EURUSD-op": 2},
    )

    result = await adapter.place_binary_order(command("EURUSD-OTC"))

    assert result.accepted is True
    assert result.order_id == 67890
    assert result.broker_symbol == "EURUSD-op"
    assert [call[1] for call in api.calls] == ["EURUSD-OTC", "EURUSD-op"]


@pytest.mark.asyncio
async def test_adapter_can_resolve_dynamic_asset_ids() -> None:
    api = FakeIQOptionAPI()
    adapter = IQOptionBinaryExecutionAdapter(
        api,
        active_codes={},
        asset_id_lookup=lambda name: 77 if name == "GBPUSD-OTC" else None,
    )

    result = await adapter.place_binary_order(command("GBPUSD"))

    assert result.accepted is True
    assert api.calls[0][1] == "GBPUSD-OTC"


@pytest.mark.asyncio
async def test_adapter_fails_without_any_otc_variant() -> None:
    adapter = IQOptionBinaryExecutionAdapter(FakeIQOptionAPI(), active_codes={})

    result = await adapter.place_binary_order(command())

    assert result.accepted is False
    assert result.order_id is None
    assert "No OTC variant" in (result.error or "")


@pytest.mark.asyncio
async def test_connection_error_marks_adapter_disconnected() -> None:
    disconnected = []
    adapter = IQOptionBinaryExecutionAdapter(
        FakeIQOptionAPI(error=ConnectionError("socket closed")),
        active_codes={"EURUSD-OTC": 1},
        on_connection_lost=lambda: disconnected.append(True),
    )

    result = await adapter.place_binary_order(command())

    assert result.accepted is False
    assert result.error == "Connection lost"
    assert disconnected == [True]


@pytest.mark.asyncio
async def test_asset_resolver_delegates_order_placement_to_adapter() -> None:
    worker = type("Worker", (), {"api": FakeIQOptionAPI(), "is_connected": True})()
    execution = AsyncMock()
    execution.place_binary_order.return_value.accepted = True
    execution.place_binary_order.return_value.order_id = 555
    execution.place_binary_order.return_value.error = None
    resolver = AssetResolver(worker, execution_adapter=execution)

    success, order_id = await resolver.place_trade("EURUSD", "call", 1.0, 2)

    assert (success, order_id) == (True, 555)
    execution.place_binary_order.assert_awaited_once()
    submitted = execution.place_binary_order.await_args.args[0]
    assert submitted.asset == "EURUSD"
    assert submitted.amount == Decimal("1.0")
