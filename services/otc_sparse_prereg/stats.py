"""Exact binomial certificate maths. Deterministic; seeds are explicit."""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from services.otc_quant_lab.risk import trades_needed

from . import spec


def cp_lower(wins: int, n: int, alpha: float = spec.ALPHA) -> float:
    """One-sided Clopper-Pearson lower bound at level 1 - alpha."""
    if n <= 0 or wins <= 0:
        return 0.0
    return float(stats.beta.ppf(alpha, wins, n - wins + 1))


def cp_upper(wins: int, n: int, alpha: float = spec.ALPHA) -> float:
    if n <= 0:
        return 1.0
    if wins >= n:
        return 1.0
    return float(stats.beta.ppf(1 - alpha, wins + 1, n - wins))


def min_wins_to_certify(n: int, breakeven: float, alpha: float = spec.ALPHA) -> int | None:
    """Smallest win count whose one-sided CP lower bound exceeds break-even (binary search)."""
    lo, hi = 0, n
    if cp_lower(n, n, alpha) <= breakeven:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if cp_lower(mid, n, alpha) > breakeven:
            hi = mid
        else:
            lo = mid + 1
    return lo


def n_target(product: str, edge: float = spec.PLANNING_EDGE) -> int:
    """Registered sample size: owner's engine, family of 8, power 0.8, design effect 1.5.

    Rounded down to match the published sample-size table (1,648 turbo / 1,653 binary at +5 pt).
    """
    payout = spec.TURBO_PAYOUT_NOMINAL if product == "turbo" else spec.BINARY_PAYOUT_NOMINAL
    raw = trades_needed(edge, spec.breakeven(payout), alpha=spec.ALPHA) * spec.DESIGN_EFFECT
    return int(math.floor(raw))


def day_block_bootstrap_mean(returns: np.ndarray, days: np.ndarray, reps: int = 2000,
                             seed: int = 20261113) -> tuple[float, float]:
    """Mean return per stake and its one-sided lower (alpha) bootstrap bound, resampling whole days."""
    returns = np.asarray(returns, dtype=float)
    days = np.asarray(days)
    if len(returns) == 0:
        return 0.0, 0.0
    unique = np.unique(days)
    sums = np.array([returns[days == d].sum() for d in unique])
    counts = np.array([(days == d).sum() for d in unique])
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(unique), size=(reps, len(unique)))
    means = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    return float(returns.mean()), float(np.quantile(means, spec.ALPHA))
