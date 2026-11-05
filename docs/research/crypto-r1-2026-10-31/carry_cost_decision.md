# Carry cost screen and depth acquisition decision

November 4, 2026. Preserve the candidate rules from the [experiment specification](experiment_spec.md) for this development check. The spot-long/perpetual-short candidate uses seven complete UTC days of settled funding, a 00:05 UTC decision, a strict entry threshold of twice modeled trading costs plus other costs, and a three-day negative-funding or 28-day holding exit. The provisional sizing and entry timing remain in the specification. The R2 lock remains conditional.

The question is whether additional order-book data can change the entry decision under the provisional fees. Set spread, impact, fixed and opportunity costs to zero to give the funding proxy its most favorable case within this fee scenario. Assume equal fee-bearing notionals on the four executions. The published VIP 0 taker rates are 10 bps for spot and 5.5 bps for perpetual per execution. Two entries and two exits total 31 bps per unit of matched notional. The existing two-times buffer requires a seven-day proxy strictly above 62 bps. These are public scenario rates and the actual account rates remain unknown. [Bybit fee schedule](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure)

| Symbol | Decision dates | Maximum seven-day funding proxy | Maximum round-trip cost permitted, exclusive | Passes at 31 bps |
|---|---:|---:|---:|---:|
| BTCUSDT | 83 | 15.9159 bps | 7.95795 bps | 0 |
| ETHUSDT | 83 | 17.9604 bps | 8.98020 bps | 0 |

Both maxima occur on August 26. The decision dates are August 9 through October 30, inside the catalog window. Each sum uses timestamps in the seven complete preceding days and excludes the decision day's midnight settlement. All 83 per-symbol observations pass at zero trading cost, and none passes at 15, 24, 31 or 62 bps. Windows overlap. These are counts of descriptive proxy evaluations, with no statistical independence assumed.

This is a funding-only screen. It does not measure realized P&L, basis changes, fees at actual prices, fills, or historical availability of each settlement at 00:05. The raw snapshot establishes event timestamps and later retrieval. The independent check also included the October 31 decision, which has a complete trailing window but falls outside the catalog dates. It reached the same conclusion.

**Acquisition decision.** Defer the remaining depth download for this exact fee scenario. More precise spread and impact estimates cannot rescue a modeled entry that already fails with both set to zero. Revisit when verified account fees and the chosen execution policy put all-in cost within the observed ceiling, or when a separately specified candidate needs depth for a different question. Preserve October 30 and August 2 as development fixtures. An archive sample selected around a known funding peak is useful for diagnosis and cannot serve as an unbiased performance sample.

The fee-only result is specific to the existing entry rule and this 90-day sample. Reducing the buffer, assuming maker fills, extending holding duration, or adding a basis forecast creates a separate hypothesis. Multi-agent signal research remains a separate comparison with deterministic and single-agent baselines. It must earn its incremental value after costs.

[Deterministic results](carry_cost_screen.json) include the two series, source-response hashes and all five cost cases. Reproduce with:

```bash
python3 docs/research/crypto-r1-2026-10-31/carry_cost_screen.py \
  data/research/crypto-r1/bybit-90d-20261031/raw /tmp/r1-cost/reproduced.json
cmp docs/research/crypto-r1-2026-10-31/carry_cost_screen.json /tmp/r1-cost/reproduced.json
python3 -m unittest discover -s docs/research/crypto-r1-2026-10-31 -p test_carry_cost_screen.py
```

Independent review passed at `/tmp/r1-cost/critique/final.md`. The raw-data replay matched the maxima and pass counts. The JSON reproduced byte for byte, and tests caught four mutations of the threshold and boundary rules. Self-rating 9/10. Proud of the acquisition decision. Account fees and historical availability remain unverified. No restart required.

November 5 follow-up: [all seven published fee tiers and 16 execution assignments](fee_ladder_decision.md) preserve the depth deferral for the all-taker candidate.
