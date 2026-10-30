from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from trading_platform.domain.settlements import BinarySettlement, BinarySettlementOutcome
from trading_platform.storage.models import binary_settlements


NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def settlement(**overrides) -> BinarySettlement:
    values = {
        "venue_settlement_id": "settlement-1",
        "client_order_id": "binary-1",
        "broker_order_id": "broker-1",
        "outcome": BinarySettlementOutcome.WIN,
        "stake": Decimal("5"),
        "gross_return": Decimal("9.20"),
        "net_pnl": Decimal("4.20"),
        "settlement_asset": "USD",
        "settled_at": NOW,
        "source": "broker_api",
        "evidence": {"status": "win"},
    }
    values.update(overrides)
    return BinarySettlement(**values)


def test_binary_settlement_preserves_exact_accounting() -> None:
    item = settlement()

    assert item.net_pnl == item.gross_return - item.stake
    assert item.outcome is BinarySettlementOutcome.WIN


@pytest.mark.parametrize(
    ("outcome", "gross_return", "net_pnl"),
    [
        (BinarySettlementOutcome.LOSS, Decimal("1"), Decimal("-4")),
        (BinarySettlementOutcome.TIE, Decimal("0"), Decimal("-5")),
        (BinarySettlementOutcome.WIN, Decimal("5"), Decimal("0")),
    ],
)
def test_outcome_must_match_cashflows(outcome, gross_return, net_pnl) -> None:
    with pytest.raises(ValueError):
        settlement(outcome=outcome, gross_return=gross_return, net_pnl=net_pnl)


def test_only_broker_api_can_create_authoritative_settlement() -> None:
    with pytest.raises(ValueError, match="broker_api"):
        settlement(source="balance_estimate")


def test_binary_settlement_schema_compiles_for_postgresql() -> None:
    ddl = str(CreateTable(binary_settlements).compile(dialect=postgresql.dialect()))

    assert "CREATE TABLE binary_settlements" in ddl
    assert "NUMERIC(38, 18)" in ddl
