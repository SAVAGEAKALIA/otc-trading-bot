from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Quantity
from trading_platform.domain.orders import (
    BinaryDirection,
    BinaryOptionTerms,
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
)
from trading_platform.domain.risk import RiskDecision
from trading_platform.domain.settlements import BinarySettlement, BinarySettlementOutcome
from trading_platform.execution.binary_settlement import BinarySettlementReconciler
from trading_platform.execution.order_manager import BrokerOrderSnapshot, OrderManager
from trading_platform.domain.orders import OrderStatus
from trading_platform.storage.models import metadata
from trading_platform.storage.repository import LedgerRepository


NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def binary_intent(client_order_id="binary-1", *, expires_at=None) -> OrderIntent:
    signal_id = UUID("00000000-0000-0000-0000-000000000099")
    environment = TradingEnvironment.PAPER
    return OrderIntent(
        client_order_id=client_order_id,
        signal_id=signal_id,
        risk_decision=RiskDecision.approved(
            signal_id=signal_id,
            environment=environment,
            limits_snapshot={"max_order_notional": "5"},
        ),
        instrument=InstrumentId(
            "iqoption", ProductType.BINARY_OPTION, "EURUSD-OTC", "USD"
        ),
        environment=environment,
        side=OrderSide.BUY,
        order_type=OrderType.BINARY,
        quantity=Quantity(Decimal("5")),
        time_in_force=TimeInForce.FOK,
        binary_terms=BinaryOptionTerms(
            direction=BinaryDirection.CALL,
            expires_at=expires_at or NOW - timedelta(minutes=1),
            payout_ratio=Decimal("0.84"),
        ),
    )


class SubmissionGateway:
    async def submit_order(self, intent):
        return BrokerOrderSnapshot(
            intent.client_order_id, "broker-1", OrderStatus.ACKNOWLEDGED
        )

    async def get_order(self, client_order_id):
        return None


class SettlementGateway:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    async def get_binary_settlement(self, order):
        self.calls.append(order.broker_order_id)
        return self.response


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'settlements.db'}")
    metadata.create_all(engine)
    return LedgerRepository(engine)


def confirmed_win() -> BinarySettlement:
    return BinarySettlement(
        venue_settlement_id="settlement-1",
        client_order_id="binary-1",
        broker_order_id="broker-1",
        outcome=BinarySettlementOutcome.WIN,
        stake=Decimal("5"),
        gross_return=Decimal("9.20"),
        net_pnl=Decimal("4.20"),
        settlement_asset="USD",
        settled_at=NOW,
        source="broker_api",
        evidence={"broker_status": "win"},
    )


@pytest.mark.asyncio
async def test_restart_reconciles_expired_unsettled_binary_order(repository) -> None:
    await OrderManager(repository, SubmissionGateway()).submit(binary_intent())
    gateway = SettlementGateway(confirmed_win())

    first = await BinarySettlementReconciler(
        repository, gateway, TradingEnvironment.PAPER
    ).reconcile_due(NOW)
    second = await BinarySettlementReconciler(
        repository, gateway, TradingEnvironment.PAPER
    ).reconcile_due(NOW)

    assert first == [confirmed_win()]
    assert second == []
    assert gateway.calls == ["broker-1"]
    assert repository.binary_settlement_count() == 1
    assert repository.get_binary_settlement("binary-1") == confirmed_win()


@pytest.mark.asyncio
async def test_pending_broker_response_remains_reconcilable(repository) -> None:
    await OrderManager(repository, SubmissionGateway()).submit(binary_intent())
    gateway = SettlementGateway(None)

    reconciler = BinarySettlementReconciler(
        repository, gateway, TradingEnvironment.PAPER
    )
    assert await reconciler.reconcile_due(NOW) == []
    assert await reconciler.reconcile_due(NOW) == []
    assert gateway.calls == ["broker-1", "broker-1"]
    assert repository.binary_settlement_count() == 0


@pytest.mark.asyncio
async def test_unexpired_order_is_not_queried(repository) -> None:
    await OrderManager(repository, SubmissionGateway()).submit(
        binary_intent(expires_at=NOW + timedelta(minutes=1))
    )
    gateway = SettlementGateway(confirmed_win())

    assert await BinarySettlementReconciler(
        repository, gateway, TradingEnvironment.PAPER
    ).reconcile_due(NOW) == []
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_mismatched_broker_evidence_is_rejected(repository) -> None:
    await OrderManager(repository, SubmissionGateway()).submit(binary_intent())
    wrong = confirmed_win()
    wrong = BinarySettlement(
        venue_settlement_id=wrong.venue_settlement_id,
        client_order_id=wrong.client_order_id,
        broker_order_id="different-broker-order",
        outcome=wrong.outcome,
        stake=wrong.stake,
        gross_return=wrong.gross_return,
        net_pnl=wrong.net_pnl,
        settlement_asset=wrong.settlement_asset,
        settled_at=wrong.settled_at,
        source=wrong.source,
        evidence=wrong.evidence,
    )

    with pytest.raises(ValueError, match="broker_order_id"):
        await BinarySettlementReconciler(
            repository, SettlementGateway(wrong), TradingEnvironment.PAPER
        ).reconcile_due(NOW)

    assert repository.binary_settlement_count() == 0


@pytest.mark.asyncio
async def test_reconciliation_environment_is_explicitly_isolated(repository) -> None:
    await OrderManager(repository, SubmissionGateway()).submit(binary_intent())
    gateway = SettlementGateway(confirmed_win())

    result = await BinarySettlementReconciler(
        repository, gateway, TradingEnvironment.SHADOW
    ).reconcile_due(NOW)

    assert result == []
    assert gateway.calls == []
