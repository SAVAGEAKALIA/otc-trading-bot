from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_platform.research.backtests.models import TradeResult
from trading_platform.research.metrics import summarize_trades


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def trade(signal_id: str, pnl: str, outcome: str) -> TradeResult:
    return TradeResult(
        signal_id=signal_id,
        instrument="EURUSD-OTC",
        direction="call",
        entry_at=BASE + timedelta(minutes=int(signal_id)),
        expiry_at=BASE + timedelta(minutes=int(signal_id) + 1),
        entry_price=Decimal("1"),
        exit_price=Decimal("1"),
        stake=Decimal("10"),
        gross_pnl=Decimal(pnl),
        costs=Decimal("0"),
        net_pnl=Decimal(pnl),
        outcome=outcome,
    )


def test_metrics_include_win_rate_profit_factor_and_drawdown() -> None:
    result = summarize_trades(
        starting_equity=Decimal("100"),
        trades=(trade("1", "-10", "loss"), trade("2", "8", "win"), trade("3", "5", "win")),
    )

    assert result.total_trades == 3
    assert result.win_rate == Decimal("0.6666666666666666666666666667")
    assert result.profit_factor == Decimal("1.3")
    assert result.net_pnl == Decimal("3")
    assert result.max_drawdown == Decimal("10")


def test_empty_metrics_are_zero_and_deterministic() -> None:
    result = summarize_trades(starting_equity=Decimal("100"), trades=())

    assert result.to_record() == {
        "schema_version": "performance_summary_v1",
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "win_rate": "0",
        "profit_factor": "0",
        "net_pnl": "0",
        "max_drawdown": "0",
    }
