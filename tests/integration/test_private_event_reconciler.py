from decimal import Decimal
from uuid import UUID

import pytest

from trading_platform.brokers.bybit.order_events import normalize_order_event
from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Quantity
from trading_platform.domain.orders import OrderIntent, OrderSide, OrderType, TimeInForce, OrderStatus
from trading_platform.domain.risk import RiskDecision
from trading_platform.execution.private_event_reconciler import PrivateEventReconciler
from trading_platform.storage.models import metadata
from trading_platform.storage.repository import LedgerRepository
from sqlalchemy import create_engine


def test_private_event_applies_to_ledger_and_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    repo = LedgerRepository(engine)
    signal = UUID("00000000-0000-0000-0000-000000000001")
    intent = OrderIntent(
        client_order_id="client-1", signal_id=signal,
        risk_decision=RiskDecision.approved(signal_id=signal, environment=TradingEnvironment.TESTNET, limits_snapshot={"max": "1"}),
        instrument=InstrumentId("BYBIT", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT"),
        environment=TradingEnvironment.TESTNET, side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=Quantity(Decimal("1")), time_in_force=TimeInForce.GTC,
    )
    repo.record_intent(intent); repo.claim_submission("client-1")
    reconciler = PrivateEventReconciler(repo)
    payload = {"topic": "order", "data": [{"orderLinkId": "client-1", "orderId": "b1", "orderStatus": "Filled", "execId": "e1", "execQty": "1", "execPrice": "100", "execFee": "0"}]}
    assert reconciler.apply_bybit_event(payload).status is OrderStatus.FILLED
    assert reconciler.apply_bybit_event(payload).status is OrderStatus.FILLED
    assert repo.execution_count() == 1

