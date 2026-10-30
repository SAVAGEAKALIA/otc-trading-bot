from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_platform.research.backtests import (
    BacktestEngine,
    CostModel,
    MarketBar,
    SignalEvent,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def bar(minute: int, close: str, *, instrument: str = "EURUSD-OTC") -> MarketBar:
    value = Decimal(close)
    return MarketBar(
        instrument=instrument,
        observed_at=BASE + timedelta(minutes=minute),
        open_price=value - Decimal("0.01"),
        high_price=value + Decimal("0.02"),
        low_price=value - Decimal("0.02"),
        close_price=value,
    )


def signal(
    signal_id: str,
    minute: int,
    direction: str,
    expiry_minute: int,
    *,
    stake: str = "10",
) -> SignalEvent:
    return SignalEvent(
        signal_id=signal_id,
        instrument="EURUSD-OTC",
        decision_at=BASE + timedelta(minutes=minute),
        direction=direction,
        stake=Decimal(stake),
        payout_ratio=Decimal("0.84"),
        expires_at=BASE + timedelta(minutes=expiry_minute),
    )


def test_binary_backtest_is_causal_and_cost_aware() -> None:
    result = BacktestEngine(
        CostModel(fixed_fee=Decimal("0.10"), slippage_bps=Decimal("10"))
    ).run(
        bars=[bar(0, "1.00"), bar(1, "1.20"), bar(2, "1.30")],
        signals=[signal("s1", 0, "call", 2)],
        starting_equity=Decimal("100"),
    )

    assert result.filled_trades == 1
    assert result.settled_trades == 1
    assert result.wins == 1
    assert result.losses == 0
    assert result.unresolved_trades == 0
    assert result.net_pnl == Decimal("8.29")
    assert result.ending_equity == Decimal("108.29")
    assert result.trades[0].entry_at == BASE + timedelta(minutes=1)


@pytest.mark.parametrize("direction", ["call", "put"])
def test_equal_settlement_is_a_tie(direction: str) -> None:
    result = BacktestEngine().run(
        bars=[bar(0, "1.00"), bar(1, "1.01"), bar(2, "1.01")],
        signals=[signal("tie", 0, direction, 2)],
        starting_equity=Decimal("100"),
    )

    assert result.ties == 1
    assert result.net_pnl == Decimal("0")


def test_missing_expiry_is_unresolved_and_not_counted_as_loss() -> None:
    result = BacktestEngine().run(
        bars=[bar(0, "1.00"), bar(1, "1.01")],
        signals=[signal("open", 0, "call", 3)],
        starting_equity=Decimal("100"),
    )

    assert result.filled_trades == 1
    assert result.settled_trades == 0
    assert result.unresolved_trades == 1
    assert result.net_pnl == Decimal("0")


def test_signal_at_or_after_last_bar_cannot_fill() -> None:
    result = BacktestEngine().run(
        bars=[bar(0, "1.00"), bar(1, "1.01")],
        signals=[signal("late", 1, "call", 2)],
        starting_equity=Decimal("100"),
    )

    assert result.filled_trades == 0
    assert result.rejected_signals == 1


def test_duplicate_signal_ids_and_non_monotonic_events_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate signal"):
        BacktestEngine().run(
            bars=[bar(0, "1.00"), bar(1, "1.01")],
            signals=[signal("same", 0, "call", 1), signal("same", 0, "put", 1)],
            starting_equity=Decimal("100"),
        )

    with pytest.raises(ValueError, match="chronological"):
        BacktestEngine().run(
            bars=[bar(1, "1.00"), bar(0, "1.01")],
            signals=[],
            starting_equity=Decimal("100"),
        )


def test_report_record_is_deterministic() -> None:
    engine = BacktestEngine()
    kwargs = dict(
        bars=[bar(0, "1.00"), bar(1, "1.20"), bar(2, "1.30")],
        signals=[signal("s1", 0, "call", 2)],
        starting_equity=Decimal("100"),
    )
    assert engine.run(**kwargs).to_record() == engine.run(**kwargs).to_record()
