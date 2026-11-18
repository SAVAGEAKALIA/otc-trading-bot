"""Score per-case buy/sell/abstain calls with per-case horizons (2/5/10 min). Runs once.

  .venv-lab/bin/python docs/research/otc-lab/agent-forecast3/score.py
"""
import json, sys
from collections import defaultdict
from pathlib import Path
from scipy import stats

HERE = Path(__file__).resolve().parent
ANSWERS = Path("/home/saviour/otc-quant-lab-artifacts/agent-forecast3/answers.json")
WHO = ["priceaction", "trend", "reversal", "multitf", "crossasset", "judge"]
PAYOUT = {2: 0.84, 5: 0.84, 10: 0.86}


def ci(w, n):
    if n == 0:
        return [0.0, 1.0]
    return [round(stats.beta.ppf(0.025, w, n - w + 1) if w else 0.0, 3),
            round(stats.beta.ppf(0.975, w + 1, n - w) if w < n else 1.0, 3)]


def score(name, truth):
    preds = {x["id"]: x for x in json.loads((HERE / "predictions" / f"{name}.json").read_text())}
    wins = losses = ties = 0
    pnl = 0.0
    be_sum = 0.0
    by_h = defaultdict(lambda: [0, 0, 0])
    for cid, moves in truth.items():
        p = preds.get(cid)
        if not p or p["call"] not in ("buy", "sell"):
            continue
        h = int(p["horizon_min"]) if int(p.get("horizon_min", 10)) in PAYOUT else 10
        m = moves[str(h)]
        side = 1 if p["call"] == "buy" else -1
        be_sum += 1 / (1 + PAYOUT[h])
        if m == 0:
            ties += 1
            by_h[h][2] += 1
        elif m == side:
            wins += 1
            pnl += PAYOUT[h]
            by_h[h][0] += 1
        else:
            losses += 1
            pnl -= 1
            by_h[h][1] += 1
    calls = wins + losses + ties
    n = wins + losses
    return {"calls": calls, "abstained": len(truth) - calls, "wins": wins, "losses": losses, "ties": ties,
            "win_rate": round(wins / n, 3) if n else None, "ci95": ci(wins, n),
            "breakeven": round(be_sum / calls, 4) if calls else None,
            "pnl_units": round(pnl, 2), "return_per_stake": round(pnl / calls, 3) if calls else 0.0,
            "by_horizon": {str(k): {"wins": v[0], "losses": v[1], "ties": v[2]} for k, v in sorted(by_h.items())},
            "missing": [c for c in truth if c not in preds]}


def main():
    out = HERE / "result.json"
    if out.exists():
        sys.exit("refusing: scored once already")
    truth = {x["id"]: x["move"] for x in json.loads(ANSWERS.read_text())}
    res = {w: score(w, truth) for w in WHO if (HERE / "predictions" / f"{w}.json").exists()}
    res["base_rate_up"] = {h: sum(m[h] == 1 for m in truth.values()) / len(truth) for h in ("2", "5", "10")}
    # Pre-registered verdict (committed before any agent ran):
    #   primary   = judge: CERTIFIED if the one-sided 95% lower bound on win rate exceeds its break-even
    #   secondary = each forecaster at one-sided 99% (0.05 / 5)
    for w, v in res.items():
        if w == "base_rate_up" or not v["calls"]:
            continue
        n, k = v["wins"] + v["losses"], v["wins"]
        alpha = 0.05 if w == "judge" else 0.01
        lo = float(stats.beta.ppf(alpha, k, n - k + 1)) if k else 0.0
        v["lower_bound"] = round(lo, 4)
        v["alpha"] = alpha
        v["certified"] = bool(n >= 30 and lo > v["breakeven"] and v["pnl_units"] > 0)
    with open(out, "x") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
