# Two frozen existing binary rules

Outcome: supply two auditable deterministic shadow policies while root gathers actual practice offers, orders and broker settlement. Neither rule has verified economic edge. This service contains no network, account, broker, sizing or order code.

Slots2 and3 of the six-policy development budget are `legacy_mhi3_causal` and `legacy_exhaustion_causal`. Rules were frozen on9 November2026 before any historical scoring. The definition digest is `a0d523554539cd6cc3fa86f4f12d9dcbadf1c292c58fb5ffd10bb69a746405e7`. `frozen_rules.json` contains exact thresholds, indicator definitions, clock bounds and source references. The initial source lock was written before the historical admission audit. The user subsequently expanded execution to other broker-listed active OTC assets; `execution_scope_amendment.json` preserves that instruction without changing historical two-asset results or thresholds.

## Boundary

```python
from services.otc_deterministic_strategies import Candle, Offer, Quote, decide

signal = decide(
    'legacy_mhi3_causal', asset, decision_ns, offer, quote, candles,
    allowed_assets=frozen_broker_discovered_otc_names,
)
```

`allowed_assets` must be an immutable tuple of unique named `-OTC` assets. The default remains `EURUSD-OTC` and `GBPUSD-OTC`. Supporting another broker-validated asset is an execution interface, not evidence that historical results generalize. The caller must independently admit the asset's active broker offer and pin the entire practice universe.

`Candle` records exact start/duration milliseconds, receiver nanoseconds, broker time at receipt, OHLC, finalized boolean and clock status. `Offer` records asset/product, receiver nanoseconds, broker receipt clock, net winning payout, actual offered absolute expiry, purchase deadline, active boolean and supported status. `Quote` has the corresponding asset, receipt/clock and price. These data cannot be inferred from a stale screen or from the eventual outcome.

The strategy uses29 causally finalized contiguous2m bars. A bar must have been received by the decision and reported by the broker after its exact close. Future or forming OHLC never enters calculations. Every causal finalized record for the selected asset is checked against its `(start_ms, received_ns)` identity before eligibility filters and latest-version selection. Contradictory records at the same identity raise `InvalidInput`, even if a later revision exists or the identity is outside the final29 bars. Identical duplicates remain valid. Different receipt instants remain distinct revisions, and the latest eligible version per start is used. Future, forming and unrelated-asset records do not enter the identity set. Missing/gap/stale prefixes abstain. Clock offset is capped at15s; quote age5s and offer age600s use physical nanosecond differences rounded upward to milliseconds. Negative offer state overrides a still-fresh payout. Payout must be at least0.80; offered holding time must be90–150s and its purchase deadline must remain ahead of broker time. Root owns the actual offered-expiry mapping and final pre-order checks. These bounds do not prove the broker will accept the request.

The corrected source version preserves full integer derived broker nanoseconds for purchase cutoff, holding duration and closed-candle staleness. It admits exactly90s and150s, rejects90s minus1ns and150s plus1ns, and never floors elapsed receiver nanoseconds before these comparisons. Clock offset compares `abs(broker_at_receipt_ms * 1000000 - received_ns)` directly to15000000000ns: exactly15s in either sign is allowed, while15s plus1ns is rejected. `source-lock-v5.json` records these repairs, the complete finalized-identity check and numeric exception normalization; rule thresholds and trial slots remain fixed. The exact-nanosecond eval rejects isolated old holding-floor and clock-offset-floor mutants. The identity eval checks all six old-conflict/later-revision permutations both inside and outside the feature window. It also rejects the preserved v3 latest-version-only implementation and an isolated mutant that narrows identity checks to the feature window. Prior source locks and reports remain preserved as earlier version evidence.

The exported `decide` contract rejects huge exact integers that cannot be checked in the supported finite numeric range with `InvalidInput`. Finite input prices may still overflow a legacy indicator calculation; arithmetic failures in that calculation also become `InvalidInput`. Unrepresentable canonical JSON evidence uses the same rejection. Ordinary finite values, the maximum finite quote price and all rule arithmetic/thresholds keep their original semantics. The numeric stress eval covers both natural Exhaustion directions, randomly scaled positive finite OHLC, huge signed integers and every numeric entry field; isolated mutants restore each escaping-exception path. Root must record `InvalidInput` as an abstention. Rejection does not establish that a lower price magnitude is economically valid.

`Signal` returns direction or abstention, a reason, input evidence hash, exact requested expiry and optional legacy MHI score. That score is a heuristic threshold score, never calibrated confidence. `capital_permission` is always false. Invalid typed or nonfinite data raise `InvalidInput`; root must treat that as abstention. The service never places an order.

MHI preserves three-bar minority color, body/doji bonuses, reversal-profile RSI guards and score65 cutoff. Exhaustion preserves calm RSI30–70, BB position outside0.10/0.90, stochastic K confirmation, body ratio at most0.60 and ADX at most40. Optional5m context is disabled explicitly. Both use the source tag's exact RSI seeding/smoothing, including its overlapping seed window; changing to textbook Wilder initialization would consume a new policy version rather than being silently called the same rule. No rule means a broker manipulates wicks or that an indicator threshold estimates win probability.

## Verification

From the package root, run the local gate:

```bash
python3 -m unittest discover -s services/otc_deterministic_strategies/tests -t .
```

Before shipping, run the periodic deterministic eval with a new output path:

```bash
python3 -m services.otc_deterministic_strategies.evals.eval_policy --repository /home/saviour/PycharmProjects/I2/IQoption --output /tmp/otc-existing-policy-eval.json
python3 -m services.otc_deterministic_strategies.evals.eval_ns_admission --output /tmp/otc-existing-policy-exact-ns-eval.json
python3 -m services.otc_deterministic_strategies.evals.eval_candle_identity --output /tmp/otc-existing-policy-candle-identity-eval.json
python3 -m services.otc_deterministic_strategies.evals.eval_numeric_contract --output /tmp/otc-existing-policy-numeric-contract-eval.json
```

It checks2000 seeded candle prefixes against pure strategy/function ASTs extracted from the pinned local source tag. It never imports the old bot or invokes a broker. It compares four indicator calculations, both rule directions, future-price perturbation invariance, negative-offer override and missing-contract abstention. The pass threshold is100%. Synthetic signal counts validate implementation only and are not wins, returns or true edge.

Historical admission is a separate read-only command:

```bash
python3 -m services.otc_deterministic_strategies.evals.historical_admission --candles /home/saviour/PycharmProjects/I2/IQoption/data/ml/historical_candles.sqlite --context /tmp/binary-training/resume-data/source_snapshot.sqlite --output /tmp/otc-existing-policy-historical-admission.json
```

The historical sources contain prices, receiver timestamps and payout samples but lack complete causal positive/negative offer state, actual offered expiry and accepted strike/cash settlement. Therefore the full practice-policy economic comparison is `BLOCKED_FOR_ECONOMIC_EVIDENCE`. Missing eligibility is retained instead of assumed active. No partial Nov7–14 fresh cohort is read, fitted or retuned. The next useful measurement is frozen shadow decisions paired with root's actual practice capture, followed by a separately frozen future comparison.

## Source selection

The implementation reuses the user's source tag `otc-binary-final-2026-10-30`, commit `c734f34e6a976c1552daf213ebb462b3a95c7094`. SHA256 values of MHI, Exhaustion and indicator source are in `frozen_rules.json`. The user owns this repository; no third-party strategy code was copied. Its archived tiny-sample win claims are not retained as evidence.

Primary GitHub metadata is saved in `repo_sources.json`. As observed9 November2026, the community [iqoptionapi](https://github.com/iqoptionapi/iqoptionapi) repository has276 stars,55 open issues, latest default-branch commit31 January2022 and last push12 August2024. It is an API reference, not a validated strategy. [alcidesmig/mhi-iqoption-bot](https://github.com/alcidesmig/mhi-iqoption-bot) has2 stars, GPL3 license and latest default-branch commit19 July2020. [octaviodegodoy/algo_binary](https://github.com/octaviodegodoy/algo_binary) has0 stars, MIT license and latest commit4 August2022. [josepholasoji/IQ-Options-AUTO-Trader](https://github.com/josepholasoji/IQ-Options-AUTO-Trader) has1 star, no API-reported license, latest commit10 November2025. None provides matched causal OTC contract evidence sufficient to replace the known local definitions. This is why existing local rules were selected as auditable replicas rather than installing another bot.

[MHI cataloger video](https://www.youtube.com/watch?v=vnoJp76WbtQ) and [MHI technique video](https://www.youtube.com/watch?v=-81HageS00c) were found as technique references. They supply hypotheses only; no video win rate is treated as evidence. External code is not installed or executed, and strategies from conventional FX or TradingView perpetual-position backtests do not transfer automatically to fixed-payout OTC contracts.

Restart: none for this pure library. Root must freeze and deploy a separate prospective practice version before integrating another strategy into the running bot.
