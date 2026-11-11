"""Pipeline power and false-positive controls (rubric H4/H5), run through run_lab.run unchanged.

Base data: the last DAYS days of real archive bars for ASSETS. Each bar's close-to-close log return
gets a random sign (open, high and low keep their ratios to the moved close), so volatility
clustering, ties, the daily feed-restart gaps and real timestamps survive but direction carries no
information. This is the null (negative control): any pass is a false discovery.

Positive control: on the same sign-randomised series, when the trailing 10-bar move exceeds one
standard deviation, the next close continues that move with probability EDGE (0.58). About 30% of
bars carry the edge. It is a trend edge on a continuous feature, so it is not one of the colour
patterns the Markov tables enumerate.

    .venv-lab/bin/python -m services.otc_quant_lab.evals.eval_controls --seeds 8 \
        --models logistic,lightgbm,regime_kmeans16,deep_gru,markov_pat3 --horizons 1,2 \
        --out /tmp/otc-quant-lab/runs/controls-full
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from services.otc_quant_lab import data, run_lab

TF = 120
ASSETS = ["EURUSD-OTC", "GBPJPY-OTC", "AUDUSD-OTC"]
DAYS = 70
EDGE = 0.58


FORMS = {  # name: (window bars, volatility lookback bars, trigger in sd, continuation probability)
    "trend10": (10, 60, 1.0, 0.58),   # round 1: equals the built-in rule:trend_follow_ret10 (critic finding 1)
    "burst7": (7, 30, 1.645, 0.57),   # round 2: rubric boundary (57% on ~10% of bars); not a built-in rule
}


def randomise(bars: pd.DataFrame, seed: int, edge: float | None, form: str = "trend10") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for _, g in bars.groupby("asset", sort=True):
        g = g.sort_values("t").reset_index(drop=True)
        c = g.c.to_numpy()
        r = np.diff(np.log(c), prepend=np.log(c[0]))
        mag = np.abs(r)
        sign = np.where(rng.random(len(r)) < 0.5, 1.0, -1.0)
        new_r = sign * mag
        if edge is not None:
            win, look, trigger, p_cont = FORMS[form]
            u = rng.random(len(r))
            for i in range(look, len(r)):
                sd = new_r[i - look:i].std() * np.sqrt(win)
                move = new_r[i - win:i].sum()
                if sd > 0 and abs(move) > trigger * sd and mag[i] > 0:
                    new_r[i] = np.sign(move) * mag[i] if u[i] < p_cont else -np.sign(move) * mag[i]
        new_c = c[0] * np.exp(np.cumsum(new_r))
        prev_old = np.concatenate([[c[0]], c[:-1]])
        prev_new = np.concatenate([[new_c[0]], new_c[:-1]])
        new_o = prev_new * (g.o.to_numpy() / prev_old)
        top_ratio = g.h.to_numpy() / np.maximum(g.o.to_numpy(), c)
        bottom_ratio = g.l.to_numpy() / np.minimum(g.o.to_numpy(), c)
        out.append(pd.DataFrame({"asset": g.asset, "t": g.t, "o": new_o,
                                 "h": np.maximum(new_o, new_c) * top_ratio,
                                 "l": np.minimum(new_o, new_c) * bottom_ratio, "c": new_c}))
    return pd.concat(out, ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--out", required=True)
    parser.add_argument("--models", default="logistic,lightgbm,regime_kmeans16,deep_gru,markov_pat3")
    parser.add_argument("--horizons", default="1,2")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--bars-parquet", default="", help="pre-exported base bars (remote runs)")
    parser.add_argument("--merge", nargs="*", default=None, help="controls.jsonl shards to summarise")
    parser.add_argument("--kinds", default="negative,positive", help="which controls to run")
    parser.add_argument("--form", default="trend10", choices=sorted(FORMS), help="positive-control edge form")
    parser.add_argument("--judge-k", type=int, default=0, help="also judge P2 at this trial count (main study K)")
    parser.add_argument("--all-assets", action="store_true", help="scale-matched: keep every asset and day of the parquet")
    args = parser.parse_args()
    root = Path(args.out)
    if args.merge is not None:
        root.mkdir(parents=True, exist_ok=True)
        rows = [json.loads(line) for path in args.merge for line in open(path)]
        verdict = summarise(rows, args)
        (root / "verdict.json").write_text(json.dumps(verdict, indent=2))
        print(json.dumps(verdict))
        return
    root.mkdir(parents=True, exist_ok=False)
    bars = pd.read_parquet(args.bars_parquet) if args.bars_parquet else base_bars()
    if not args.all_assets:
        bars = bars[bars.asset.isin(ASSETS)]
        bars = bars[bars.t >= bars.t.max() - DAYS * 86400].reset_index(drop=True)
    results = []
    for kind, edge in (("negative", None), ("positive", FORMS[args.form][3])):
        if kind not in args.kinds.split(","):
            continue
        for seed in range(args.seed_start, args.seed_start + args.seeds):
            ns = SimpleNamespace(out=str(root / f"{kind}-{seed}"), tf=TF, horizons=args.horizons,
                                 models=args.models, realtime=False, assets="")
            summary = run_lab.run(ns, bars=randomise(bars, 5000 + seed, edge, args.form))
            r = summary["winner_rubric"]
            wf = summary["winner_final"] or {}
            results.append({"kind": kind, "seed": seed, "winner": summary["winner_selected_on_dev"],
                            "pass": bool(r.get("pass")), "checks": r, "K": summary["trials_K"],
                            "pbo": summary["pbo"]["pbo"],
                            "final_win_rate": (summary["winner_final"] or {}).get("win_rate"),
                            "final_trades": wf.get("trades"), "final_wins": wf.get("wins"),
                            "final_losses": wf.get("losses"), "breakeven": wf.get("breakeven_primary"),
                            "form": args.form if kind == "positive" else None})
            line = json.dumps(results[-1], default=float)
            print(line, flush=True)
            with (root / "controls.jsonl").open("a") as f:
                f.write(line + "\n")
    verdict = summarise(results, args)
    (root / "verdict.json").write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict))


def base_bars() -> pd.DataFrame:
    bars = data.load_historical(TF)
    bars = bars[bars.asset.isin(ASSETS)]
    return bars[bars.t >= bars.t.max() - DAYS * 86400].reset_index(drop=True)


def summarise(results: list[dict], args) -> dict:
    checks = sorted({k for r in results for k in r["checks"] if k != "pass"})
    per_check = {kind: {c: float(np.mean([bool(r["checks"].get(c)) for r in results if r["kind"] == kind]))
                        for c in checks} for kind in ("negative", "positive")}
    neg = [r["pass"] for r in results if r["kind"] == "negative"]
    pos = [r["pass"] for r in results if r["kind"] == "positive"]
    from services.otc_quant_lab.metrics import wilson, wilson_lower_one_sided

    judge_k = getattr(args, "judge_k", 0)

    def pass_at(r, k):
        """Rubric pass with P2 re-judged at trial count k (e.g. the main study's K)."""
        if not k or r.get("final_wins") is None:
            return None
        n = r["final_wins"] + r["final_losses"]
        p2 = n > 0 and wilson_lower_one_sided(r["final_wins"], n, 0.05 / k) > r["breakeven"]
        others = all(bool(v) for c, v in r["checks"].items() if c not in ("pass", "P2_bonferroni_wilson"))
        return bool(p2 and others)

    def p1_p6(r):
        return all(bool(r["checks"].get(c)) for c in checks if c != "P7_calibration")

    return {"false_positive_rate": float(np.mean(neg)), "fpr_wilson95": list(wilson(int(sum(neg)), len(neg))),
            "power": float(np.mean(pos)), "power_wilson95": list(wilson(int(sum(pos)), len(pos))),
            "H4_pass": bool(np.mean(neg) <= 0.05), "H5_pass": bool(np.mean(pos) >= 0.80),
            "negative_runs": len(neg), "positive_runs": len(pos), "per_check_pass_rate": per_check,
            "edge": FORMS[getattr(args, "form", "trend10")][3], "form": getattr(args, "form", "trend10"), "models": args.models, "horizons": args.horizons,
            "winners_positive": sorted({r["winner"] for r in results if r["kind"] == "positive"}),
            "p1_p6_pass": {kind: int(sum(p1_p6(r) for r in results if r["kind"] == kind)) for kind in ("negative", "positive")},
            "judge_k": judge_k,
            "pass_at_judge_k": {kind: [pass_at(r, judge_k) for r in results if r["kind"] == kind] for kind in ("negative", "positive")},
            "missed_positive_causes": [{"seed": r["seed"], "winner": r["winner"], "final_trades": r["final_trades"],
                                        "final_win_rate": r["final_win_rate"],
                                        "failed": [c for c, v in r["checks"].items() if c != "pass" and not v]}
                                       for r in results if r["kind"] == "positive" and not r["pass"]]}


if __name__ == "__main__":
    main()
