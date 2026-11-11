"""Online / adaptive learning and the adaptive model-selection engine.

- prequential_sgd: logistic model updated once per UTC day; day d is predicted only with data
  through day d-1. Page-Hinkley on its trade returns suspends trading after a detected decline.
- adaptive_selection: each day, trade with the model/coverage whose trailing-window return (from
  already-settled earlier days only) is best, or abstain if none is positive.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import PRIMARY_PAYOUT, unit_returns


class PageHinkley:
    """Detects a downward shift in the mean of a return stream."""

    def __init__(self, delta: float = 0.005, threshold: float = 15.0):
        self.delta, self.threshold = delta, threshold
        self.mean = self.cum = self.min_cum = 0.0
        self.n = 0

    def update(self, value: float) -> bool:
        self.n += 1
        self.mean += (value - self.mean) / self.n
        self.cum += self.mean - value - self.delta
        self.min_cum = min(self.min_cum, self.cum)
        return self.cum - self.min_cum > self.threshold


def prequential_sgd(x: np.ndarray, y: np.ndarray, day: np.ndarray, start_day: int,
                    seed: int = 20261109) -> np.ndarray:
    """p_up for rows with day >= start_day, each predicted by a model trained on earlier days."""
    from sklearn.linear_model import SGDClassifier

    x = np.clip(np.nan_to_num(x.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0), -50, 150)
    warm = day < start_day
    mu, sd = x[warm].mean(0), x[warm].std(0) + 1e-6
    x = np.clip((x - mu) / sd, -8, 8)
    model = SGDClassifier(loss="log_loss", alpha=1e-4, learning_rate="constant", eta0=1e-3, random_state=seed)
    known = y >= 0
    model.partial_fit(x[warm & known], y[warm & known], classes=[0, 1])
    out = np.full(len(y), np.nan)
    for d in np.unique(day[~warm]):
        today = day == d
        out[today] = model.predict_proba(x[today])[:, 1]
        if (today & known).any():
            model.partial_fit(x[today & known], y[today & known])
    return out


def causal_thresholds(p_up: np.ndarray, day: np.ndarray, coverage: float, window: int = 7) -> np.ndarray:
    """Per-row confidence threshold from predictions of the previous `window` days only."""
    conf = np.maximum(p_up, 1 - p_up)
    out = np.full(len(p_up), np.inf)
    if coverage >= 1:
        return np.zeros(len(p_up))
    for d in np.unique(day):
        past = (day < d) & (day >= d - window) & np.isfinite(conf)
        if past.sum() >= 1000:
            out[day == d] = np.quantile(conf[past], 1 - coverage)
    return out


def suspend_with_page_hinkley(trades: pd.DataFrame, payout: float = PRIMARY_PAYOUT) -> pd.DataFrame:
    """Drop every trade after the detector fires (it re-arms at the next UTC day boundary)."""
    detector = PageHinkley()
    keep, suspended_day = [], None
    for day, outcome in zip(trades.day.to_numpy(), trades.outcome.to_numpy()):
        if suspended_day is not None and day == suspended_day:
            keep.append(False)
            continue
        if suspended_day is not None and day != suspended_day:
            suspended_day, detector = None, PageHinkley()
        keep.append(True)
        if detector.update(float(unit_returns(np.array([outcome]), payout)[0])):
            suspended_day = day
    return trades[np.array(keep, dtype=bool)] if len(trades) else trades


def adaptive_selection(candidates: dict[str, pd.DataFrame], days: np.ndarray, window: int = 7,
                       payout: float = PRIMARY_PAYOUT, min_trades: int = 100) -> tuple[pd.DataFrame, list]:
    """Daily switch to the candidate with the best trailing-window mean return (strictly past days)."""
    daily = {}
    for name, tr in candidates.items():
        r = unit_returns(tr.outcome.to_numpy(), payout)
        daily[name] = pd.DataFrame({"day": tr.day.to_numpy(), "r": r}).groupby("day").r.agg(["sum", "count"])
    chosen, log = [], []
    for d in days:
        best, best_mean = None, 0.0
        for name, table in daily.items():
            past = table[(table.index < d) & (table.index >= d - window)]
            n = past["count"].sum()
            if n >= min_trades and past["sum"].sum() / n > best_mean:
                best, best_mean = name, past["sum"].sum() / n
        log.append({"day": int(d), "model": best, "trailing_mean": best_mean if best else None})
        if best is not None:
            tr = candidates[best]
            chosen.append(tr[tr.day == d])
    out = pd.concat(chosen, ignore_index=True) if chosen else pd.DataFrame(columns=["day", "outcome"])
    return out.sort_values("t").reset_index(drop=True) if len(out) else out, log
