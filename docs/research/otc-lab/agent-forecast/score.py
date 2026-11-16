"""Score the forecaster agents and the judge against held-back 10-minute outcomes. Runs once.

  .venv-lab/bin/python docs/research/otc-lab/agent-forecast/score.py
"""
import json, sys
from pathlib import Path
from scipy import stats

HERE = Path(__file__).resolve().parent
ANSWERS = Path("/home/saviour/otc-quant-lab-artifacts/agent-forecast/answers.json")
PRED = HERE / "predictions"
WHO = ["statistician", "chartist", "regimes", "crossasset", "skeptic", "judge"]
PAYOUT, BE = 0.86, 1 / 1.86


def score(name, truth):
    p = {x["id"]: x for x in json.loads((PRED / f"{name}.json").read_text())}
    calls = [(i, p[i]["call"]) for i in truth if i in p and p[i]["call"] in ("up", "down")]
    wins = sum(1 for i, c in calls if truth[i] == (1 if c == "up" else -1))
    ties = sum(1 for i, c in calls if truth[i] == 0)
    n = len(calls) - ties
    lo, hi = (stats.beta.ppf(0.025, wins, n - wins + 1) if wins else 0.0,
              stats.beta.ppf(0.975, wins + 1, n - wins) if n > wins else 1.0)
    ret = (wins * PAYOUT - (n - wins)) / len(calls) if calls else 0.0
    return {"calls": len(calls), "abstained": len(truth) - len(calls), "wins": wins, "win_rate": wins / n if n else None,
            "ci95": [round(lo, 3), round(hi, 3)], "return_per_stake": round(ret, 3),
            "beats_breakeven_95": bool(n and lo > BE), "missing": [i for i in truth if i not in p]}


def main():
    out_path = HERE / "result.json"
    if out_path.exists():
        sys.exit("refusing: scored once already")
    truth = {x["id"]: x["up"] for x in json.loads(ANSWERS.read_text())}
    res = {w: score(w, truth) for w in WHO if (PRED / f"{w}.json").exists()}
    res["base_rate_up"] = sum(v == 1 for v in truth.values()) / len(truth)
    with open(out_path, "x") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
