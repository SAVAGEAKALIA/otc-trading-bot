"""Pure, ordered pre-trade risk policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from trading_platform.domain.instruments import InstrumentId, ProductType
from trading_platform.domain.signals import SignalAction

from .state import RiskState


@dataclass(frozen=True, slots=True)
class RiskLimits:
    allowed_instruments: frozenset[InstrumentId]
    max_signal_age: timedelta
    max_state_age: timedelta
    max_market_data_age: timedelta
    max_order_notional: Decimal
    max_instrument_exposure: Decimal
    max_total_exposure: Decimal
    max_leverage: Decimal
    max_drawdown_fraction: Decimal
    max_open_orders: int
    min_liquidation_buffer_fraction: Decimal

    def __post_init__(self) -> None:
        if not self.allowed_instruments:
            raise ValueError("at least one instrument must be allowed")
        if min(self.max_signal_age, self.max_state_age, self.max_market_data_age) <= timedelta(0):
            raise ValueError("freshness limits must be positive")
        if min(
            self.max_order_notional,
            self.max_instrument_exposure,
            self.max_total_exposure,
            self.max_leverage,
        ) <= 0:
            raise ValueError("notional, exposure and leverage limits must be positive")
        if not Decimal("0") < self.max_drawdown_fraction < Decimal("1"):
            raise ValueError("max drawdown fraction must be in (0, 1)")
        if self.max_open_orders < 1:
            raise ValueError("max open orders must be positive")
        if not Decimal("0") <= self.min_liquidation_buffer_fraction <= Decimal("1"):
            raise ValueError("liquidation buffer fraction must be in [0, 1]")

    def snapshot(self) -> dict[str, str | int | tuple[str, ...]]:
        return {
            "allowed_instruments": tuple(
                sorted(f"{item.venue}:{item.product_type.value}:{item.symbol}" for item in self.allowed_instruments)
            ),
            "max_signal_age_seconds": str(self.max_signal_age.total_seconds()),
            "max_state_age_seconds": str(self.max_state_age.total_seconds()),
            "max_market_data_age_seconds": str(self.max_market_data_age.total_seconds()),
            "max_order_notional": str(self.max_order_notional),
            "max_instrument_exposure": str(self.max_instrument_exposure),
            "max_total_exposure": str(self.max_total_exposure),
            "max_leverage": str(self.max_leverage),
            "max_drawdown_fraction": str(self.max_drawdown_fraction),
            "max_open_orders": self.max_open_orders,
            "min_liquidation_buffer_fraction": str(self.min_liquidation_buffer_fraction),
        }


def evaluate_policies(request, state: RiskState, limits: RiskLimits, now: datetime) -> tuple[str, ...]:
    """Return every violation in stable safety-precedence order."""
    signal = request.signal
    reasons: list[str] = []
    if state.kill_switch_active:
        reasons.append("kill switch is active")
    if signal.environment is not state.environment:
        reasons.append("signal and risk state environments differ")
    if state.as_of > now:
        reasons.append("risk state timestamp is in the future")
    elif now - state.as_of > limits.max_state_age:
        reasons.append("risk state is stale")
    if signal.signal_id in state.seen_signal_ids:
        reasons.append("signal has already been evaluated")
    if signal.action is SignalAction.ABSTAIN:
        reasons.append("abstain signals cannot be traded")
    if signal.decision_at > now:
        reasons.append("signal decision time is in the future")
    else:
        if now - signal.decision_at > limits.max_signal_age:
            reasons.append("signal is stale")
        if now >= signal.expires_at:
            reasons.append("signal has expired")
    if signal.instrument not in limits.allowed_instruments:
        reasons.append("instrument is not allowed")
    market_time = state.market_data_as_of.get(signal.instrument)
    if market_time is None:
        reasons.append("market data timestamp is missing")
    elif market_time > now:
        reasons.append("market data timestamp is in the future")
    elif now - market_time > limits.max_market_data_age:
        reasons.append("market data is stale")
    if state.open_order_count >= limits.max_open_orders:
        reasons.append("open order limit reached")
    drawdown = (state.peak_equity - state.equity) / state.peak_equity
    if drawdown >= limits.max_drawdown_fraction:
        reasons.append("drawdown limit reached")

    notional = request.quantity * request.reference_price
    if notional > limits.max_order_notional:
        reasons.append("order notional limit exceeded")
    instrument_exposure = state.instrument_exposures.get(signal.instrument, Decimal("0")) + notional
    if instrument_exposure > limits.max_instrument_exposure:
        reasons.append("instrument exposure limit exceeded")
    proposed_total = state.total_abs_exposure + notional
    if proposed_total > limits.max_total_exposure:
        reasons.append("total exposure limit exceeded")
    if request.requested_leverage > limits.max_leverage:
        reasons.append("requested leverage limit exceeded")
    if proposed_total / state.equity > limits.max_leverage:
        reasons.append("portfolio leverage limit exceeded")

    is_perpetual = signal.instrument.product_type in {
        ProductType.LINEAR_PERPETUAL,
        ProductType.INVERSE_PERPETUAL,
    }
    if is_perpetual and request.requested_leverage > Decimal("1"):
        if request.liquidation_buffer_fraction is None:
            reasons.append("liquidation buffer is missing")
        elif request.liquidation_buffer_fraction < limits.min_liquidation_buffer_fraction:
            reasons.append("liquidation buffer is below minimum")
    return tuple(reasons)
