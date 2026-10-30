# Carry economics and evidence audit

Date: 2026-10-30. Scope: research only. No strategy was built or approved.

## Verdict

The original table is reproducible, but does not demonstrate investable returns or a safe hedge. It is an annualized funding-minus-assumed-fees diagnostic. Do not promote any sleeve from this evidence.

The original report reproduced byte-for-byte with the repository virtualenv. The 121,328-row raw file was recovered at:

`/tmp/claude-1000/-home-saviour-PycharmProjects-I2-IQoption/e632c59c-6a70-40c5-8d7c-d83dec295f79/scratchpad/funding/funding.json`

SHA256: `1969cf4f62d913527383ac66875d9f23efd4fddcf9b7d7bb7a8994a46e137a1a`.

The independent standard-library diagnostic in `carry_audit.py` reproduces the funding-only logic, checks duplicate/nonfinite records, inventories calendar coverage, and computes capital/fee sensitivities. Its output is `carry_audit_results.json`. The raw file remains ephemeral, not an immutable published dataset; preserve a content-addressed source artifact before future investment research.

## Capital changes the conclusion

Segregated fully paid spot of N plus a stablecoin-margined short at 1x requires approximately 2N before reserve capital. The original README's 1.0–1.5N is incompatible with that setup. Portfolio-margin offsets require a separate verified collateral model, asset haircuts, account eligibility and stress testing; do not silently assume them.

| Annualized funding-only proxy | 2024 / N | 2025 / N | 2026 / N | 2026 / 2N |
|---|---:|---:|---:|---:|
| Bybit BTC | 9.75% | 1.80% | 0.84% | 0.42% |
| Bybit ETH | 11.33% | 0.96% | -0.07% | -0.03% |
| Hyperliquid BTC | 23.31% | 9.73% | 3.54% | 1.77% |
| Hyperliquid ETH | 20.02% | 6.62% | 3.86% | 1.93% |

2026 contains 303 calendar days, including an incomplete final day. These are annualized rates, not actual YTD returns. The 2N column is a denominator sensitivity only, not an investable backtest. It excludes reserve drag, idle yield, price/basis movement, rebalancing, slippage, infrastructure, tax and operational losses.

## Specific defects and corrections

1. `realized_carry.py` adds funding-rate percentages, implicitly holding notional constant without modeling the trading required to maintain it. A fixed-quantity matched spot/linear-perp hedge has funding cash flows proportional to current mark value, not initial N. Model quantity, mark, funding cash, fees and equity event by event.
2. It omits spot/perp basis changes, intraday margins, exchange equity, liquidation/ADL, transfer restrictions and actual executable prices. Therefore it cannot establish maximum drawdown, survivability, or returns on equity.
3. It charges half the assumed round trip at each state transition, with no forced exit at dataset end. BTC on Bybit and all three Hyperliquid series finish open, leaving the final assumed exit fee unbooked. Mark liquidation value or report open exposure and estimated close cost separately.
4. The signal uses prior completed daily sums via a one-day lag, which is good. But it assumes a transition at the new day's boundary earns all that day's prints. Funding at 00:00 cannot safely be attributed to an order decided and filled after that event. Define event ordering, information availability and eligibility explicitly; use subsequent execution and settlement timestamps.
5. Resampling zero-fills absent days; the collector never proves complete coverage or rejects conflicting duplicates. This recovered sample has no whole missing days and no duplicate timestamps. Hyperliquid has early three-print days and several 23-print days; Bybit SOL changes print frequency. Diagnose schedule changes versus missing records using historical venue rules before treating either as errors or valid zero funding.
6. The proposed entry rule requiring seven-day funding to cover twice the round-trip fee was not tested. Its annualized break-even is 32.33% on Bybit and 23.99% on Hyperliquid under the original fees, versus 8% in the script. Freeze one implementable policy and cost-aware expected holding horizon, then rerun. Past realized funding is an estimator, not locked future yield.
7. Historical spot-leg availability, wrapping, fee tiers, minimum sizes and liquidity are absent. A current spot listing cannot justify a historical same-venue hedge. Explicitly model external spot custody and transfer risk where needed.
8. Existing 2025–2026 observations were already inspected. They are historical validation, not an untouched holdout. Freeze a new configuration and evaluation clock; subsequently collected data is the clean prospective sample.
9. A negative-funding gate surviving one SOL episode does not prove safety. Remove claims that code caps tails or that a venue can always be flattened. Venue loss can remove all exposed capital.
10. A 4-week P&L ratio or eight-week annualized return within one sigma is a poor acceptance test when expected P&L is near zero and funding serially correlated. Test exact cash-flow attribution, residual delta, implementation shortfall and operational correctness; evaluate economic evidence with predeclared dependent-data confidence intervals and report insufficient evidence honestly.

## Primary literature checked

- [Borri, Liu, Tsyvinski and Wu, version 4](https://arxiv.org/html/2510.14435v4), section 3.6: confirms compressed carry and negative Sharpe for the 2025 part of its Binance BTC sample, which ends May 31, 2025. It discusses Ethena's dependence on funding; it does not establish the draft's causal claim that Ethena and basis ETFs crowded away the return. Remove that causal attribution unless separately supported.
- [BIS Working Paper 1087](https://www.bis.org/publications/working-paper-1087-crypto-carry): high carry reflects market frictions and risk, including margin/liquidation pressure. Useful economic mechanism, not a current expected-return estimate.
- [Zarattini, Pagani and Barbon, April 9, 2025 version](https://concretumgroup.com/wp-content/uploads/2026/02/Catching-Crypto-Trends.pdf): Table 4 reports 1.57 Sharpe for a long-only top-20 portfolio over January 2015–March 2025 with 10bp costs and a 20% rebalance threshold. Bitcoin cost sensitivities include 25/50bp, but the portfolio headline is not a demonstrated 1.57 across all costs. Aggregated CoinMarketCap data and historical asset availability require venue-level replication. Treat daily trend as a candidate, not the only credible directional family. Prefer spot long/cash for a first replication; perp trend must include actual funding expenses.
- [Autodeleveraging: Impossibilities and Optimization, version 3](https://arxiv.org/html/2512.01112v3): studies the October 10, 2025 ADL episode. Its abstract describes $2.1B as ADL closures, while its empirical introduction describes that amount as liquidations in the cascade. This review does not resolve that inconsistent labeling or use the amount as an ADL-specific estimate. The demonstrated forced hedge-removal mechanism matters here; the preprint is not a default-probability model or promise that collateral prevents ADL.

## Proposed research specification

Compare three implementable alternatives under the same total capital and cash benchmark: (A) no trading, (B) gated spot/perp carry, (C) dated-futures cash-and-carry where legally and operationally accessible. Dated futures fix a maturity basis more directly than forecast perpetual funding, but still introduce margin, settlement, fees and counterparty risk. Price its access and minimum sizes before selecting it. Keep directional trend in a separate risk mandate, never use it to rescue a failed yield sleeve.

Freeze symbol universe, information timestamps, training/validation windows, all tried configurations, allowed data exclusions, cost assumptions and benchmark before new results. Count variants in a research ledger. Use walk-forward windows for historical robustness, block-bootstrap confidence intervals for dependent daily excess returns, and multiple-testing correction when selecting among variants. Do not claim the bootstrap measures exchange-default risk.

Compute all-capital NAV in the user's chosen base currency. Attribute spot P&L, derivative P&L, funding, fees, slippage, borrowing, transfers, realized idle yield and fixed costs separately. Return benchmark uses accessible cash instruments with matched currency, liquidity and tax assumptions. Stablecoin earn has separate issuer/lending/venue risks and must pass due diligence; it is not risk-free.

Suggested promotion standard, to be frozen before implementation: no unresolved data/accounting defects; positive net excess economics after measured costs and an explicitly agreed risk premium; acceptable predeclared capital-loss stress budget; historical evidence remains positive under doubled modeled execution costs; no liquidation in the declared stress suite. Require a lower confidence bound above zero for claimed statistical evidence, or label evidence insufficient. Eight weeks may validate operations but cannot establish durable alpha.

## Reproduce and verify

```bash
python3 docs/research/crypto-review-2026-10-30/carry_audit_test.py
python3 docs/research/crypto-review-2026-10-30/carry_audit.py /path/to/funding.json
venv/bin/python docs/research/crypto-evidence-2026-10-30/realized_carry.py /path/to/funding.json 0.08
```

Eight deterministic tests/scenario evals pass, including signal lag, fee accounting, the cost-horizon contradiction, capital denominators and constant-funding cases. These validate this diagnostic, not a live strategy. No service restart is needed.
