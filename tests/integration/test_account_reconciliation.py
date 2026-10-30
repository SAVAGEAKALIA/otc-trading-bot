from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.execution.account_reconciler import AccountReconciler
from trading_platform.storage.models import metadata
from trading_platform.storage.projections import (
    AccountSnapshot,
    BalanceProjection,
    PositionProjection,
)
from trading_platform.storage.repository import LedgerRepository


NOW = datetime(2026, 1, 1, tzinfo=UTC)
BTC = InstrumentId("bybit", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT")


def snapshot(snapshot_id="snapshot-1", quantity="0.1") -> AccountSnapshot:
    return AccountSnapshot(
        snapshot_id=snapshot_id,
        venue="bybit",
        environment=TradingEnvironment.TESTNET,
        as_of=NOW,
        balances=(BalanceProjection("USDT", Decimal("1000"), Decimal("900")),),
        positions=(
            PositionProjection(
                instrument=BTC,
                signed_quantity=Decimal(quantity),
                average_entry_price=Decimal("50000"),
                mark_price=Decimal("51000"),
                unrealized_pnl=Decimal("100"),
                leverage=Decimal("2"),
                liquidation_price=Decimal("30000"),
            ),
        ),
    )


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'accounts.db'}")
    metadata.create_all(engine)
    return LedgerRepository(engine)


@pytest.mark.asyncio
async def test_reconciler_atomically_replaces_account_projection(repository) -> None:
    class Gateway:
        async def get_account_snapshot(self):
            return snapshot()

    result = await AccountReconciler(repository, Gateway()).reconcile()
    balances, positions = repository.get_account_projection(
        "bybit", TradingEnvironment.TESTNET
    )

    assert result.snapshot_id == "snapshot-1"
    assert balances[0].available == Decimal("900")
    assert positions[0].signed_quantity == Decimal("0.1")
    assert repository.list_pending_outbox()[0].topic == "accounts.reconciled"


def test_new_broker_snapshot_replaces_stale_positions(repository) -> None:
    assert repository.replace_account_snapshot(snapshot("first", "0.1"))
    assert repository.replace_account_snapshot(snapshot("second", "0"))

    _, positions = repository.get_account_projection("BYBIT", TradingEnvironment.TESTNET)

    assert len(positions) == 1
    assert positions[0].signed_quantity == 0


def test_duplicate_snapshot_is_idempotent(repository) -> None:
    current = snapshot()
    assert repository.replace_account_snapshot(current)
    assert repository.replace_account_snapshot(current) is False
    assert repository.pending_outbox_count() == 1


def test_snapshot_rejects_cross_venue_positions() -> None:
    wrong = InstrumentId("weex", ProductType.LINEAR_PERPETUAL, "BTCUSDT", "USDT")
    with pytest.raises(ValueError, match="venue"):
        AccountSnapshot(
            snapshot_id="bad",
            venue="bybit",
            environment=TradingEnvironment.TESTNET,
            as_of=NOW,
            balances=(),
            positions=(
                PositionProjection(
                    wrong,
                    Decimal("1"),
                    Decimal("1"),
                    Decimal("1"),
                    Decimal("0"),
                    Decimal("1"),
                ),
            ),
        )
