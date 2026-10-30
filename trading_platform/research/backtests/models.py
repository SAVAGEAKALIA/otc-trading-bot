from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from trading_platform.domain.time import require_utc


def _positive(value: Decimal, name: str, *, allow_zero: bool = False) -> None:
    if not value.is_finite() or (value < 0 if allow_zero else value <= 0):
        raise ValueError(f"{name} must be finite and {'non-negative' if allow_zero else 'positive'}")


@dataclass(frozen=True, slots=True)
class MarketBar:
    instrument: str
    observed_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal

    def __post_init__(self) -> None:
        require_utc(self.observed_at, "observed_at")
        if not self.instrument.strip():
            raise ValueError("instrument must not be empty")
        for name in ("open_price", "high_price", "low_price", "close_price"):
            _positive(getattr(self, name), name, allow_zero=True)
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("high_price is below candle prices")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("low_price is above candle prices")


@dataclass(frozen=True, slots=True)
class SignalEvent:
    signal_id: str
    instrument: str
    decision_at: datetime
    direction: str
    stake: Decimal
    payout_ratio: Decimal
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.signal_id.strip() or not self.instrument.strip():
            raise ValueError("signal identity must not be empty")
        require_utc(self.decision_at, "decision_at")
        require_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.decision_at:
            raise ValueError("signal expiry must follow decision time")
        if self.direction.lower() not in {"call", "put"}:
            raise ValueError("direction must be call or put")
        _positive(self.stake, "stake")
        if not self.payout_ratio.is_finite() or not Decimal("0") < self.payout_ratio <= Decimal("1"):
            raise ValueError("payout_ratio must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class CostModel:
    fixed_fee: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _positive(self.fixed_fee, "fixed_fee", allow_zero=True)
        _positive(self.slippage_bps, "slippage_bps", allow_zero=True)


@dataclass(frozen=True, slots=True)
class TradeResult:
    signal_id: str
    instrument: str
    direction: str
    entry_at: datetime
    expiry_at: datetime
    entry_price: Decimal
    exit_price: Decimal
    stake: Decimal
    gross_pnl: Decimal
    costs: Decimal
    net_pnl: Decimal
    outcome: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: tuple[TradeResult, ...]
    rejected_signals: int
    unresolved_trades: int
    starting_equity: Decimal
    ending_equity: Decimal

    @property
    def filled_trades(self) -> int:
        return len(self.trades) + self.unresolved_trades

    @property
    def settled_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(item.outcome == "win" for item in self.trades)

    @property
    def losses(self) -> int:
        return sum(item.outcome == "loss" for item in self.trades)

    @property
    def ties(self) -> int:
        return sum(item.outcome == "tie" for item in self.trades)

    @property
    def net_pnl(self) -> Decimal:
        return sum((item.net_pnl for item in self.trades), Decimal("0"))

    @property
    def max_drawdown(self) -> Decimal:
        equity = self.starting_equity
        peak = equity
        drawdown = Decimal("0")
        for item in self.trades:
            equity += item.net_pnl
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        return drawdown

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": "event_backtest_result_v1",
            "rejected_signals": self.rejected_signals,
            "unresolved_trades": self.unresolved_trades,
            "starting_equity": str(self.starting_equity),
            "ending_equity": str(self.ending_equity),
            "net_pnl": str(self.net_pnl),
            "max_drawdown": str(self.max_drawdown),
            "trades": [
                {
                    key: (value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, Decimal) else value)
                    for key, value in asdict(item).items()
                }
                for item in self.trades
            ],
        }
