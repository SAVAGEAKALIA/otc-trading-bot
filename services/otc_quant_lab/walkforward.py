"""Chronological splits, payout-aware abstention policy, and overfitting statistics.

Split recipe (identical for every model):
  train days -> gap 2 days -> inner days (7) -> gap 2 days -> test days
The gap is 1 day of purge (> max label horizon + feature lookback = 2 h 10 m) plus 1 day embargo.
The model is fit on train. Inner-day predictions (out of sample for that model) fit the Platt
recalibration and the confidence thresholds. Test days are scored once.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

from .features import DOWN, TIE, UP
from .metrics import PRIMARY_PAYOUT, breakeven, unit_returns, wilson_lower_one_sided

INNER_DAYS = 7
GAP_DAYS = 2  # purge + embargo
COVERAGES = (1.0, 0.5, 0.2, 0.1, 0.05, 0.02)


@dataclass(frozen=True)
class Split:
    name: str
    train: tuple[int, int]  # [start, end) in UTC day numbers
    inner: tuple[int, int]
    test: tuple[int, int]


def lab_splits(days: np.ndarray, dev_fraction: float = 0.75, folds: int = 4) -> tuple[list[Split], Split]:
    first, last = int(days.min()), int(days.max()) + 1
    dev_end = first + int((last - first) * dev_fraction)
    final_start = dev_end + GAP_DAYS
    window_start = first + int((dev_end - first) * 0.40)
    edges = np.linspace(window_start, dev_end, folds + 1).astype(int)
    splits = []
    for k in range(folds):
        test = (int(edges[k]), int(edges[k + 1]))
        inner = (test[0] - GAP_DAYS - INNER_DAYS, test[0] - GAP_DAYS)
        splits.append(Split(f"fold{k}", (first, inner[0] - GAP_DAYS), inner, test))
    inner = (dev_end - INNER_DAYS, dev_end)
    final = Split("final", (first, inner[0] - GAP_DAYS), inner, (final_start, last))
    return splits, final


def in_days(day: np.ndarray, span: tuple[int, int]) -> np.ndarray:
    return (day >= span[0]) & (day < span[1])


def platt(p_inner: np.ndarray, y_inner: np.ndarray):
    """Return a function mapping raw p_up to recalibrated p_up (fit on inner rows only)."""
    from sklearn.linear_model import LogisticRegression

    def logit(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p)).reshape(-1, 1)

    x = logit(p_inner)
    if len(np.unique(y_inner)) < 2 or np.std(x) < 1e-9:
        return lambda p: np.asarray(p, dtype=np.float64)
    model = LogisticRegression(C=1e4).fit(x, y_inner)
    return lambda p: model.predict_proba(logit(p))[:, 1]


def non_overlapping(asset: np.ndarray, t: np.ndarray, hold_seconds: int) -> np.ndarray:
    """Greedy chronological filter: one open position per asset at a time."""
    order = np.lexsort((t, asset))
    keep = np.zeros(len(t), dtype=bool)
    last_asset, free_at = None, -np.inf
    for i in order:
        if asset[i] != last_asset:
            last_asset, free_at = asset[i], -np.inf
        if t[i] >= free_at:
            keep[i] = True
            free_at = t[i] + hold_seconds
    return keep


def trades(frame: pd.DataFrame, rows: np.ndarray, p_up: np.ndarray, threshold: float,
           horizon: int, tf: int) -> pd.DataFrame:
    """Trades for one policy on `rows` (positions into frame). Unknown labels are excluded."""
    conf = np.maximum(p_up, 1 - p_up)
    label = frame[f"y{horizon}"].to_numpy()[rows]
    chosen = (conf >= threshold) & (label != -2)
    sub_rows = rows[chosen]
    side_up = p_up[chosen] >= 0.5
    asset = frame.asset.to_numpy()[sub_rows]
    t = frame.t.to_numpy()[sub_rows]
    keep = non_overlapping(asset, t, horizon * tf)
    sub_rows, side_up, label = sub_rows[keep], side_up[keep], label[chosen][keep]
    outcome = np.where(label == TIE, -1, np.where((label == UP) == side_up, 1, 0)).astype(np.int8)
    out = pd.DataFrame({"row": sub_rows, "asset": asset[keep], "t": t[keep],
                        "day": frame.day.to_numpy()[sub_rows], "up": side_up, "outcome": outcome,
                        "hour": frame.hour.to_numpy()[sub_rows]})
    return out.sort_values(["t", "asset"]).reset_index(drop=True)


def thresholds(p_inner: np.ndarray) -> dict[float, float]:
    conf = np.maximum(p_inner, 1 - p_inner)
    return {q: (0.0 if q >= 1.0 else float(np.quantile(conf, 1 - q))) for q in COVERAGES}


def selection_score(outcome: np.ndarray, payout: float = PRIMARY_PAYOUT, min_trades: int = 500) -> float:
    """Development selection metric: one-sided 95% Wilson lower bound minus break-even."""
    wins = int((outcome == 1).sum())
    n = wins + int((outcome == 0).sum())
    if n < min_trades:
        return -np.inf
    return wilson_lower_one_sided(wins, n, 0.05) - breakeven(payout)


def pbo_cscv(block_returns: np.ndarray, blocks_per_half: int | None = None, max_combos: int = 4000,
             seed: int = 11) -> dict:
    """Probability of Backtest Overfitting (Bailey, Borwein, Lopez de Prado, Zhu 2017).

    block_returns: (S blocks, N configs) mean return per block. For each split of the S blocks
    into equal IS/OS halves, take the IS-best config and its relative OS rank w in (0,1);
    PBO = P(logit(w) <= 0).
    """
    s, n = block_returns.shape
    half = blocks_per_half or s // 2
    combos = list(combinations(range(s), half))
    rng = np.random.default_rng(seed)
    if len(combos) > max_combos:
        combos = [combos[i] for i in rng.choice(len(combos), max_combos, replace=False)]
    logits, degradation = [], []
    for is_blocks in combos:
        mask = np.zeros(s, dtype=bool)
        mask[list(is_blocks)] = True
        is_perf = block_returns[mask].mean(axis=0)
        os_perf = block_returns[~mask].mean(axis=0)
        best = int(np.argmax(is_perf))
        rank = (os_perf < os_perf[best]).sum() + 0.5 * ((os_perf == os_perf[best]).sum() - 1) + 1
        w = rank / (n + 1)
        logits.append(np.log(w / (1 - w)))
        degradation.append((is_perf[best], os_perf[best]))
    logits = np.array(logits)
    deg = np.array(degradation)
    return {"pbo": float((logits <= 0).mean()), "combos": len(combos), "configs": n, "blocks": s,
            "median_is_best": float(np.median(deg[:, 0])), "median_os_of_is_best": float(np.median(deg[:, 1])),
            "prob_os_loss_of_is_best": float((deg[:, 1] < 0).mean())}


def block_matrix(trade_sets: dict[str, pd.DataFrame], day_edges: np.ndarray,
                 payout: float = PRIMARY_PAYOUT) -> tuple[np.ndarray, list[str]]:
    """(blocks, configs) mean unit return per contiguous day block; empty blocks get 0."""
    names = sorted(trade_sets)
    out = np.zeros((len(day_edges) - 1, len(names)))
    for j, name in enumerate(names):
        tr = trade_sets[name]
        ret = unit_returns(tr.outcome.to_numpy(), payout)
        block = np.searchsorted(day_edges, tr.day.to_numpy(), side="right") - 1
        for b in range(len(day_edges) - 1):
            hit = block == b
            out[b, j] = ret[hit].mean() if hit.any() else 0.0
    return out, names


__all__ = ["Split", "lab_splits", "in_days", "platt", "non_overlapping", "trades", "thresholds",
           "selection_score", "pbo_cscv", "block_matrix", "COVERAGES", "DOWN", "UP"]
