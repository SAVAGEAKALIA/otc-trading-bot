"""Capital and sample-size numbers quoted in the lab report, with every parameter stated.

    .venv-lab/bin/python -m services.otc_quant_lab.risk_report --out /home/saviour/otc-quant-lab-artifacts/runs/risk.json
"""
from __future__ import annotations

import argparse
import json

from . import metrics, risk

BANKROLL = 20.0          # minimal starting capital, USD
MIN_STAKE = 1.0          # broker minimum stake, USD
TRADES = 500
DAILY_TRADES = 20
DAILY_LOSS_LIMIT = 0.25  # stop for the day after losing 25% of the day's opening bankroll
PERCENT_FRACTION = 0.05  # percent staking: 5% of bankroll, floored at the minimum stake
WIN_RATES = {"coin": 0.50, "best_dev_selected": 0.5203, "best_final_any_config": 0.5094, "hypothetical_edge": 0.56}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    be = metrics.breakeven(metrics.PRIMARY_PAYOUT)
    out = {"payout": metrics.PRIMARY_PAYOUT, "breakeven": be,
           "parameters": {"bankroll": BANKROLL, "min_stake": MIN_STAKE, "trades": TRADES, "daily_trades": DAILY_TRADES,
                          "daily_loss_limit": DAILY_LOSS_LIMIT, "percent_fraction": PERCENT_FRACTION},
           "kelly": {k: risk.kelly_fraction(w) for k, w in WIN_RATES.items()},
           "survival": {f"{k}|{rule}": risk.survival(w, TRADES, BANKROLL, rule, fraction=PERCENT_FRACTION,
                                                     min_stake=MIN_STAKE, daily_trades=DAILY_TRADES,
                                                     daily_loss_limit=DAILY_LOSS_LIMIT)
                        for k, w in WIN_RATES.items() for rule in ("fixed", "percent")},
           "losing_streak": {k: {n: risk.prob_losing_streak(w, n, TRADES) for n in (6, 8, 10, 12)}
                             for k, w in WIN_RATES.items()},
           "trades_needed": {edge: risk.trades_needed(edge, be) for edge in (0.01, 0.02, 0.03, 0.05)}}
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(json.dumps(out, default=float)[:600])


if __name__ == "__main__":
    main()
