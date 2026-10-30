from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Quantity
from trading_platform.domain.orders import OrderIntent, OrderSide, OrderType, TimeInForce
from trading_platform.domain.risk import RiskDecision
from trading_platform.storage.models import metadata
from trading_platform.storage.outbox import OutboxPublisher
from trading_platform.storage.repository import LedgerRepository


def make_intent() -> OrderIntent:
    signal_id = UUID("00000000-0000-0000-0000-000000000001")
    environment = TradingEnvironment.TESTNET
    return OrderIntent(
        client_order_id="outbox-order",
        signal_id=signal_id,
        risk_decision=RiskDecision.approved(
            signal_id=signal_id,
            environment=environment,
            limits_snapshot={"max": "1"},
        ),
        instrument=InstrumentId("bybit", ProductType.SPOT, "BTCUSDT", "USDT"),
        environment=environment,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Quantity(Decimal("0.001")),
        time_in_force=TimeInForce.IOC,
    )


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'outbox.db'}")
    metadata.create_all(engine)
    repo = LedgerRepository(engine)
    repo.record_intent(make_intent())
    return repo


@pytest.mark.asyncio
async def test_outbox_publishes_then_marks_message(repository) -> None:
    class Sink:
        def __init__(self):
            self.events = []

        async def publish(self, **event):
            self.events.append(event)

    sink = Sink()
    result = await OutboxPublisher(repository, sink).run_once()

    assert (result.published, result.failed) == (1, 0)
    assert sink.events[0]["event_key"].startswith("outbox-order:")
    assert repository.pending_outbox_count() == 0


@pytest.mark.asyncio
async def test_outbox_stops_on_failure_and_retries_at_least_once(repository) -> None:
    class FlakySink:
        def __init__(self):
            self.calls = 0

        async def publish(self, **event):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("sink offline")

    sink = FlakySink()
    first = await OutboxPublisher(repository, sink).run_once()
    pending = repository.list_pending_outbox()
    second = await OutboxPublisher(repository, sink).run_once()

    assert (first.published, first.failed) == (0, 1)
    assert pending[0].last_error == "sink offline"
    assert (second.published, second.failed) == (1, 0)
    assert repository.pending_outbox_count() == 0
