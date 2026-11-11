"""Deterministic extraction of every number the lab report quotes from a run directory.

The report is written from this output, not by reading JSON by eye (critic round 2 found two C1
counts mis-transcribed that way).

    .venv-lab/bin/python -m services.otc_quant_lab.report_digest RUN_DIR [--expiry-payouts 1:0.84,2:0.84,5:0.86]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .metrics import breakeven


def c1_cells(scores: list[dict]) -> dict:
    """Day-AUC CI exclusions of 0.5, split by direction. Base-rate cells are degenerate and excluded."""
    rows = [r for r in scores if r["model"] != "base_rate" and r.get("day_auc_ci95")]
    above = [(r["model"], r["h"], r["day_auc_mean"], r["day_auc_ci95"]) for r in rows if r["day_auc_ci95"][0] > 0.5]
    below = [(r["model"], r["h"], r["day_auc_mean"], r["day_auc_ci95"]) for r in rows if r["day_auc_ci95"][1] < 0.5]
    return {"cells": len(rows), "expected_by_chance_95": round(0.05 * len(rows), 2),
            "exclude_above": above, "exclude_below": below,
            "day_auc_range": [min(r["day_auc_mean"] for r in rows), max(r["day_auc_mean"] for r in rows)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--expiry-payouts", default="", help="h:payout pairs for per-expiry break-even")
    args = parser.parse_args()
    out = Path(args.run) / "out" if (Path(args.run) / "out").exists() else Path(args.run)
    s = json.load(open(out / "summary.json"))
    final = pd.read_csv(out / "final_table.csv")
    payouts = {int(k): float(v) for k, v in (p.split(":") for p in args.expiry_payouts.split(",") if p)}
    big = final[final.trades >= 1000].copy()
    big["h"] = big.config.str.extract(r"\|h(\d+)\|")[0].astype(float)
    big["breakeven"] = big.h.map(lambda h: breakeven(payouts.get(int(h), 0.84)) if h == h else breakeven(0.84))
    best = big.sort_values("win_rate", ascending=False).head(1)
    digest = {
        "K": s["trials_K"], "winner": s["winner_selected_on_dev"],
        "winner_dev": {k: s["winner_dev"][k] for k in ("trades", "days", "win_rate", "wilson95", "wilson_lower_bonferroni",
                                                       "mean_return", "mean_return_day_bootstrap95")},
        "winner_final": {k: s["winner_final"][k] for k in ("trades", "days", "win_rate", "wilson95",
                                                           "wilson_lower_bonferroni", "mean_return",
                                                           "mean_return_day_bootstrap95", "max_consecutive_losses",
                                                           "max_drawdown_stakes")},
        "rubric": s["winner_rubric"], "pbo": s["pbo"]["pbo"], "pbo_family": (s.get("pbo_winner_family") or {}).get("pbo"),
        "winner_traded_calibration": s.get("winner_traded_calibration"),
        "final_configs_ge_1000": int(len(big)),
        "final_best_ge_1000": best[["config", "trades", "win_rate", "breakeven"]].to_dict("records"),
        "final_configs_above_own_breakeven": int((big.win_rate > big.breakeven).sum()),
        "c1": c1_cells(s["model_scores_final"]),
        "realtime_best_ge_1000": [(r["config"], r["trades"], r["win_rate"]) for r in s["realtime_top10_post_hoc"]
                                  if r["trades"] >= 1000][:3],
    }
    print(json.dumps(digest, indent=1, default=float))


if __name__ == "__main__":
    main()
