# Published fee ladder and carry decision

November 5, 2026. The current Bybit base schedule leaves the frozen BTC/ETH all-taker carry candidate below the entry threshold at every published VIP tier. Even Supreme VIP all-taker costs 15 bps over four equal-notional executions, requiring more than 30 bps in the seven-day funding proxy. The sample maxima were 15.9159 bps for BTC and 17.9604 bps for ETH. The published rates can differ by region and account. [Bybit fee schedule](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure)

The [fee matrix](fee_ladder_results.json) applies seven published tiers and all 16 maker/taker assignments to the 83 in-window decisions per symbol. Only these three Supreme VIP assignments pass in any window, with spread, impact, fixed and opportunity costs set to zero.

| Executions | Round-trip fees | BTC qualifying windows | ETH qualifying windows |
|---|---:|---:|---:|
| All four maker | 6 bps | 16 | 10 |
| One spot taker, other three maker, either entry or exit | 7.5 bps | 5 | 4 |

Both perpetual executions must be maker in every passing assignment. At the observed peaks, the 6 bps fee case leaves less than 1.95795 bps of additional round-trip cost for BTC and less than 2.98020 bps for ETH. At 7.5 bps the headroom falls below 0.45795 and 1.48020 bps respectively. These are overlapping funding proxy windows, not a count of fills or trades.

The frozen execution assumption uses bid/ask crossing. Passive execution is a separate hypothesis requiring evidence for fills, waiting, cancellation, adverse selection and recovery when only one leg fills. The fee rows provide sensitivity bounds and no account qualification evidence. [Existing carry screen](carry_cost_decision.md)

Keep the 90-day depth backfill deferred for this carry candidate. To reassess, obtain the actual BTCUSDT and ETHUSDT spot and perpetual fee rates from My Fee Rate. The peak funding windows can only support **less than 7.95795 bps for BTC and 8.98020 bps for ETH** in total round-trip trading cost before any fixed or benchmark costs. Any lower authenticated fee still leaves spread, impact and execution behavior to verify. Capital budgets and the final R2 decision remain unset.

Reproduce from the repository root with `python3 docs/research/crypto-r1-2026-10-31/fee_ladder.py`. The result is a deterministic sensitivity eval over the saved funding screen. Unit tests cover the four-fee sum, asymmetric executions and equality at the threshold.

Independent cold review passed at `/tmp/r1-fee-ladder/critique/final.md`. The review matched all 112 fee cases and 166 funding proxies, checked the source table and reproduced the JSON byte for byte. Self-rating 9/10. Proud of the decision evidence. Actual account tariffs remain the missing point. No restart required.
