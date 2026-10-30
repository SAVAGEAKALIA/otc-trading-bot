"""Deterministic, point-in-time crypto research baselines.

The module intentionally contains no broker, credential, or network dependency.
Signals are generated only from bars strictly before the decision bar and the
engine applies explicit fee, slippage, funding, leverage, and exposure bounds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_platform.domain.time import require_utc


def _positive(value: Decimal, name: str, *, zero: bool = False) -> None:
    if not value.is_finite() or (value < 0 if zero else value <= 0):
        qualifier = "non-negative" if zero else "positive"
        raise ValueError(f"{name} must be finite and {qualifier}")


@dataclass(frozen=True, slots=True)
class CryptoBar:
    instrument: str
    observed_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    funding_rate: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        instrument = self.instrument.strip().upper()
        if not instrument:
            raise ValueError("instrument must not be empty")
        require_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "instrument", instrument)
        for name in ("open_price", "high_price", "low_price", "close_price"):
            _positive(getattr(self, name), name)
        _positive(self.volume, "volume", zero=True)
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("high_price is below candle prices")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("low_price is above candle prices")
        if not self.funding_rate.is_finite():
            raise ValueError("funding_rate must be finite")


@dataclass(frozen=True, slots=True)
class PointInTimeUniverse:
    """Symbols available at an observation time, with no future leakage."""

    observed_at: datetime
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        require_utc(self.observed_at, "observed_at")
        normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in self.symbols))
        if not normalized or any(not symbol for symbol in normalized):
            raise ValueError("universe symbols must be non-empty and unique")
        object.__setattr__(self, "symbols", normalized)


@dataclass(frozen=True, slots=True)
class CryptoSignal:
    signal_id: str
    instrument: str
    decision_at: datetime
    direction: str
    notional: Decimal
    holding_bars: int = 1

    def __post_init__(self) -> None:
        if not self.signal_id.strip():
            raise ValueError("signal_id must not be empty")
        require_utc(self.decision_at, "decision_at")
        direction = self.direction.strip().lower()
        if direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "instrument", self.instrument.strip().upper())
        if not self.instrument:
            raise ValueError("instrument must not be empty")
        _positive(self.notional, "notional")
        if self.holding_bars < 1:
            raise ValueError("holding_bars must be positive")


@dataclass(frozen=True, slots=True)
class CryptoCostModel:
    taker_fee_bps: Decimal = Decimal("5")
    maker_fee_bps: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("2")
    funding_bps_per_bar: Decimal = Decimal("0")
    leverage: Decimal = Decimal("1")
    maximum_gross_notional: Decimal = Decimal("100000")
    maximum_open_positions: int = 1

    def __post_init__(self) -> None:
        for name in ("taker_fee_bps", "maker_fee_bps", "slippage_bps", "funding_bps_per_bar"):
            _positive(getattr(self, name), name, zero=True)
        _positive(self.leverage, "leverage")
        _positive(self.maximum_gross_notional, "maximum_gross_notional")
        if self.maximum_open_positions < 1:
            raise ValueError("maximum_open_positions must be positive")


def _ordered_bars(bars: Iterable[CryptoBar]) -> dict[str, list[CryptoBar]]:
    grouped: dict[str, list[CryptoBar]] = {}
    for bar in bars:
        grouped.setdefault(bar.instrument, []).append(bar)
    for values in grouped.values():
        if any(left.observed_at >= right.observed_at for left, right in zip(values, values[1:])):
            raise ValueError("bars must be chronological per instrument")
    return grouped


def _signals_from_returns(
    bars: Iterable[CryptoBar], *, lookback: int, threshold: Decimal, mode: str
) -> tuple[CryptoSignal, ...]:
    if lookback < 1 or not threshold.is_finite() or threshold < 0:
        raise ValueError("lookback and threshold are invalid")
    grouped = _ordered_bars(bars)
    result: list[CryptoSignal] = []
    for instrument, values in grouped.items():
        for index in range(lookback, len(values)):
            previous = values[index - lookback].close_price
            current = values[index].close_price
            change = (current - previous) / previous
            if mode == "momentum" and abs(change) >= threshold:
                direction = "long" if change > 0 else "short"
            elif mode == "mean_reversion" and abs(change) >= threshold:
                direction = "short" if change > 0 else "long"
            else:
                continue
            result.append(CryptoSignal(
                f"{mode}-{instrument}-{values[index].observed_at.isoformat()}",
                instrument,
                values[index].observed_at,
                direction,
                current,
            ))
    return tuple(result)


def generate_momentum_signals(
    bars: Iterable[CryptoBar], *, lookback: int = 1, threshold: Decimal = Decimal("0")
) -> tuple[CryptoSignal, ...]:
    return _signals_from_returns(bars, lookback=lookback, threshold=threshold, mode="momentum")


def generate_mean_reversion_signals(
    bars: Iterable[CryptoBar], *, lookback: int = 3, threshold: Decimal = Decimal("0")
) -> tuple[CryptoSignal, ...]:
    return _signals_from_returns(bars, lookback=lookback, threshold=threshold, mode="mean_reversion")


def generate_breakout_signals(
    bars: Iterable[CryptoBar], *, lookback: int = 3
) -> tuple[CryptoSignal, ...]:
    if lookback < 1:
        raise ValueError("lookback must be positive")
    grouped = _ordered_bars(bars)
    result: list[CryptoSignal] = []
    for instrument, values in grouped.items():
        for index in range(lookback, len(values)):
            history = values[index - lookback:index]
            current = values[index]
            if current.close_price > max(item.high_price for item in history):
                direction = "long"
            elif current.close_price < min(item.low_price for item in history):
                direction = "short"
            else:
                continue
            result.append(CryptoSignal(
                f"breakout-{instrument}-{current.observed_at.isoformat()}",
                instrument, current.observed_at, direction, current.close_price,
            ))
    return tuple(result)


class CryptoResearchEngine:
    def __init__(self, costs: CryptoCostModel | None = None) -> None:
        self.costs = costs or CryptoCostModel()

    def run(
        self,
        *,
        bars: Iterable[CryptoBar],
        signals: Iterable[CryptoSignal],
        universe: Iterable[PointInTimeUniverse],
        starting_equity: Decimal,
    ) -> Mapping[str, Decimal | int]:
        _positive(starting_equity, "starting_equity")
        grouped = _ordered_bars(bars)
        snapshots = sorted(universe, key=lambda item: item.observed_at)
        if any(left.observed_at > right.observed_at for left, right in zip(snapshots, snapshots[1:])):
            raise ValueError("universe snapshots must be chronological")
        seen: set[str] = set()
        gross = Decimal("0")
        costs = Decimal("0")
        accepted = 0
        rejected = 0
        open_until: list[datetime] = []
        for signal in sorted(signals, key=lambda item: (item.decision_at, item.signal_id)):
            if signal.signal_id in seen:
                raise ValueError("duplicate signal id")
            seen.add(signal.signal_id)
            active = next((item for item in reversed(snapshots) if item.observed_at <= signal.decision_at), None)
            if active is None or signal.instrument not in active.symbols:
                rejected += 1
                continue
            values = grouped.get(signal.instrument, [])
            entry_index = next((idx for idx, item in enumerate(values) if item.observed_at > signal.decision_at), None)
            if entry_index is None or entry_index + signal.holding_bars >= len(values):
                rejected += 1
                continue
            if signal.notional * self.costs.leverage > self.costs.maximum_gross_notional:
                rejected += 1
                continue
            open_until = [item for item in open_until if item > signal.decision_at]
            if len(open_until) >= self.costs.maximum_open_positions:
                rejected += 1
                continue
            entry = values[entry_index]
            exit_bar = values[entry_index + signal.holding_bars]
            move = (exit_bar.close_price - entry.close_price) / entry.close_price
            if signal.direction == "short":
                move = -move
            gross += signal.notional * move * self.costs.leverage
            turnover = signal.notional * 2
            costs += turnover * (self.costs.taker_fee_bps + self.costs.slippage_bps) / Decimal("10000")
            costs += signal.notional * self.costs.funding_bps_per_bar * signal.holding_bars / Decimal("10000")
            accepted += 1
            open_until.append(exit_bar.observed_at)
        net = gross - costs
        return {
            "accepted_signals": accepted,
            "rejected_signals": rejected,
            "gross_pnl": gross,
            "costs": costs,
            "net_pnl": net,
            "ending_equity": starting_equity + net,
        }


@dataclass(frozen=True, slots=True)
class CryptoCandidateAssessment:
    hypothesis_id: str
    passed: bool
    reasons: tuple[str, ...]
    baseline_reports: tuple[Mapping[str, Decimal | int], ...]
    adverse_reports: tuple[Mapping[str, Decimal | int], ...]

    def __post_init__(self) -> None:
        if not self.hypothesis_id.strip():
            raise ValueError("hypothesis_id must not be empty")
        if self.passed == bool(self.reasons):
            raise ValueError("passing assessments cannot have reasons and failures require reasons")


def assess_crypto_candidate(
    *,
    hypothesis_id: str,
    baseline_reports: Iterable[Mapping[str, Decimal | int]],
    adverse_reports: Iterable[Mapping[str, Decimal | int]],
    minimum_accepted_signals: int,
) -> CryptoCandidateAssessment:
    """Evaluate Section 29's first gates without promoting or selecting a model."""

    if not hypothesis_id.strip():
        raise ValueError("hypothesis_id must not be empty")
    if minimum_accepted_signals < 1:
        raise ValueError("minimum_accepted_signals must be positive")
    baseline = tuple(dict(item) for item in baseline_reports)
    adverse = tuple(dict(item) for item in adverse_reports)
    if not baseline or not adverse:
        raise ValueError("baseline and adverse reports are required")
    reasons: list[str] = []
    accepted = sum(int(item.get("accepted_signals", 0)) for item in baseline)
    if accepted < minimum_accepted_signals:
        reasons.append("insufficient accepted signals")
    if any(Decimal(item.get("net_pnl", 0)) <= 0 for item in baseline):
        reasons.append("baseline cost-adjusted expectancy is not positive")
    if any(Decimal(item.get("net_pnl", 0)) <= 0 for item in adverse):
        reasons.append("candidate does not survive adverse costs")
    positive = [Decimal(item.get("net_pnl", 0)) for item in baseline]
    if len(positive) >= 3:
        ordered = sorted(positive)
        neighbours = ordered[-2]
        if neighbours <= 0 or ordered[-1] > neighbours * Decimal("3"):
            reasons.append("performance is concentrated in a single parameter spike")
    return CryptoCandidateAssessment(
        hypothesis_id.strip(), not reasons, tuple(dict.fromkeys(reasons)), baseline, adverse
    )


def evaluate_parameter_surface(
    *,
    bars: Iterable[CryptoBar],
    universe: Iterable[PointInTimeUniverse],
    starting_equity: Decimal,
    parameter_values: Iterable[int],
    strategy: str = "momentum",
) -> tuple[Mapping[str, Decimal | int], ...]:
    """Run a predeclared baseline over each parameter without selecting winners."""

    values = tuple(parameter_values)
    if not values or any(value < 1 for value in values):
        raise ValueError("parameter_values must contain positive integers")
    if strategy == "momentum":
        generator = generate_momentum_signals
    elif strategy == "mean_reversion":
        generator = generate_mean_reversion_signals
    elif strategy == "breakout":
        generator = generate_breakout_signals
    else:
        raise ValueError("strategy is not supported")
    frozen_bars = tuple(bars)
    frozen_universe = tuple(universe)
    reports: list[Mapping[str, Decimal | int]] = []
    for value in values:
        signals = generator(frozen_bars, lookback=value)
        report = CryptoResearchEngine().run(
            bars=frozen_bars,
            signals=signals,
            universe=frozen_universe,
            starting_equity=starting_equity,
        )
        reports.append({"parameter": value, **report})
    return tuple(reports)
