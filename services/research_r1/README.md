# R1 hypothetical economics and research configuration

This standalone standard-library service produces scenario evidence only. It cannot import exchange adapters, send orders or enable live mode. No hosted model calls or paid services are used.

The contract is version 1 `config.example.json` to CSV scenario rows plus a JSON readiness report on stdout. Its settings record Nigeria, user-reported Bybit/WEEX/Binance accounts and USDT reference currency. Eligibility, authenticated fees, final data-quality acceptance and signed trial specification remain false until supported by evidence. Live budgets are explicitly null. Configuration completeness is a validation result, never a signature or permission to trade. `r2_freeze_ready` stays false: the final data, account and protocol evidence lock is outside this diagnostic.

For fully paid spot and a separate stablecoin short margin account:

```
capital_multiplier = 1 + 1 / short_leverage + reserve_per_notional
hedged_notional = total_capital / capital_multiplier
annual_net_profit = hedged_notional * net_notional_apr - annual_fixed_cost
annual_excess_profit = annual_net_profit - total_capital * benchmark_apr
```

Net notional APR is a **hypothetical input after variable costs**, not a funding forecast. No lending yield is assumed on margin/reserves. The 0% benchmark represents non-interest-bearing USDT holding in USDT units, not a USD risk-free asset. FX, depeg, tax, counterparty loss, basis, liquidation and dynamic margin are not modeled. Full portfolio accounting belongs in R2.

The example grid uses hypothetical capital amounts of 1,000, 5,000 and 10,000 USDT, six return scenarios, and annual fixed costs of 0, 120 and 360 USDT. These are sensitivity assumptions, not recommended allocations, observed returns or approved expenditure. A reserve of 0.5 per hedged notional and 1x short require 2.5 times notional capital, matching the trial specification's 40% spot, 40% margin, 20% reserve scenario. User loss budgets remain unset and cannot be inferred from these examples.

Run from repository root:

```bash
python3 -m unittest discover -s services/research_r1/tests -v
python3 services/research_r1/evals/eval_scenarios.py
python3 services/research_r1/scenarios.py --config services/research_r1/config.example.json --output /tmp/r1-economics.csv
```

Tests verify capital conservation, cost effects, invalid-input rejection, no live mode, and unset-budget handling. Offline evals sweep adverse funding, capital, cost and reserve assumptions. They do not measure strategy quality or annual profitability.

No running daemon, installation or restart is required. New CSV output is local and should use a new path when preserving earlier evidence.
