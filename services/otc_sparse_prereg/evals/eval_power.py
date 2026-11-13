"""Periodic eval for gates G2 (planted-edge power) and G3 (known-null pipeline control).

Deterministic seeds, no network, no real data. Pass thresholds (frozen with the registration):
  G2a  exact CP power at the registered n for a +5 pt edge                    >= 0.80
  G2b  exact CP false-certification probability at break-even                 <= ALPHA (0.00625)
  G2c  full certificate (CP, ties as losses, bootstrap, thirds) power, 0.6% ties, Monte Carlo  >= 0.80
  G2d  full certificate false-certification rate on a null, Monte Carlo       <= ALPHA + 2 MC SE
  G3a  end-to-end pipeline on a memoryless 1-second random walk: nothing CERTIFIED
  G3b  same pipeline with a planted fade after extreme moves: H2 CERTIFIED
Thresholds for G3 are frozen on a pre-forward segment of the synthetic market, never in-sample.

Run: .venv-lab/bin/python -m services.otc_sparse_prereg.evals.eval_power --output /tmp/sparse-prereg/eval.json
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd
from scipy import stats as sps

from services.otc_sparse_prereg import certify, labels, spec, stats, triggers

LATE = spec.FORWARD_START_MS + 211 * spec.DAY_MS
TIE = spec.TIE_RATE_2MIN


def exact_rates() -> tuple[float, float]:
    n, be = stats.n_target("turbo"), spec.breakeven(0.84)
    k = stats.min_wins_to_certify(n, be)
    power = float(sps.binom.sf(k - 1, n, be + spec.PLANNING_EDGE))
    false = float(sps.binom.sf(k - 1, n, be))
    return power, false


def _trades(n, p, rng, payout=0.84):
    tie = rng.random(n) < TIE
    out = np.where(tie, -1, (rng.random(n) < p).astype(int))
    return pd.DataFrame({"asset": "X", "decision_ms": spec.FORWARD_START_MS + np.arange(n) * 1_800_000,
                         "label_status": "labeled", "outcome": out, "payout": payout})


def certificate_rates(reps_power=300, reps_null=1500, seed=1):
    rng = np.random.default_rng(seed)
    n, be = stats.n_target("turbo"), spec.breakeven(0.84)
    # win probability among non-tie trades so that the +5 pt edge holds on the non-tie win rate
    power = np.mean([certify.evaluate("H2", _trades(n, be + 0.05, rng), LATE).state == "CERTIFIED"
                     for _ in range(reps_power)])
    false = np.mean([certify.evaluate("H2", _trades(n, be, rng), LATE).state == "CERTIFIED"
                     for _ in range(reps_null)])
    return float(power), float(false), reps_null


def synthetic_market(days=40, archive_days=12, assets=("EURUSD-OTC", "GBPUSD-OTC", "AUDUSD-OTC"),
                     planted=0.0, seed=7):
    """1-s random walk per asset. The first archive_days end 2 days before the forward start."""
    rng = np.random.default_rng(seed)
    start_s = spec.FORWARD_START_MS // 1000 - (archive_days + 2) * 86400
    secs = np.arange(start_s, spec.FORWARD_START_MS // 1000 + days * 86400)
    paths = {a: 1.1 * np.exp(np.cumsum(rng.normal(0, 1e-5, len(secs)) * (1 + 4 * (rng.random(len(secs)) < 1e-4))))
             for a in assets}

    def bars_from(paths):
        rows = []
        for a, p in paths.items():
            m = p.reshape(-1, 120)
            rows.append(pd.DataFrame({"asset": a, "t": secs[::120], "o": m[:, 0], "h": m.max(1), "l": m.min(1),
                                      "c": m[:, -1]}))
        return pd.concat(rows, ignore_index=True)

    b = bars_from(paths)
    archive_end = spec.FORWARD_START_MS // 1000 - 2 * 86400
    thr = triggers.thresholds_from_archive(triggers.candle_frame(b[b.t < archive_end]))
    if planted:
        f = triggers.candle_frame(b)
        ev = triggers.non_overlapping(triggers.h2(f, thr))
        for a, side, d in zip(ev.asset, ev.side, ev.decision_ms):
            i = int((d + spec.ENTRY_DELAY_MS) // 1000 - start_s) + 30  # inside the 2-minute expiry window
            if i >= len(secs):
                continue
            good = rng.random() < planted
            paths[a][i:] *= np.exp((side if good else -side) * 3e-4)
        b = bars_from(paths)
    keep = secs * 1000 >= spec.FORWARD_START_MS - spec.DAY_MS
    c1 = pd.concat([pd.DataFrame({"asset": a, "candle_start_ms": secs[keep] * 1000, "close": p[keep]})
                    for a, p in paths.items()])
    po = pd.concat([pd.DataFrame({"asset": a, "instrument_type": it, "received_at_ms": secs[::30] * 1000,
                                  "payout_fraction": 0.84 if it == "turbo-option" else 0.86})
                    for a in assets for it in ("turbo-option", "binary-option")])
    return b[b.t >= archive_end - 2 * 86400], c1, po, thr


def pipeline(b, c1, po, thr):
    f = triggers.candle_frame(b)
    ev = {"H2": triggers.h2(f, thr), "H2b": triggers.h2b(f, thr), "H3": triggers.h3(f),
          "H4": triggers.h4(b), "H5": triggers.h5(f, thr)}
    fwd = lambda e: triggers.non_overlapping(e[e.decision_ms >= spec.FORWARD_START_MS])
    lab = {k: labels.label(fwd(v), c1, po) for k, v in ev.items()}
    return {r.hid: r for r in certify.evaluate_family(lab, LATE)}


def run_all() -> dict:
    t0 = time.time()
    p_exact, f_exact = exact_rates()
    p_mc, f_mc, reps = certificate_rates()
    se = np.sqrt(spec.ALPHA * (1 - spec.ALPHA) / reps)
    null = pipeline(*synthetic_market(planted=0.0))
    plant = pipeline(*synthetic_market(planted=0.70, seed=8))
    checks = {
        "G2a_exact_power_ge_0.80": p_exact >= 0.80,
        "G2b_exact_false_cert_le_alpha": f_exact <= spec.ALPHA,
        "G2c_full_certificate_power_ge_0.80": p_mc >= 0.80,
        "G2d_full_certificate_false_cert_le_alpha_plus_2se": bool(f_mc <= spec.ALPHA + 2 * se),
        "G3a_known_null_certifies_nothing": all(r.state != "CERTIFIED" for r in null.values()),
        "G3b_planted_fade_certifies_H2": plant["H2"].state == "CERTIFIED",
    }
    return {"checks": checks, "passed": all(checks.values()),
            "exact_power": p_exact, "exact_false_cert": f_exact, "mc_power": p_mc, "mc_false_cert": f_mc,
            "null_states": {k: r.state for k, r in null.items()},
            "null_cp_lower_minus_be": {k: round(r.cp_lower - r.breakeven, 4) for k, r in null.items()
                                       if r.cp_lower is not None},
            "planted_H2": plant["H2"].as_dict(), "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="/tmp/sparse-prereg-eval.json")
    args = ap.parse_args()
    out = run_all()
    with open(args.output, "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(json.dumps(out, indent=1, default=float))
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
