"""Forward labels from live 1-second candles and the payout in force at entry.

entry price = close of the latest 1-s candle starting at or before decision + 2 s (at most 2 s old)
exit price  = close of the latest 1-s candle starting at or before entry + expiry (at most 2 s old)
A trade with a missing price or payout is UNLABELED and excluded; exclusions are counted, never
imputed. Exclusion depends only on data availability, never on the outcome.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import spec

PRICE_TOLERANCE_MS = 2_000
WIN, LOSS, TIE = 1, 0, -1


def _asof(events: pd.DataFrame, table: pd.DataFrame, at: str, value: str, tol: int, by: list[str]) -> pd.Series:
    if table.empty:
        return pd.Series(np.nan, index=events.index, dtype=float)
    left = events[[at, *by]].reset_index().sort_values(at)
    left[at] = left[at].astype(np.int64)
    right = table.sort_values("time_ms")
    j = pd.merge_asof(left, right, left_on=at, right_on="time_ms", by=by, direction="backward", tolerance=tol)
    return j.set_index("index")[value].reindex(events.index)


def label(events: pd.DataFrame, candles1s: pd.DataFrame, payouts: pd.DataFrame) -> pd.DataFrame:
    """events: trigger rows. candles1s: asset, candle_start_ms, close. payouts: asset, instrument_type,
    received_at_ms, payout_fraction. Returns events plus entry, exit, payout, outcome, label_status."""
    ev = events.copy().reset_index(drop=True)
    if ev.empty:
        return ev.assign(entry=[], exit=[], payout=[], outcome=[], label_status=[])
    from .triggers import clean_payouts
    payouts = clean_payouts(payouts)
    candles1s = candles1s.assign(candle_start_ms=candles1s.candle_start_ms.astype(np.int64),
                                 close=candles1s.close.astype(float))
    ev["entry_ms"] = ev.decision_ms.astype(np.int64) + spec.ENTRY_DELAY_MS
    ev["expiry_ms"] = ev.entry_ms + ev.expiry_s.astype(np.int64) * 1000
    px = candles1s.rename(columns={"candle_start_ms": "time_ms"})[["asset", "time_ms", "close"]]
    ev["entry"] = _asof(ev, px, "entry_ms", "close", PRICE_TOLERANCE_MS, ["asset"])
    ev["exit"] = _asof(ev, px, "expiry_ms", "close", PRICE_TOLERANCE_MS, ["asset"])
    po = payouts.rename(columns={"received_at_ms": "time_ms"})
    po = po.assign(instrument=po.instrument_type.str.replace("-option", "", regex=False))
    ev["instrument"] = ev["product"]
    ev["payout"] = _asof(ev, po[["asset", "instrument", "time_ms", "payout_fraction"]], "entry_ms",
                         "payout_fraction", spec.MAX_PAYOUT_AGE_MS, ["asset", "instrument"])
    move = ev.side * (ev.exit - ev.entry)
    ev["outcome"] = np.where(move > 0, WIN, np.where(move < 0, LOSS, TIE))
    status = np.where(ev.entry.isna(), "missing_entry_price",
                      np.where(ev.exit.isna(), "missing_exit_price",
                               np.where(ev.payout.isna(), "missing_payout", "labeled")))
    ev["label_status"] = status
    ev.loc[ev.label_status != "labeled", "outcome"] = np.nan
    return ev.drop(columns=["instrument"])
