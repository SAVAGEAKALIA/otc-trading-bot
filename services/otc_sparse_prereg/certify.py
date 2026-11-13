"""The certificate. One look per hypothesis: at its first n_target labeled trades, or when its max_days
horizon has fully elapsed, whichever comes first. run.py seals every look in a write-once file, so a
hypothesis is scored exactly once. Futility may be checked at any time; it can only stop a hypothesis
(and is sealed too), never certify one. Before its look a hypothesis reports counts only.

States:
  PENDING           look not reached; counts only
  CERTIFIED         every certificate condition holds (tradable rows only)
  FEED-PROPERTY     every condition holds on a non-tradable row (H7): a no-trade filter, never an entry
  NULL-INFORMATIVE  not certified and the planning edge is excluded: cp_upper < break-even + 5 pt
  UNDERPOWERED      not certified and the planning edge is not excluded
  FUTILE            stopped early: running upper bound below break-even
  NOT-OPENED        nested row whose parent did not certify
  GATE-FAILED       G2/G3 evals did not pass, so no state is reported
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy import stats as sps

from . import spec, stats

FUTILITY_MIN_N = 100
PLACEBO_REQUIRED = 1000
CONTROL_MIN_N = 200        # a control smaller than this cannot clear H1
PLACEBO_MIN_TRADES = 30    # an emptier placebo lattice is scored as a perfect placebo (fails closed)
EMPTY = pd.DataFrame(columns=["decision_ms", "asset", "label_status", "outcome", "payout"])


@dataclass
class Result:
    hid: str
    state: str
    n_events: int
    n_labeled: int
    n_target: int
    look_reached: bool
    sample_end_ms: int | None = None
    wins: int | None = None
    n_nontie: int | None = None
    win_rate: float | None = None
    breakeven: float | None = None
    cp_lower: float | None = None
    cp_upper: float | None = None
    cp_lower_tie_as_loss: float | None = None
    mean_return: float | None = None
    mean_return_lower: float | None = None
    mean_return_lower_tie_as_loss: float | None = None
    thirds_positive: bool | None = None
    thirds_positive_tie_as_loss: bool | None = None
    extra: dict | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def returns(df: pd.DataFrame, tie_as_loss: bool) -> np.ndarray:
    out = np.where(df.outcome == 1, df.payout.astype(float), -1.0)
    return np.where(df.outcome == -1, -1.0 if tie_as_loss else 0.0, out).astype(float)


def breakeven(df: pd.DataFrame) -> float:
    """Zero-EV win rate at the sample's mean payout."""
    return 1.0 / (1.0 + float(df.payout.astype(float).mean())) if len(df) else 1.0


def score(df: pd.DataFrame) -> dict:
    """Certificate statistics on labeled trades (outcome 1 win, 0 loss, -1 tie), in decision order."""
    nontie = df[df.outcome != -1]
    wins, n = int((nontie.outcome == 1).sum()), len(nontie)
    days = df.decision_ms.to_numpy(np.int64) // spec.DAY_MS
    out = {"wins": wins, "n_nontie": n, "win_rate": wins / n if n else 0.0, "breakeven": breakeven(df),
           "cp_lower": stats.cp_lower(wins, n), "cp_upper": stats.cp_upper(wins, n),
           "cp_lower_tie_as_loss": stats.cp_lower(wins, len(df))}
    for suffix, tie_loss in (("", False), ("_tie_as_loss", True)):
        ret = returns(df, tie_loss)
        mean, lower = stats.day_block_bootstrap_mean(ret, days)
        thirds = np.array_split(np.arange(len(df)), 3) if len(df) >= 3 else []
        if suffix == "":
            out["mean_return"] = mean
        out[f"mean_return_lower{suffix}"] = lower
        out[f"thirds_positive{suffix}"] = bool(len(thirds) == 3 and all(ret[i].mean() > 0 for i in thirds))
    return out


def passes(s: dict) -> bool:
    be = s["breakeven"]
    return bool(s["cp_lower"] > be and s["cp_lower_tie_as_loss"] > be
                and s["mean_return_lower"] > 0 and s["mean_return_lower_tie_as_loss"] > 0
                and s["thirds_positive"] and s["thirds_positive_tie_as_loss"])


def control_beaten(sample: pd.DataFrame, control: pd.DataFrame) -> tuple[bool, float]:
    """H1 must beat the matched mood-only fade: one-sided two-proportion z test at 0.05."""
    a, b = sample[sample.outcome != -1], control[control.outcome != -1]
    if len(a) == 0 or len(b) < CONTROL_MIN_N:
        return False, 1.0
    p1, p2 = (a.outcome == 1).mean(), (b.outcome == 1).mean()
    pooled = ((a.outcome == 1).sum() + (b.outcome == 1).sum()) / (len(a) + len(b))
    se = np.sqrt(pooled * (1 - pooled) * (1 / len(a) + 1 / len(b)))
    p = float(1 - sps.norm.cdf((p1 - p2) / se)) if se > 0 else 1.0
    return p < 0.05, p


def _window(df: pd.DataFrame | None, end_ms: int, start_ms: int = spec.FORWARD_START_MS) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return EMPTY
    return df[(df.decision_ms >= start_ms) & (df.decision_ms <= end_ms)
              & (df.label_status == "labeled")]


def evaluate(hid: str, labeled: pd.DataFrame | None, now_ms: int, extras: dict | None = None,
             start_ms: int = spec.FORWARD_START_MS, horizon_end_ms: int | None = None) -> Result:
    """labeled: this hypothesis's trades with label_status and outcome. now_ms: data cut-off.
    start_ms / horizon_end_ms default to the registered forward block; the historical test passes its own."""
    h = spec.BY_ID[hid]
    labeled = EMPTY if labeled is None or len(labeled) == 0 else labeled
    horizon_end = horizon_end_ms if horizon_end_ms is not None else spec.FORWARD_START_MS + h.max_days * spec.DAY_MS
    ev = labeled[(labeled.decision_ms >= start_ms) & (labeled.decision_ms < horizon_end)]
    ev = ev.sort_values(["decision_ms", "asset"])
    lab = ev[ev.label_status == "labeled"]
    target = stats.n_target(h.product)
    look = len(lab) >= target or now_ms >= horizon_end
    base = dict(hid=hid, n_events=len(ev), n_labeled=len(lab), n_target=target, look_reached=look)
    if not look:
        nontie = lab[lab.outcome != -1]
        w = int((nontie.outcome == 1).sum())
        if len(nontie) >= FUTILITY_MIN_N and stats.cp_upper(w, len(nontie)) < breakeven(lab):
            return Result(state="FUTILE", **base, sample_end_ms=int(lab.decision_ms.max()),
                          note="running upper bound below break-even; sealed")
        return Result(state="PENDING", **base)
    sample = lab.iloc[:target]
    end_ms = int(sample.decision_ms.max()) if len(sample) else horizon_end
    s = score(sample)
    ok = passes(s) if len(sample) else False
    extra, notes = {}, []
    if hid == "H1":  # fail closed: no control in the same window means no certificate
        control = _window((extras or {}).get("control"), end_ms, start_ms)
        beaten, p = control_beaten(sample, control)
        extra.update(control_n=len(control), control_beaten=beaten, control_p=p)
        if len(control) == 0:
            notes.append("control missing")
        ok = ok and beaten
    if hid == "H4":  # fail closed: the placebo must be complete and cut to the scored window
        placebos = (extras or {}).get("placebos") or []
        rates = []
        for pl in placebos:
            w = _window(pl, end_ms, start_ms)
            w = w[w.outcome != -1]
            rates.append(float((w.outcome == 1).mean()) if len(w) >= PLACEBO_MIN_TRADES else 1.0)
        extra["placebo_n"] = len(rates)
        if len(rates) < PLACEBO_REQUIRED:
            notes.append(f"placebo incomplete ({len(rates)} < {PLACEBO_REQUIRED})")
            ok = False
        else:
            q99 = float(np.quantile(rates, 0.99))
            extra["placebo_q99"] = q99
            ok = ok and s["win_rate"] > q99
    if ok:
        state = "CERTIFIED" if h.tradable else "FEED-PROPERTY"
    elif s["cp_upper"] < s["breakeven"] + spec.PLANNING_EDGE and len(sample) > 0:
        state = "NULL-INFORMATIVE"
    else:
        state = "UNDERPOWERED"
    if not h.tradable:
        notes.append("feed property only, never an entry")
    return Result(state=state, **base, sample_end_ms=end_ms, **s, extra=extra or None, note="; ".join(notes))


def evaluate_family(per_hid: dict[str, pd.DataFrame], now_ms: int, extras: dict | None = None,
                    sealed: dict[str, dict] | None = None) -> list[Result]:
    """sealed: results already written by an earlier look; they are returned unchanged, never re-scored."""
    sealed = sealed or {}
    results: dict[str, Result] = {}

    def one(hid):
        if hid in sealed:
            return Result(**sealed[hid])
        return evaluate(hid, per_hid.get(hid), now_ms, (extras or {}).get(hid))

    for h in spec.FAMILY:
        if not h.nested_in:
            results[h.hid] = one(h.hid)
    for h in spec.FAMILY:
        if h.nested_in:
            if results[h.nested_in].state == "CERTIFIED":
                results[h.hid] = one(h.hid)
            else:
                results[h.hid] = Result(hid=h.hid, state="NOT-OPENED", n_events=0, n_labeled=0,
                                        n_target=stats.n_target(h.product), look_reached=False,
                                        note=f"fixed sequence: opens only if {h.nested_in} certifies")
    order = {h.hid: i for i, h in enumerate(spec.FAMILY)}
    return sorted(results.values(), key=lambda r: order[r.hid])


SEAL_STATES = {"CERTIFIED", "FEED-PROPERTY", "NULL-INFORMATIVE", "UNDERPOWERED", "FUTILE"}
