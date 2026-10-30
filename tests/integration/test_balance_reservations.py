from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.storage.models import metadata
from trading_platform.storage.repository import LedgerRepository

from tests.integration.test_order_manager_recovery import intent
from tests.integration.test_account_reconciliation import snapshot


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'reservations.db'}")
    metadata.create_all(engine)
    repo = LedgerRepository(engine)
    repo.record_intent(intent())
    repo.replace_account_snapshot(snapshot())
    return repo


def test_reservation_reduces_available_balance_and_release_restores_it(repository) -> None:
    created = repository.reserve_balance(
        reservation_id="reserve-1",
        client_order_id="order-1",
        venue="bybit",
        environment=TradingEnvironment.TESTNET,
        asset="usdt",
        amount=Decimal("100"),
    )

    assert created
    assert repository.available_after_reservations(
        "BYBIT", TradingEnvironment.TESTNET, "USDT"
    ) == Decimal("800")
    assert repository.release_reservation("reserve-1")
    assert repository.available_after_reservations(
        "BYBIT", TradingEnvironment.TESTNET, "USDT"
    ) == Decimal("900")


def test_reservation_is_idempotent_but_cannot_be_rebound(repository) -> None:
    arguments = dict(
        reservation_id="reserve-1",
        client_order_id="order-1",
        venue="bybit",
        environment=TradingEnvironment.TESTNET,
        asset="usdt",
        amount=Decimal("100"),
    )
    assert repository.reserve_balance(**arguments)
    assert repository.reserve_balance(**arguments) is False
    with pytest.raises(ValueError, match="different funds"):
        repository.reserve_balance(**{**arguments, "amount": Decimal("101")})


def test_over_reservation_fails_closed(repository) -> None:
    with pytest.raises(ValueError, match="insufficient"):
        repository.reserve_balance(
            reservation_id="too-large",
            client_order_id="order-1",
            venue="bybit",
            environment=TradingEnvironment.TESTNET,
            asset="usdt",
            amount=Decimal("901"),
        )
