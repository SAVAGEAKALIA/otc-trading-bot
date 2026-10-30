from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from .models import BacktestResult, CostModel, MarketBar, SignalEvent, TradeResult


class BacktestEngine:
    def __init__(self, costs: CostModel | None = None) -> None:
        self.costs = costs or CostModel()

    def run(
        self,
        *,
        bars: Iterable[MarketBar],
        signals: Iterable[SignalEvent],
        starting_equity: Decimal,
    ) -> BacktestResult:
        if not starting_equity.is_finite() or starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        ordered_bars = list(bars)
        if any(left.observed_at >= right.observed_at for left, right in zip(ordered_bars, ordered_bars[1:])):
            raise ValueError("bars must be chronological")
        by_instrument: dict[str, list[MarketBar]] = {}
        for item in ordered_bars:
            by_instrument.setdefault(item.instrument.upper(), []).append(item)
        ordered_signals = sorted(signals, key=lambda item: (item.decision_at, item.signal_id))
        seen: set[str] = set()
        trades: list[TradeResult] = []
        rejected = 0
        unresolved = 0
        for event in ordered_signals:
            if event.signal_id in seen:
                raise ValueError("duplicate signal id")
            seen.add(event.signal_id)
            candidates = [bar for bar in by_instrument.get(event.instrument.upper(), []) if bar.observed_at > event.decision_at]
            if not candidates:
                rejected += 1
                continue
            entry = candidates[0]
            expiry = next((bar for bar in candidates if bar.observed_at >= event.expires_at), None)
            if expiry is None:
                unresolved += 1
                continue
            entry_price = entry.close_price
            exit_price = expiry.close_price
            direction = event.direction.lower()
            won = exit_price > entry_price if direction == "call" else exit_price < entry_price
            tied = exit_price == entry_price
            gross = (
                event.stake * (Decimal("1") + event.payout_ratio)
                if won
                else event.stake
                if tied
                else Decimal("0")
            )
            gross_pnl = gross - event.stake
            costs = self.costs.fixed_fee + event.stake * self.costs.slippage_bps / Decimal("10000")
            net = gross_pnl - costs
            trades.append(TradeResult(event.signal_id, event.instrument, direction, entry.observed_at, expiry.observed_at, entry_price, exit_price, event.stake, gross_pnl, costs, net, "tie" if tied else "win" if won else "loss"))
        pnl = sum((item.net_pnl for item in trades), Decimal("0"))
        return BacktestResult(tuple(trades), rejected, unresolved, starting_equity, starting_equity + pnl)
