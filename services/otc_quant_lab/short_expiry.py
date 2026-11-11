"""1, 2 and 3 minute expiries on the live-recorded period (Jul 31 - Aug 20 2026), labelled from 1 s candles.

Decisions are made at the close of each recorded 120 s bar, with the same causal features as the main
study. Outcomes come from the 1 s candles, not the bar proxy:
  entry  = last 1 s close at or before decision + DELAY (at most 3 s old)
  expiry = last 1 s close at or before entry + E (at most 3 s old); E in {60, 120, 180} s
The 1 s feed covers about 27% of the period, so only covered decisions get labels.

It also measures how often the main study's bar-close proxy (close of bar t+1 vs close of bar t)
agrees with the second-level 120 s outcome at zero delay (critic round 2, finding 8e).

Split per expiry by the time of LABELLED decisions (1 s coverage is uneven, so a calendar split leaves
almost no labelled test rows): first 60% train, next 15% inner (Platt + thresholds), then a gap of the
128 min feature lookback + 3 min label horizon + 1 day embargo (rubric H3), the rest test.

    .venv-lab/bin/python -m services.otc_quant_lab.short_expiry --out /home/saviour/otc-quant-lab-artifacts/runs/short_expiry.json
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from . import baselines, data, features, metrics, regimes
from .features import DOWN, FEATURES, TIE, UNKNOWN, UP
from .models import tabular_zoo
from .walkforward import platt, thresholds, trades

EXPIRIES = (60, 120, 180)
DELAY = 2
MAX_STALE = 3
GAP_S = (features.LOOKBACK * 2 + 3) * 60 + 86400  # lookback (64 x 120 s) + longest expiry + 1 day embargo


def second_labels(frame: pd.DataFrame, seconds: pd.DataFrame, delay: int, expiry: int, tf: int = 120) -> np.ndarray:
    """UP/DOWN/TIE/UNKNOWN per frame row from 1 s closes (rows sorted by asset, t)."""
    out = np.full(len(frame), UNKNOWN, dtype=np.int8)
    for asset, idx in frame.groupby("asset").indices.items():
        s = seconds[seconds.asset == asset].sort_values("t")
        if s.empty:
            continue
        ts, cs = s.t.to_numpy(), s.c.to_numpy()
        entry_t = frame.t.to_numpy()[idx] + tf + delay
        i0 = np.searchsorted(ts, entry_t, side="right") - 1
        i1 = np.searchsorted(ts, entry_t + expiry, side="right") - 1
        ok = (i0 >= 0) & (i1 >= 0)
        i0c, i1c = np.clip(i0, 0, None), np.clip(i1, 0, None)
        ok &= (entry_t - ts[i0c] <= MAX_STALE) & (entry_t + expiry - ts[i1c] <= MAX_STALE) & (i1c > i0c)
        e, x = cs[i0c], cs[i1c]
        lab = np.where(x > e, UP, np.where(x < e, DOWN, TIE)).astype(np.int8)
        out[idx[ok]] = lab[ok]
    return out


def split_spans(t_known: np.ndarray) -> dict[str, tuple[float, float]]:
    """(lo, hi] time spans: first 60% of labelled decisions train, next 15% inner, then GAP_S, then test."""
    q60, q75 = np.quantile(t_known, [0.60, 0.75])
    return {"train": (-np.inf, q60), "inner": (q60, q75), "test": (q75 + GAP_S, np.inf)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    frame = features.build(data.load_realtime(120), 120, (1,))
    seconds = data.load_realtime(1)
    valid = frame.valid.to_numpy()
    day = frame.day.to_numpy()
    days = np.unique(day[valid])
    t_all = frame.t.to_numpy()
    result = {"period": [str(pd.to_datetime(int(days[0]) * 86400, unit="s").date()),
                         str(pd.to_datetime(int(days[-1]) * 86400, unit="s").date())],
              "delay_s": DELAY, "payout": metrics.PRIMARY_PAYOUT, "split": "60% train / 15% inner / lookback + horizon + 1 day gap / rest test",
              "expiries": {}}

    agree = second_labels(frame, seconds, 0, 120)
    both = valid & (agree != UNKNOWN) & (frame.y1.to_numpy() != UNKNOWN)
    result["proxy_agreement_120s"] = {"rows": int(both.sum()),
                                      "same_outcome": float((agree[both] == frame.y1.to_numpy()[both]).mean())}

    order = np.lexsort((frame.asset_id.to_numpy(), frame.t.to_numpy()))
    x_all = frame[FEATURES].to_numpy(np.float32)
    zoo = tabular_zoo()
    models = {"logistic": zoo["logistic"], "lightgbm": zoo["lightgbm"], "markov_pat3": lambda: regimes.Pattern("pat3", 27)}
    rules = {k: v for k, v in baselines.baseline_suite(frame, 120).items()
             if k in ("mhi_minority3_quadrant", "exhaustion_4", "trend_follow_ret10")}
    trials = 0
    for expiry in EXPIRIES:
        y = second_labels(frame, seconds, DELAY, expiry)
        tmp = frame[["asset", "t", "day", "hour"]].copy()
        tmp["y1"] = y
        known = valid & (y != UNKNOWN)
        spans = split_spans(t_all[known])
        rows = {name: order[(known & (t_all > lo) & (t_all <= hi))[order]] for name, (lo, hi) in spans.items()}
        binary = lambda r: r[np.isin(y[r], (UP, DOWN))]
        up_rows = binary(order[known[order]])
        nxt = (y[up_rows] == UP).astype(int)
        entry = {"labelled_decisions": int(known.sum()), "train_rows": int(len(rows["train"])),
                 "inner_rows": int(len(rows["inner"])), "test_rows": int(len(rows["test"])),
                 "test_days": int(len(np.unique(day[rows["test"]]))), "up_rate": float(nxt.mean()),
                 "tie_rate": float((y[known] == TIE).mean()), "models": {}, "rules": {}}
        for name, make in models.items():
            tr = binary(rows["train"])
            model = make().fit(x_all[tr], (y[tr] == UP).astype(np.int8))
            inner = binary(rows["inner"])
            calib = platt(model.predict(x_all[inner]), (y[inner] == UP).astype(np.int8))
            p_test = calib(model.predict(x_all[rows["test"]]))
            te = binary(rows["test"])
            p_te = calib(model.predict(x_all[te]))
            yb = (y[te] == UP).astype(int)
            day_ids = np.unique(day[te])
            day_auc = np.array([metrics.auc(yb[day[te] == d], p_te[day[te] == d]) for d in day_ids])
            ok = np.isfinite(day_auc)  # a day with one outcome class has no AUC
            entry["models"][name] = {"auc": metrics.auc(yb, p_te), "day_auc_mean": float(day_auc[ok].mean()),
                                     "day_auc_ci95": list(metrics.day_block_bootstrap(day_auc[ok], day_ids[ok], reps=500))}
            for q, thr in thresholds(calib(model.predict(x_all[inner]))).items():
                if q not in (1.0, 0.1):
                    continue
                t = trades(tmp, rows["test"], p_test, thr, 1, expiry)
                entry["models"][name][f"cov{q}"] = metrics.trade_summary(t.outcome.to_numpy(), t.day.to_numpy())
                trials += 1
        for name, p_all in rules.items():
            t = trades(tmp, rows["test"], p_all[rows["test"]], 0.51, 1, expiry)
            entry["rules"][name] = metrics.trade_summary(t.outcome.to_numpy(), t.day.to_numpy())
            trials += 1
        result["expiries"][str(expiry)] = entry
    result["trials"] = trials
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2, default=float)
    print(json.dumps({"agreement": result["proxy_agreement_120s"],
                      **{e: {m: (v["auc"], (v.get("cov0.1") or {}).get("win_rate")) for m, v in r["models"].items()}
                         for e, r in result["expiries"].items()}}, default=float))


if __name__ == "__main__":
    main()
