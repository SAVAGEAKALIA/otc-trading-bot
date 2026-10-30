from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Quantity
from trading_platform.domain.orders import OrderIntent, OrderSide, OrderStatus, OrderType, TimeInForce
from trading_platform.domain.risk import RiskDecision
from trading_platform.execution.order_manager import (
    BrokerExecution,
    BrokerOrderSnapshot,
    OrderManager,
)
from trading_platform.execution.reconciler import OrderReconciler
from trading_platform.storage.models import executions, metadata, order_events, orders, outbox
from trading_platform.storage.repository import LedgerRepository


class ProcessCrash(BaseException):
    pass


class FakeGateway:
    def __init__(self, *, crash_after_accept: bool = False):
        self.orders = {}
        self.submit_calls = 0
        self.query_calls = 0
        self.crash_after_accept = crash_after_accept

    async def submit_order(self, intent):
        self.submit_calls += 1
        snapshot = BrokerOrderSnapshot(
            client_order_id=intent.client_order_id,
            broker_order_id=f"broker-{self.submit_calls}",
            status=OrderStatus.ACKNOWLEDGED,
        )
        self.orders[intent.client_order_id] = snapshot
        if self.crash_after_accept:
            raise ProcessCrash()
        return snapshot

    async def get_order(self, client_order_id):
        self.query_calls += 1
        return self.orders.get(client_order_id)


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ledger.db'}")
    metadata.create_all(engine)
    return LedgerRepository(engine)


def intent(client_order_id="order-1"):
    signal_id = UUID("00000000-0000-0000-0000-000000000001")
    environment = TradingEnvironment.TESTNET
    return OrderIntent(
        client_order_id=client_order_id,
        signal_id=signal_id,
        risk_decision=RiskDecision.approved(
            signal_id=signal_id,
            environment=environment,
            limits_snapshot={"max_order_notional": "100"},
        ),
        instrument=InstrumentId("bybit", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT"),
        environment=environment,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Quantity(Decimal("0.001")),
        time_in_force=TimeInForce.IOC,
    )


@pytest.mark.asyncio
async def test_intent_is_durable_before_gateway_submission(repository):
    class InspectingGateway(FakeGateway):
        async def submit_order(self, submitted):
            assert repository.get_order(submitted.client_order_id).status is OrderStatus.SUBMISSION_STARTED
            return await super().submit_order(submitted)

    result = await OrderManager(repository, InspectingGateway()).submit(intent())

    assert result.status is OrderStatus.ACKNOWLEDGED
    assert [event.status for event in repository.list_order_events("order-1")] == [
        OrderStatus.INTENT_RECORDED,
        OrderStatus.SUBMISSION_STARTED,
        OrderStatus.ACKNOWLEDGED,
    ]
    assert repository.pending_outbox_count() == 3


@pytest.mark.asyncio
async def test_duplicate_submission_is_idempotent(repository):
    gateway = FakeGateway()
    manager = OrderManager(repository, gateway)
    proposed = intent()

    first = await manager.submit(proposed)
    second = await manager.submit(proposed)

    assert second == first
    assert gateway.submit_calls == 1
    assert repository.order_count() == 1


@pytest.mark.asyncio
async def test_restart_recovers_broker_acceptance_after_process_crash(repository):
    gateway = FakeGateway(crash_after_accept=True)
    with pytest.raises(ProcessCrash):
        await OrderManager(repository, gateway).submit(intent())

    assert repository.get_order("order-1").status is OrderStatus.SUBMISSION_STARTED
    gateway.crash_after_accept = False
    recovered = await OrderReconciler(repository, gateway).reconcile_open_orders()

    assert recovered[0].status is OrderStatus.ACKNOWLEDGED
    assert recovered[0].broker_order_id == "broker-1"
    assert gateway.submit_calls == 1


@pytest.mark.asyncio
async def test_restart_resumes_intent_that_was_never_claimed(repository):
    proposed = intent()
    repository.record_intent(proposed)
    gateway = FakeGateway()

    resumed = await OrderManager(repository, gateway).submit(proposed)

    assert resumed.status is OrderStatus.ACKNOWLEDGED
    assert gateway.submit_calls == 1


@pytest.mark.asyncio
async def test_ambiguous_submission_becomes_unknown_and_is_not_resubmitted(repository):
    proposed = intent()
    repository.record_intent(proposed)
    assert repository.claim_submission("order-1")
    gateway = FakeGateway()

    reconciled = await OrderReconciler(repository, gateway).reconcile_open_orders()
    repeated = await OrderManager(repository, gateway).submit(proposed)

    assert reconciled[0].status is OrderStatus.UNKNOWN
    assert repeated.status is OrderStatus.UNKNOWN
    assert gateway.submit_calls == 0


@pytest.mark.asyncio
async def test_reconciliation_records_fill_and_deduplicates_execution(repository):
    gateway = FakeGateway()
    await OrderManager(repository, gateway).submit(intent())
    gateway.orders["order-1"] = BrokerOrderSnapshot(
        client_order_id="order-1",
        broker_order_id="broker-1",
        status=OrderStatus.FILLED,
        executions=(
            BrokerExecution("exec-1", Decimal("0.001"), Decimal("50000"), Decimal("0.01")),
        ),
    )
    reconciler = OrderReconciler(repository, gateway)

    await reconciler.reconcile_open_orders()
    await reconciler.reconcile_open_orders()

    assert repository.get_order("order-1").status is OrderStatus.FILLED
    assert repository.execution_count() == 1


def test_order_and_outbox_write_is_atomic(repository):
    repository.record_intent(intent())
    assert repository.order_count() == 1
    assert repository.pending_outbox_count() == 1

    message = repository.list_pending_outbox()[0]
    assert message.payload["status"] == OrderStatus.INTENT_RECORDED.value
    repository.record_outbox_error(message.event_key, "temporary sink failure")
    repository.mark_outbox_published(message.event_key)
    assert repository.pending_outbox_count() == 0


def test_fill_transition_and_execution_write_roll_back_together(repository):
    proposed = intent()
    repository.record_intent(proposed)
    repository.claim_submission(proposed.client_order_id)
    repository.transition(proposed.client_order_id, OrderStatus.ACKNOWLEDGED)

    invalid_execution = type(
        "InvalidExecution",
        (),
        {"execution_id": "bad", "quantity": None, "price": None, "fee": None},
    )()
    with pytest.raises(Exception):
        repository.transition(
            proposed.client_order_id,
            OrderStatus.FILLED,
            executions_to_record=(invalid_execution,),
        )

    assert repository.get_order(proposed.client_order_id).status is OrderStatus.ACKNOWLEDGED
    assert repository.execution_count() == 0


def test_schema_compiles_for_postgresql() -> None:
    dialect = postgresql.dialect()
    ddl = "\n".join(
        str(CreateTable(table).compile(dialect=dialect))
        for table in (orders, order_events, executions, outbox)
    )
    assert "CREATE TABLE orders" in ddl
    assert "CREATE TABLE outbox" in ddl


@pytest.mark.asyncio
async def test_database_outage_prevents_any_broker_call() -> None:
    class OfflineRepository:
        def record_intent(self, proposed):
            raise RuntimeError("database offline")

    gateway = FakeGateway()
    with pytest.raises(RuntimeError, match="database offline"):
        await OrderManager(OfflineRepository(), gateway).submit(intent())
    assert gateway.submit_calls == 0
