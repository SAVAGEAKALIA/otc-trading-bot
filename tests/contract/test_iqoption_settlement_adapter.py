from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from trading_platform.brokers.iqoption.settlement import IQOptionSettlementGateway
from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.money import Quantity
from trading_platform.domain.orders import (
    BinaryDirection,
    BinaryOptionTerms,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from trading_platform.domain.risk import RiskDecision
from trading_platform.domain.settlements import BinarySettlementOutcome
from trading_platform.storage.repository import LedgerOrder


NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def ledger_order() -> LedgerOrder:
    signal_id = UUID("00000000-0000-0000-0000-000000000123")
    environment = TradingEnvironment.PAPER
    return LedgerOrder(
        client_order_id="binary-1",
        intent=OrderIntent(
            client_order_id="binary-1",
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
                BinaryDirection.CALL, NOW - timedelta(minutes=1), Decimal("0.84")
            ),
        ),
        status=OrderStatus.ACKNOWLEDGED,
        broker_order_id="9001",
        version=3,
    )


class FakeHistoryAPI:
    def __init__(self, closed_options):
        self.closed_options = closed_options
        self.calls = []

    async def find_closed_option(self, broker_order_id):
        self.calls.append(broker_order_id)
        return next(
            (
                item
                for item in self.closed_options
                if str((item.get("id") or [""])[0]) == broker_order_id
            ),
            None,
        )


def broker_record(**overrides):
    values = {
        "id": [9001],
        "win": "win",
        "amount": 5,
        "win_amount": 9.2,
        "close_time": int(NOW.timestamp()),
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_normalizes_broker_confirmed_win() -> None:
    api = FakeHistoryAPI([broker_record()])

    result = await IQOptionSettlementGateway(api).get_binary_settlement(
        ledger_order()
    )

    assert result is not None
    assert result.outcome is BinarySettlementOutcome.WIN
    assert result.stake == Decimal("5")
    assert result.gross_return == Decimal("9.2")
    assert result.net_pnl == Decimal("4.2")
    assert result.source == "broker_api"
    assert api.calls == ["9001"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "win_amount", "outcome", "net_pnl"),
    [
        ("loose", 0, BinarySettlementOutcome.LOSS, Decimal("-5")),
        ("equal", 5, BinarySettlementOutcome.TIE, Decimal("0")),
        ("refund", 5, BinarySettlementOutcome.VOID, Decimal("0")),
    ],
)
async def test_normalizes_non_win_outcomes(status, win_amount, outcome, net_pnl) -> None:
    api = FakeHistoryAPI([broker_record(win=status, win_amount=win_amount)])

    result = await IQOptionSettlementGateway(api).get_binary_settlement(
        ledger_order()
    )

    assert result is not None
    assert result.outcome is outcome
    assert result.net_pnl == net_pnl


@pytest.mark.asyncio
async def test_missing_order_remains_pending() -> None:
    api = FakeHistoryAPI([broker_record(id=[1234])])

    result = await IQOptionSettlementGateway(api).get_binary_settlement(
        ledger_order()
    )

    assert result is None


@pytest.mark.asyncio
async def test_broker_stake_mismatch_is_rejected() -> None:
    api = FakeHistoryAPI([broker_record(amount=50, win_amount=92)])

    with pytest.raises(ValueError, match="stake"):
        await IQOptionSettlementGateway(api).get_binary_settlement(ledger_order())


@pytest.mark.asyncio
async def test_internally_inconsistent_loss_cashflow_is_rejected() -> None:
    api = FakeHistoryAPI([broker_record(win="loose", win_amount=9.2)])

    with pytest.raises(ValueError, match="non-zero gross return"):
        await IQOptionSettlementGateway(api).get_binary_settlement(ledger_order())


@pytest.mark.asyncio
async def test_missing_broker_timestamp_is_not_authoritative() -> None:
    item = broker_record()
    del item["close_time"]

    with pytest.raises(ValueError, match="timestamp"):
        await IQOptionSettlementGateway(
            FakeHistoryAPI([item])
        ).get_binary_settlement(ledger_order())
