"""Reinforcement learning, reduced to what the problem actually is.

A fixed-stake binary option does not change the market state, so the decision problem is a
contextual bandit: context -> one of {abstain, up/down x expiry}. DQN/PPO/A2C on this problem
learn the same Q(context, arm) with more variance; the MDP part only appears in bankroll
(staking) decisions, handled in risk.py.

Two offline policies are learned on train rows and scored on test rows:
- greedy: pick the arm with the highest mean train reward if it is > 0 (what an unconstrained
  RL agent converges to; it exploits noise in the training sample),
- pessimistic LCB: pick an arm only if mean - z * se > 0 (offline-RL pessimism).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import DOWN, TIE, UP
from .metrics import PRIMARY_PAYOUT
from .walkforward import non_overlapping


def arm_rewards(frame: pd.DataFrame, rows: np.ndarray, horizons: tuple[int, ...],
                payout: float = PRIMARY_PAYOUT) -> np.ndarray:
    """(n, 2H) reward matrix: columns up_h1, down_h1, up_h2, ...; NaN where label unknown."""
    cols = []
    for h in horizons:
        y = frame[f"y{h}"].to_numpy()[rows]
        up = np.where(y == UP, payout, np.where(y == DOWN, -1.0, np.where(y == TIE, 0.0, np.nan)))
        down = np.where(y == DOWN, payout, np.where(y == UP, -1.0, np.where(y == TIE, 0.0, np.nan)))
        cols += [up, down]
    return np.stack(cols, axis=1)


def learn(contexts: np.ndarray, rewards: np.ndarray, n_contexts: int, mode: str, min_n: int = 200) -> np.ndarray:
    """Arm per context (-1 = abstain).

    The LCB z is Bonferroni-adjusted over every (context, arm) cell: with 64 contexts x 6 arms an
    unadjusted 1.645 admits noise cells even when every arm has negative expectancy.
    """
    from scipy import stats

    z = stats.norm.ppf(1 - 0.05 / (n_contexts * rewards.shape[1]))
    choice = np.full(n_contexts, -1)
    for c in range(n_contexts):
        r = rewards[contexts == c]
        if len(r) < min_n:
            continue
        n = np.isfinite(r).sum(0)
        mean = np.nanmean(r, axis=0)
        se = np.nanstd(r, axis=0) / np.sqrt(np.maximum(n, 1))
        score = mean if mode == "greedy" else mean - z * se
        score = np.where(np.isfinite(score), score, -np.inf)
        best = int(np.argmax(score))
        if score[best] > 0 and n[best] >= min_n:
            choice[c] = best
    return choice


def act(frame: pd.DataFrame, rows: np.ndarray, contexts: np.ndarray, choice: np.ndarray,
        horizons: tuple[int, ...], tf: int, payout: float = PRIMARY_PAYOUT) -> pd.DataFrame:
    arm = choice[contexts]
    take = arm >= 0
    rows, arm = rows[take], arm[take]
    h = np.array(horizons)[arm // 2]
    up = arm % 2 == 0
    y = np.stack([frame[f"y{hz}"].to_numpy()[rows] for hz in horizons], axis=1)[np.arange(len(rows)), arm // 2]
    known = y != -2
    rows, h, up, y = rows[known], h[known], up[known], y[known]
    asset = frame.asset.to_numpy()[rows]
    t = frame.t.to_numpy()[rows]
    keep = np.zeros(len(rows), dtype=bool)
    for hz in np.unique(h):  # per-expiry non-overlap; different expiries may overlap
        m = h == hz
        keep[np.flatnonzero(m)[non_overlapping(asset[m], t[m], int(hz) * tf)]] = True
    outcome = np.where(y == TIE, -1, np.where((y == UP) == up, 1, 0))[keep]
    return pd.DataFrame({"row": rows[keep], "asset": asset[keep], "t": t[keep],
                         "day": frame.day.to_numpy()[rows][keep], "horizon": h[keep],
                         "up": up[keep], "outcome": outcome.astype(np.int8),
                         "hour": frame.hour.to_numpy()[rows][keep]}).sort_values("t").reset_index(drop=True)
