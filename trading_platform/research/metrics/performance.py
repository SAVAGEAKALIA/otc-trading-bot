from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Iterable

from trading_platform.research.backtests.models import TradeResult


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    total_trades: int
    wins: int
    losses: int
    ties: int
    win_rate: Decimal
    profit_factor: Decimal
    net_pnl: Decimal
    max_drawdown: Decimal

    def to_record(self) -> dict[str, object]:
        return {
            "schema_version": "performance_summary_v1",
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "win_rate": str(self.win_rate),
            "profit_factor": str(self.profit_factor),
            "net_pnl": str(self.net_pnl),
            "max_drawdown": str(self.max_drawdown),
        }


def summarize_trades(*, starting_equity: Decimal, trades: Iterable[TradeResult]) -> PerformanceSummary:
    if not starting_equity.is_finite() or starting_equity <= 0:
        raise ValueError("starting_equity must be positive")
    ordered = tuple(trades)
    wins = sum(item.outcome == "win" for item in ordered)
    losses = sum(item.outcome == "loss" for item in ordered)
    ties = sum(item.outcome == "tie" for item in ordered)
    decided = wins + losses
    win_rate = (
        Decimal(wins) / Decimal(decided)
        if decided
        else Decimal("0")
    )
    positive = sum((item.net_pnl for item in ordered if item.net_pnl > 0), Decimal("0"))
    negative = sum((-item.net_pnl for item in ordered if item.net_pnl < 0), Decimal("0"))
    profit_factor = positive / negative if negative else Decimal("0")
    equity = starting_equity
    peak = starting_equity
    max_drawdown = Decimal("0")
    for item in ordered:
        equity += item.net_pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return PerformanceSummary(
        total_trades=len(ordered),
        wins=wins,
        losses=losses,
        ties=ties,
        win_rate=win_rate,
        profit_factor=profit_factor,
        net_pnl=sum((item.net_pnl for item in ordered), Decimal("0")),
        max_drawdown=max_drawdown,
    )
