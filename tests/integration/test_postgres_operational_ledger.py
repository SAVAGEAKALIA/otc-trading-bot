import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import create_engine

from trading_platform.domain.environment import TradingEnvironment
from trading_platform.storage.repository import LedgerRepository

from tests.integration.test_account_reconciliation import snapshot
from tests.integration.test_order_manager_recovery import intent


POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL, reason="TEST_POSTGRES_URL is required for PostgreSQL integration"
)


@pytest.fixture
def postgres_repository():
    schema = f"phase5_{uuid4().hex}"
    assert POSTGRES_URL is not None
    with psycopg.connect(POSTGRES_URL, autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA "{schema}"')
        connection.execute(f'SET search_path TO "{schema}"')
        migration_dir = (
            Path(__file__).parents[2]
            / "src/trading_platform/storage/migrations"
        )
        for migration in sorted(migration_dir.glob("*.sql")):
            connection.execute(migration.read_text())

    engine = create_engine(
        POSTGRES_URL.replace("postgresql://", "postgresql+psycopg://", 1),
        connect_args={"options": f"-csearch_path={schema}"},
        pool_pre_ping=True,
    )
    try:
        yield LedgerRepository(engine)
    finally:
        engine.dispose()
        with psycopg.connect(POSTGRES_URL, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


def test_migrations_and_ledger_contract_run_on_postgresql(postgres_repository) -> None:
    repository = postgres_repository
    proposed = intent()

    repository.record_intent(proposed)
    repository.replace_account_snapshot(snapshot())
    repository.reserve_balance(
        reservation_id="pg-reservation",
        client_order_id=proposed.client_order_id,
        venue="bybit",
        environment=TradingEnvironment.TESTNET,
        asset="usdt",
        amount=proposed.quantity.value,
    )

    assert repository.order_count() == 1
    assert repository.available_after_reservations(
        "bybit", TradingEnvironment.TESTNET, "usdt"
    ).is_finite()
    assert repository.pending_outbox_count() == 3
