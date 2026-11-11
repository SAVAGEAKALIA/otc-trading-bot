"""Capital and losing-streak analysis. No martingale or recovery staking, by design."""
from __future__ import annotations

import numpy as np

from .metrics import PRIMARY_PAYOUT


def kelly_fraction(win_rate: float, payout: float = PRIMARY_PAYOUT) -> float:
    """Kelly stake for a binary bet: f* = (p*b - q) / b. Negative means do not bet."""
    return (win_rate * payout - (1 - win_rate)) / payout


def prob_losing_streak(win_rate: float, streak: int, trades: int) -> float:
    """P(at least one run of `streak` consecutive losses in `trades` iid trades), exact DP."""
    q = 1 - win_rate
    state = np.zeros(streak)
    state[0] = 1.0
    hit = 0.0
    for _ in range(trades):
        new = np.zeros(streak)
        new[0] = state.sum() * win_rate
        new[1:] = state[:-1] * q
        hit += state[-1] * q
        state = new
    return float(hit)


def survival(win_rate: float, trades: int, bankroll: float, stake_rule: str, payout: float = PRIMARY_PAYOUT,
             fraction: float = 0.02, min_stake: float = 1.0, daily_trades: int = 20,
             daily_loss_limit: float = 0.10, reps: int = 4000, seed: int = 3) -> dict:
    """Monte Carlo of a bankroll under fixed or percentage staking with a daily loss stop.

    Ruin = bankroll below the broker minimum stake. Returns ruin probability and final quantiles.
    """
    rng = np.random.default_rng(seed)
    wins = rng.random((reps, trades)) < win_rate
    bank = np.full(reps, bankroll, dtype=float)
    ruined = np.zeros(reps, dtype=bool)
    day_start = bank.copy()
    for i in range(trades):
        if i % daily_trades == 0:
            day_start = bank.copy()
        stake = np.full(reps, min_stake) if stake_rule == "fixed" else np.maximum(min_stake, bank * fraction)
        stopped = (day_start - bank) >= daily_loss_limit * day_start
        active = ~ruined & ~stopped & (bank >= stake)
        bank = np.where(active, bank + np.where(wins[:, i], stake * payout, -stake), bank)
        ruined |= bank < min_stake
    return {"win_rate": win_rate, "trades": trades, "bankroll": bankroll, "rule": stake_rule,
            "ruin_probability": float(ruined.mean()), "median_final": float(np.median(bank)),
            "p05_final": float(np.quantile(bank, 0.05)), "p95_final": float(np.quantile(bank, 0.95)),
            "prob_end_below_start": float((bank < bankroll).mean())}


def trades_needed(edge_over_breakeven: float, breakeven_rate: float, alpha: float = 0.05,
                  power: float = 0.8) -> int:
    """One-sided binomial sample size to detect win rate = breakeven + edge."""
    from scipy import stats

    p1 = breakeven_rate + edge_over_breakeven
    za, zb = stats.norm.ppf(1 - alpha), stats.norm.ppf(power)
    n = ((za * np.sqrt(breakeven_rate * (1 - breakeven_rate)) + zb * np.sqrt(p1 * (1 - p1))) / edge_over_breakeven) ** 2
    return int(np.ceil(n))
