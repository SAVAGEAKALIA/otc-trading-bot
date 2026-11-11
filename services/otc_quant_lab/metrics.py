"""Binary-option trade statistics. Deterministic; unit tested."""
from __future__ import annotations

import numpy as np
from scipy import stats

PRIMARY_PAYOUT = 0.84  # median observed turbo-option payout in payout_samples (Jul 31 - Aug 20 2026)
PAYOUTS = (0.80, 0.84, 0.87)


def breakeven(payout: float) -> float:
    return 1.0 / (1.0 + payout)


def wilson(wins: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided Wilson interval at `confidence`."""
    if n == 0:
        return (float("nan"), float("nan"))
    z = stats.norm.ppf(1 - (1 - confidence) / 2)
    phat = wins / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * np.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def wilson_lower_one_sided(wins: int, n: int, alpha: float) -> float:
    """One-sided lower bound with level alpha (e.g. 0.05 / K for Bonferroni)."""
    return wilson(wins, n, 1 - 2 * alpha)[0]


def unit_returns(outcome: np.ndarray, payout: float) -> np.ndarray:
    """outcome: 1 win, 0 loss, -1 tie (refund)."""
    return np.where(outcome == 1, payout, np.where(outcome == 0, -1.0, 0.0))


def day_block_bootstrap(values: np.ndarray, days: np.ndarray, reps: int = 2000,
                        seed: int = 7) -> tuple[float, float]:
    """95% CI of the mean, resampling whole UTC days (keeps intraday and cross-asset dependence)."""
    if len(values) == 0:
        return (float("nan"), float("nan"))
    unique, inverse = np.unique(days, return_inverse=True)
    sums = np.bincount(inverse, weights=values)
    counts = np.bincount(inverse)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(unique), size=(reps, len(unique)))
    means = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    return (float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)))


def max_consecutive_losses(outcome: np.ndarray) -> int:
    best = current = 0
    for value in outcome:
        if value == 0:
            current += 1
            best = max(best, current)
        elif value == 1:
            current = 0
    return best


def max_drawdown(returns: np.ndarray) -> float:
    """Largest peak-to-trough drop of the cumulative unit-stake equity curve, in stakes."""
    if len(returns) == 0:
        return 0.0
    equity = np.concatenate([[0.0], np.cumsum(returns)])
    return float(np.max(np.maximum.accumulate(equity) - equity))


def auc(y: np.ndarray, p: np.ndarray) -> float:
    positives = y == 1
    n1, n0 = positives.sum(), (~positives).sum()
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = stats.rankdata(p)
    return float((ranks[positives].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def calibration_slope(y: np.ndarray, p: np.ndarray) -> float:
    """Slope of logistic recalibration of logit(p). 1 = calibrated; <1 overconfident."""
    from sklearn.linear_model import LogisticRegression

    if len(np.unique(y)) < 2:
        return float("nan")
    x = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1)).reshape(-1, 1)
    if np.std(x) < 1e-9:
        return float("nan")
    model = LogisticRegression(C=1e6).fit(x, y)
    return float(model.coef_[0, 0])


def traded_calibration(p_up: np.ndarray, side_up: np.ndarray, outcome: np.ndarray) -> dict:
    """Brier and calibration slope of the probability of the side actually traded (rubric P7)."""
    decided = outcome >= 0
    p_win = np.where(side_up, p_up, 1 - p_up)[decided]
    win = (outcome[decided] == 1).astype(int)
    if len(win) < 50:
        return {"n": int(len(win)), "brier": None, "slope": None}
    return {"n": int(len(win)), "brier": brier(win, p_win), "slope": calibration_slope(win, p_win),
            "mean_p_win": float(p_win.mean()), "win_rate": float(win.mean())}


def trade_summary(outcome: np.ndarray, days: np.ndarray, payout: float = PRIMARY_PAYOUT,
                  trials: int = 1) -> dict:
    """Everything the rubric asks for on one trade list (chronological order assumed)."""
    outcome = np.asarray(outcome)
    decided = outcome >= 0
    wins = int((outcome == 1).sum())
    losses = int((outcome == 0).sum())
    n = wins + losses
    returns = {f"{p:.2f}": unit_returns(outcome, p) for p in PAYOUTS}
    primary = unit_returns(outcome, payout)
    lo, hi = wilson(wins, n)
    unique_days = np.unique(days) if len(days) else np.array([])
    day_thirds = np.array_split(unique_days, 3)  # calendar thirds (rubric P4), not trade-count thirds
    thirds = [np.flatnonzero(np.isin(days, part)) for part in day_thirds] if len(days) else [[], [], []]
    return {
        "trades": int(len(outcome)),
        "wins": wins,
        "losses": losses,
        "ties": int((~decided).sum()),
        "days": int(len(np.unique(days))) if len(days) else 0,
        "win_rate": wins / n if n else None,
        "wilson95": [lo, hi],
        "wilson_lower_bonferroni": wilson_lower_one_sided(wins, n, 0.05 / max(trials, 1)) if n else None,
        "breakeven_primary": breakeven(payout),
        "mean_return": {k: float(v.mean()) if len(v) else None for k, v in returns.items()},
        "mean_return_day_bootstrap95": list(day_block_bootstrap(primary, days)),
        "thirds_mean_return": [float(primary[ix].mean()) if len(ix) else None for ix in thirds],
        "max_consecutive_losses": max_consecutive_losses(outcome),
        "max_drawdown_stakes": max_drawdown(primary),
    }
