# Binary OTC: an edge search worth implementing

Date: 5 November 2026. Deliverable: proposal challenge and implementation specification. Status: **RESEARCH ONLY; proposed implementation.** This document does not authorize broker orders, deposits, production changes or a collector restart.

**Recommendation:** keep pursuing binary with a smaller, better measured experiment. Build trustworthy observation and contract-aware research, select one policy, then test it on untouched forward data. The archive does not justify restoring the old scanner. It also does not prove that every possible OTC strategy must fail.

**The best current lead is the frozen crowd-fade band, but it has no demonstrated economic edge.** The most useful new searches are received-time lead/lag between OTC feeds and genuinely new public deal information. Correct expiry/strike labels and payout-aware abstention are prerequisites for testing those leads, not discoveries of predictive advantage.

This plan supersedes the proposed future workflow in [30 October research direction](../research/otc/2026-10-30-research-direction.md) for the next cycle if adopted. It does not rewrite past registrations or results. Its main changes are explicit offered-expiry semantics, a variable-payout audit counterexample, a smaller development budget, one independently selected forward champion, and a sample-size/throughput feasibility gate.

## What the evidence actually says

Source code reference: git tag `otc-binary-final-2026-10-30`; current-code base: `aa14db0f8cf5fb70e81c6bb45a561810f0c3fa38`. Archived data remain local under `data/archive/otc-binary-2026-10-30/research/` in the original checkout. The managed plan worktree contains no copy of those large artifacts. A separate agent recomputed saved counts and per-row returns; it did not connect to the broker or train models.

| Evidence | Sample | Result | What it supports |
|---|---:|---|---|
| Run 1 best return, meta contrarian / 120s | 414 wins / 767 selected rows | 53.9765% wins; -0.1434% per stake at assumed 85% payout | No pass; even its point return is negative |
| Run 2 best pooled win rate, logistic | 4,765 / 9,160 | 52.0197%; -3.7636% per stake if payout is 85% | Better accuracy than some alternatives still loses |
| Round 3 LightGBM, nominally unseen | 38,162 / 74,088 | 51.5090%; saved per-row return -5.0436% | Negative replay, every reported unseen week negative |
| Round 3 logistic, nominally unseen | 4,029 / 7,768 | 51.8666%; saved per-row return -4.2279% | No candidate despite selective trading |
| Older post-selected crowd band | Reported 9,794 rows | Approximately 54.9% wins | A discovery lead chosen after looking at the holdout |

Run 1 has 14 configurations, Run 2 has nine families, and Round 3 has four policy slots including an empty grid. All fail their report gates. These are overlapping experiments, not independent replications. The README's “32 strategies” needs a complete inventory before repeating it as an audited count.

The Round 3 trade parquet recomputation matched report counts, win rates and mean PnL to absolute tolerance 1e-12. This checks accounting within the saved simulation. It does not validate input causality, accepted strikes or live execution. The 74,088 LightGBM unseen rows contain only 16,762 distinct target times across 15 assets. They cannot all be treated as independent bets or as a feasible one-position portfolio.

Some Run 2 models have a small measured log-loss improvement while still losing money. Therefore “the data contain no learnable information” is too strong. The supported conclusion is **no demonstrated tradable advantage under the tested information, selection and execution assumptions**. Likewise, correcting invalid tests might strengthen a rejection; it is not evidence that a hidden profitable system will appear.

The old 54.9% crowd result deserves especially little optimism: later band summaries show stronger values in already-seen periods and roughly 51% in unseen periods. Those CSV summaries contain rounded win rates and average payouts, insufficient to reconstruct payout/outcome covariance. Keep the exact old band as one replication candidate, with no fresh claim of profitability.

## The defects to fix before asking a model for more accuracy

References marked **archive** are paths at the tag, inspectable using `git show otc-binary-final-2026-10-30:PATH`. They are not current imports.

| Severity | File / code | Problem and required change |
|---|---|---|
| Critical for economic approval | Current `trading_platform/research/validation/edge_audit.py`, `audit_trade_log:126-141` | Averages quoted payouts, then compares pooled win rate against that average. A synthetic 10,000-row ledger with 60% wins paying 55%, and losses quoted at 95%, passes its Wilson gate while losing **7% per stake**. Compute each contract's cash return. Do not use this helper as the new promotion judge. |
| High | Archive `trading_platform/research/studies/otc_tick_settlement.py:19-25`; `trading_platform/vendor/iqoptionapi/iqoptionapi/expiration.py:15-46` | The screen settles at entry +120s. The adapter selects offered minute expiries, using a purchase cutoff and local wall clock. Same supplied timestamp, same duration=2: the helper selects a 91s hold, or a 151s hold after a 2s clock shift. Reproduce actual offered/accepted UTC expiry rather than inheriting the helper's wall-clock dependency. |
| High | Archive `trading_platform/scripts/harvest_market_data.py:554-555`; `trading_platform/research/studies/otc_crowd_study.py:92-94` | Payout received at second 250 can be bucketed to zero and joined to a second-120 decision. Export true receipt/clock provenance; bucket time is not availability. Measure affected joins from raw timestamps. Existing bucket-only CSV cannot recover them. `INSERT OR REPLACE` may also have overwritten arrivals within a bucket; mark unrecoverable history rather than reconstructing it by guesswork. |
| High | Archive `trading_platform/research/studies/otc_feature_matrix.py:139`, followed by `trading_platform/research/studies/otc_crowd_study.py:89` | Future dojis remove assets before cross-asset mood is calculated. Another asset's future outcome can change this asset's present features. Build features from the available universe before joining labels. |
| High | Archive `trading_platform/research/studies/otc_crowd_study.py:94`; `trading_platform/research/studies/otc_feature_matrix.py:41` | Missing payout becomes 0.85; mood aggregation drops product identity. Unknown/stale/conflicting payout must abstain. Never mix turbo, binary and digital populations implicitly. |
| High | Archive `trading_platform/research/studies/otc_tick_settlement.py:37,39,45` | Full-period extreme thresholds/scaling and test-population confidence quantiles use unavailable future distributions. Fit transforms and selection thresholds on development only. |
| Medium | Archive `trading_platform/research/studies/otc_tick_settlement.py:23-27` | Missing lag/entry/expiry samples are excluded, but missing intermediate seconds need not be. The claimed continuous tick screen is stronger than its check. Report continuity explicitly and admit each feature according to its actual data requirements. |
| Medium | Archive `trading_platform/strategies/otc/strategy_engine.py:10-29,130-158` | Three score systems and win-rate-driven weights can obscure what produced a decision. Strategy agreement is correlated evidence; heuristic confidence is not calibrated win probability. Replace with one frozen policy and one qualification result. |

These are code behaviors or demonstrated counterexamples. Their prevalence and PnL impact in the historical dataset remain to be measured. An adapter helper is also not proof of what today's broker actually accepts. The old `BinarySettlement` domain contract is useful, but it assumes full-stake refunds for ties/voids; verify the product terms before reuse.

## The economic edge and the information edge are different

For a unit stake, use `X = net winning payout` on a win, `X = -1` on a full loss, and `X = 0` on a full refund, less any actual fee. Authoritative accounting is `(gross returned cash - stake - separately charged fee) / stake`; do not subtract a fee twice if the returned cash is already net. A tie follows the verified contract rule, not a global assumption. Track unresolved outcomes separately.

With constant net payout `r`, no fees and no refunds, `EV = p*r - (1-p)`, and break-even is `1/(1+r)`. With full refunds, use `p_win*r - p_loss`; decisive-trade win rate and the return over all accepted trades have different denominators. Variable payout requires actual per-trade returns, not average payout multiplied by pooled wins.

| Net win payout | Break-even decisive win rate | EV at hypothetical 54.9% wins |
|---:|---:|---:|
| 70% | 58.82% | -6.67% |
| 80% | 55.56% | -1.18% |
| 82% | 54.95% | -0.082% |
| 85% | 54.05% | +1.565% |
| 90% | 52.63% | +4.31% |
| 95% | 51.28% | +7.055% |

These are arithmetic illustrations, not a forecast from the old crowd result. Higher payouts can improve expectancy without changing accuracy. In actual data, payout and outcomes may be related, so replay the joint policy instead of transplanting the same hypothetical win probability between payout buckets.

The opportunity is **selectivity with evidence**: trade only states where calibrated conditional return clears a fixed margin at the observed offer, while reporting how many opportunities survive. Compare policies at matched coverage and expiries. A model's “90% confidence,” a late candle already looking green, or ten indicators agreeing supplies no standalone probability guarantee. At entry, the relevant price is the accepted strike, so being ahead of the candle's old open is not a head start on the new option.

A useful new constraint is statistical throughput. The standard IID normal approximation, at 85% payout, one-sided alpha 0.05 and 80% power, gives:

| True return per stake to detect | Corresponding win probability | Approximate independent trades |
|---:|---:|---:|
| +1% | 54.5946% | 52,519 |
| +3% | 55.6757% | 5,827 |
| +5% | 56.7568% | 2,094 |

These are explanatory estimates, not the final sample calculation. Dependence, sparse opportunities, execution stress and the full promotion rule change the requirement. The +1% example alone needs about 584 independent trades per day over 90 days. A rare band cannot be validated by promising “1,000 trades.” Estimate power using the **one-position selector's actual throughput** before committing to the forward run. Prioritize a stronger, repeatable subset if the weak effect is infeasible; changing that subset must happen in development, not after observing confirmation outcomes.

## Three searches, ranked, with ways to kill each one

Start with the two broker-offered expiry policies corresponding to the archived 2-minute and 5-minute requests, only after their mapping is verified. Store absolute expiries and actual remaining seconds. This preserves the link to prior evidence. The proposal's 1-minute/3-minute choice has no superior repository evidence. Faster expiries require a new cycle and better timing data.

The development budget is **six evaluated complete policies: three information families times two expiry policies**. Record the exact features, estimator settings, transforms, cutoff, asset universe, entry schedule and tie-breaker before evaluating each slot. A threshold sweep, flipped direction, extra model or asset/hour slice is another policy, not free analysis. If one is needed, allocate one of the six slots before running it; do not automatically fill all family/expiry combinations. Choose parameters from prior evidence or a documented development-only mechanism study. All such exploratory findings remain development evidence. Log abandoned and failed evaluations too.

| Priority / hypothesis | Specific experiment | Falsification / exclusion |
|---|---|---|
| 1. Frozen crowd fade with actual payout | Preserve `0.30 <= abs(call_fraction - 0.5) < 0.45`; CALL below 0.5, PUT above. Preserve source/product identity and receipt time. Reproduce without retuning; measure fixed-rule return before adding any trained selector. Payout/freshness/expiry eligibility is part of the registered policy. | Kill if corrected development and subsequent confirmation fail economics. Do not interpret mood as actual money, complete crowd participation, or proof of broker manipulation. Degenerate samples are invalid under the inherited band, but “zero volume” remains an unverified explanation. |
| 2. Received cross-asset response | On continuous new ticks, test whether a past move in another OTC feed predicts this feed's return after its own accepted-entry delay. Use one regularized linear/logistic model with a small, frozen set of received-time lag features. Cluster duplicate/common feeds first. | Kill if the apparent lead is just different receipt delays, simultaneous correlation, one session, or if p95 acceptance delay consumes it. Require an improvement over the same asset's price-only baseline and all-asset block-shift controls. Never substitute external FX for OTC prices. |
| 3. Public count/amount disagreement | Only if a permitted endpoint exposes documented event identity, product, side, amount and arrival. Compare count imbalance with amount imbalance, then test later quote response against price + mood alone. | Previous inspection reported zero recorded public-deal events. If the feed, semantics or usable coverage is absent, this family is unavailable. No inferred order book, no “institutional flow” claim, and no automatic replacement search. |

Momentum, MHI/streak patterns, BB/RSI reversion, candle anatomy, crowd follow/fade ML, LSTM/GRU/TCN/transformers and ensembles have already had meaningful exploration. Keep constant CALL/PUT, seeded random direction, one simple price rule and NO TRADE as fixed diagnostic controls. Controls cannot be promoted without becoming registered candidates. User-approved refinement on 5 November: once causal data and targets are repaired, CatBoost may compete directly with the simple benchmark. It does not require prior linear profitability. LSTM remains a later, separately registered comparison on reliable sequences. There is no model sweep in the initial scope.

## What to remove, retain and defer

| Decision | Components |
|---|---|
| Remove from the proposed runtime | Two-AI branding/debate, learned AI2, strategy voting and live weight adaptation, three competing score systems, martingale/recovery staking, default payout, synthetic order flow, per-trade LLM narratives, unrestricted self-learning and mutable Telegram risk/account switching |
| Retain | NO TRADE, raw observation provenance, explicit contract clock/strike, deterministic qualification and independent risk veto, uncertain submission state, no blind retry, broker-authoritative cash reconciliation, one frozen policy version |
| Defer | Full execution service until a promising development result; any live capital until fresh practice evidence and explicit approval; deep networks, RL, GPUs, multi-broker abstractions, Rust, distributed messaging, Postgres migration, Grafana, custom agent orchestration and scheduled retraining |
| Simplify process | One experiment manifest, one numeric report, one independent review at a phase boundary; event-triggered health alerts. Agents investigate offline. No five-agent meeting or approval ritual for every signal. |

Use Python, SQLite, NumPy/pandas and scikit-learn. The standard libraries handle clocks, immutable records, hashes and accounting fixtures. Prefer existing reviewed `arch` bootstrap primitives for dependent inference when the implementation needs them. Keep broker-specific contract replay small because ordinary buy/sell position backtesters do not implement this payoff/expiry contract. Reuse domain invariants and read-only archive patterns selectively; importing the old scanner would restore its coupling.

The 5 November GitHub API snapshot returned scikit-learn 68,020 stars / last push 4 November; arch 1,667 / 5 November; iqoptionapi 276 / August 2024; Lu-Yi-Hsun fork 391 / July 2026. Push dates are not verified substantive code dates; stars are not reliability or profitability evidence. The [30 October dependency review](../research/otc/2026-10-30-github-review.md) contains issue/source review. No new adapter is endorsed based on popularity. Before dependency installation, pin and check its current source/license and run contract tests. The available public material does not establish this account's automation permission or current endpoint reliability.

## Two service directories now, a third only when earned

```text
contracts/otc_v1/                immutable event, offer, decision and cash schemas
services/otc_observer/           import, recorder, dedicated SQLite, immutable export, health
services/otc_research/           features, expiry replay, six trials, calibration, judge
services/otc_execution/          later: practice adapter, risk veto, reconciliation
```

Each service owns its code, config, tests, evals and README. Exchange versioned immutable records and exports; never share a mutable SQLite database between services. No HTTP service mesh is needed. OTC writes only its dedicated directories/databases and branch. The concurrent crypto session owns current crypto services and deployment. Shared contract changes need an explicit version bump and coordinated migration; copying crypto business logic into the OTC directory is not the reuse strategy.

`contracts/otc_v1/events.py` must define:

- **Observation:** version; broker, account mode where relevant, asset, product, source; stable event identity; source timestamp if supplied; local receipt UTC plus monotonic sequence; broker-clock offset and uncertainty; precision; raw-payload hash; quality flags. Never overwrite multiple arrivals in a bucket. Reject non-finite or invalid numeric data.
- **Offer:** observation ID; product/asset; absolute expiry UTC; latest purchase UTC; net winning payout with explicit ratio units; source/age; verified tie rule. An indicated percentage and gross payout are different fields.
- **Decision:** policy/data hashes; cutoff and triggering observation; feature/evidence IDs; direction or abstention; offered expiry; payout snapshot; qualifying margin and reasons. Freeze deterministic global selection, including an asset-ID tie-break, and one outstanding position.
- **Acknowledgement:** client/broker IDs; proposed/submitted/accepted times; exact accepted strike, expiry, stake and contractual payout when provided; response hash. Missing fields stay missing. Receipt time is not silently relabeled broker acceptance time.
- **Settlement:** authoritative outcome/cash/fees/currency and source evidence, or explicit unresolved state. Preserve rejected, timeout, refund and void outcomes in the ledger. A broker cash verdict is authoritative even when chart quotes cannot explain it; an unexplained discrepancy blocks promotion.

Availability is defined by the receipt sequence at the decision, with explicitly bounded clock conversion for broker offers. Older source timestamps never make late messages available earlier. Features use the as-of available universe; labels join afterward. Purge whole overlapping outcome intervals across all assets at split boundaries. Fit scaling, imputation, calibration and thresholds inside training/validation only.

Proxy replay uses an explicit offered expiry and the first valid causally received quote at/after a predeclared delay, with a maximum age/wait and no interpolation across missing boundaries. It is a **quote proxy**, even after using the right expiry. No post-decision missing settlement may delete an already-selected trade. Report unresolved fraction and conservative return bounds; no PASS with unresolved accepted practice contracts. Skip conditions must be known at decision time.

## Implementation units and acceptance criteria

All paths below are proposed files, not a claim that the services exist. Units 0 and 1 can run in parallel after the schema is frozen. Subsequent dependencies are explicit.

| Unit | Exact work and artifacts | Gate tests and periodic eval | Done when |
|---|---|---|---|
| 0. Evidence repair, first | `contracts/otc_v1/events.py`; `services/otc_observer/archive_import.py`; `services/otc_research/audit.py`, `accounting.py`, `availability.py`, `universe.py`; JSON provenance/contract-gap report. Read raw archive without modifying it. | Future payout unavailable; future-other-asset doji cannot change feature; products isolated; unknown payout abstains; tie retained; correlated payout example loses 7%; all recorded decisions accounted. Eval on corrupted and clean export fixtures plus archived result reproduction. | Every admitted field has provenance; old report counts/returns reproduce; affected joins and before/after results reported where raw data allow it. Missing receipt/contract data explicitly blocks execution claims. No model training. |
| 1. Fresh observation | `services/otc_observer/adapter.py`, `recorder.py`, `store.py`, `health.py`; dedicated DB and feed/offer inventory. Permission/account integration check precedes a connection. | Replay reconnects, duplicate IDs, clock jumps, stale/conflicting payouts, late data and process restart. Eval a 24-hour recorded/permitted practice feed: every gap detected; feature-specific continuity/age eligibility enforced. | True receipt events and explicit expiry offers persist reproducibly. Coverage and permitted product scope are known. Public flow is marked present with semantics or unavailable. A production collector restart still requires a concrete approval. |
| 2. Causal replay | `services/otc_research/expiry.py`, `features.py`, `replay.py`, `controls.py`; depends on 0 and offer inventory from 1. | Cutoff -1/0/+1ms, hour/day boundaries, two-second clock skew, acceptance crossing cutoff, changed payout, ties/precision, missing boundaries, same-time assets, one-position selection. Eval future rewrite, null data, injected-edge and delayed-entry fixtures. | Zero unexplained fixture mismatches; all proxy outcomes labeled as proxies; feature/decision hashes invariant to future edits. Baseline and abstention reports reproduce. |
| 3. Bounded development | `services/otc_research/cycle-1.json`, `policies.py`, `calibration.py`, `evaluate.py`; depends on 1/2. | Trial cap rejects extra variants; train-only transforms and cross-asset purging. Eval new-information ablations, calibration, payout/latency stress, coverage and repeated time folds. | All tried policies reported; either none merits continuation, or one champion and scope selected. Development evidence alone never enables orders. |
| 4. Practice contract validation | `services/otc_execution/practice.py`, `risk.py`, `history.py`; depends on promising 3, verified integration and separately authorized practice order scope. | Timeout enters UNKNOWN with no retry; duplicate responses settle once; restart reconciles before order; minimum stake/risk, stale cash and manual kill. Eval capture/replay against actual accepted contracts and cash. | Zero unexplained strike/expiry/cash discrepancies in available fields; no unresolved accepted contracts. Record missing fields and rejection/latency distributions. If required fields cannot be verified, stop economic promotion. |
| 5. One fresh confirmation | `services/otc_research/forward_protocol.json`, `judge.py`, `report.py`; depends on 3/4. | Changed hashes, extra look, insufficient blocks/coverage, unresolved outcome or missing stress assumptions prevent PASS. Eval seeded dependent null and positive-edge ensembles for error/power; run the locked end-date judge. | PASS, REJECT or INCONCLUSIVE under the frozen rules below, with raw decision-to-settlement lineage and a reviewable report. |

Gate tests: deterministic local fixtures, target under two seconds per service. Larger historical replay and statistical sensitivity work belong in periodic evals. Do not pretend that an injected positive edge proves a real edge. Use at least 2,000 fixed seeded repetitions per registered null/alternative class. For the null eval, require the one-sided 95% binomial upper bound on erroneous PASS frequency to be at most 6.5% (nominal test size remains 5%); for the declared useful-effect alternative, require the corresponding lower bound on detection power to be at least 80%. Include serially clustered and changing-payout null classes, not only IID coins. Record counts and bounds; a single lucky simulation is not a harness validation. Freeze generators before testing the judge, and reject the judge if a class fails rather than selecting a friendlier generator. If an LLM proposal workflow is later added, use the required local Claude service and separate prompt-quality evals. The numerical judge requires no LLM or paid API.

For unit 0 specifically, start with a read-only manifest of source tag, file hashes, table schemas and event counts. Import a deterministic bounded fixture without raw broker secrets. Produce `audit.json` containing `reproduced_legacy`, `availability_known`, `future_join_count`, `product_collision_count`, `unknown_payout_count`, `contract_fields_present`, and `blocked_claims`, with denominators for every rate. If raw timestamps are unavailable, report `future_join_count: null` and the reason; zero is not an acceptable substitute. Before/after calculations operate on matched opportunity IDs and show excluded/changed rows, rather than comparing different populations silently.

## A single forward judge, and an honest stopping rule

**Choose one champion entirely before fresh confirmation.** Six development trials do not require six final Bonferroni tests when only one locked policy meets genuinely untouched future data. The fresh cohort must not be used to tune selection, choose assets, retrain, recalibrate or pick between policies. If more policies or positive-evidence looks are requested, register a new joint error budget before collecting their future outcomes. Preserve the old registrations as historical documents.

Before the start, freeze the source/policy/data hashes, asset universe, exact expiry policy, decision schedule, signal expiry, payout source/floor, calibration evidence, global selector, fixed stake convention, clock/age bounds, tie rules, delay/rejection assumptions, stress cases, minimum coverage and maximum unresolved fraction. Rules used to choose data-quality limits must be fitted on development and frozen too. An individual predicted probability is not a confidence interval: any conservative probability/return estimate must come from supported validation groups or a specified block-resampled calibration procedure, with unsupported states abstaining.

Use **one fixed future calendar interval**, at least 30 observed trading days and 30 nonoverlapping inference-length blocks, subject to a maximum 90 calendar days. These are minimum guardrails, not proof of independence or adequate power. Before collecting confirmation, use development-only block simulation of the complete one-position policy and composite pass rule to require at least 80% power for the declared useful effect, initially +1% net PnL/stake. Freeze the resulting end date/sample/coverage requirements. If that cannot fit the budget, stop as infeasible for this effect/throughput; do not lower the effect, extend the test, or alter the selector after looking at forward results. A stronger target or different sparse policy must be registered as a development decision first.

For definitive **practice economic evidence**, the confirmatory cohort must consist of all accepted practice contracts generated by the frozen selector, with actual accepted payout and broker cash settlement. Practice authorization and feasible permitted order rate are prerequisites. Shadow quotes can run alongside as paired diagnostics. A shadow-only cohort can graduate to practice investigation, but its positive proxy return cannot receive the economic PASS below. This distinction prevents “validated simulator” from turning hypothetical strikes into observed fills.

Primary estimand: mean net cash PnL per unit staked over all accepted contracts under the one frozen policy, including refunded/voided contracts and actual fees. In the fixed-stake experiment also report total cash PnL, daily PnL, win rate among decisive outcomes, refund/unresolved/rejection fractions, offered vs accepted payout, coverage and accepted trades/day. Keep rejected opportunities in the decision ledger; report return per eligible opportunity/calendar day to expose selective acceptance and scarce capacity. Practice profitability remains practice evidence; live transfer requires separate approval and evaluation.

Block-bootstrap inference is approximate and assumes sufficiently stable, weakly dependent returns within the admitted scope. Thirty blocks cannot establish those assumptions; a structural break can invalidate the inference. Resample **whole time blocks containing all assets together**. Choose block length and a longer-block sensitivity from development dependence diagnostics, freeze them, and check that forward conditions stay within the specified validity range. Use the frozen method for a one-sided 95% lower bound on mean per-stake PnL. Evaluate the entire selector, not independently profitable-looking overlapping trades. Report both the lower and upper bounds with their own one-sided interpretation.

- **PASS:** valid data/contract evidence and required sample/blocks/coverage; lower mean-return bound above zero under both registered block lengths; positive total PnL in both chronological halves; positive return under every frozen delay/payout stress. One end-date decision only. A smaller effect than +1% may meet the positive-expectancy test; disclose its size and operational economics instead of silently claiming the design target was achieved.
- **REJECT the useful-effect hypothesis:** with valid, sufficient evidence, if PASS fails and the one-sided 95% upper bound is below the registered useful effect. This rejects that effect size, not every possible edge or the whole venue.
- **INCONCLUSIVE:** otherwise, including data invalidity, insufficient observations, unresolved contracts or a failed power/coverage requirement. No capital promotion. A terminated safety/health run is inconclusive for profitability unless its predeclared stopping design permits another inference.

The stress set is fixed from development practice measurements: baseline observed joint delay/acceptance behavior, a conservative p95 delay case, and a payout reduction linked to observed offer-to-accept changes or a stated policy floor. Preserve relationships with time/state where observed; do not independently shuffle away adverse selection. Recalculate delayed direction from quotes and exact expiry for stress, label it simulated, and use it only as an additional veto. An accepted actual loser never becomes a simulated winner in the primary cash ledger. Unknown stress behavior blocks promotion rather than being replaced with zero friction.

During collection, operational monitoring may stop on data, risk or contract faults. It cannot select a winner or declare significance early. Only the fixed-date judge can issue PASS. After any run, preserve its result and artifacts. No automatic second attempt on the same spent cohort.

## Risk and platform facts still needed

Before account access or practice submission, verify the account's legal entity/product, permitted automation, offered expiry/purchase terms, actual quote/settlement/fee rules and accessible history fields. Prior notes about a stopped collector and missing public flow are October observations, not a fresh server health check. This review made no server calls. Reliable withdrawal and live account execution are separate due-diligence questions; neither backtests nor practice results establish them.

Proposed future limits: fixed stake up to 0.25% of permitted equity, one outstanding contract, daily loss 2% of starting-day equity, weekly loss 5% of starting-week equity, peak drawdown 8%, no recovery staking. Include reserved worst-case open losses when admitting another trade. A broker minimum above the cap means abstention. Loss stops constrain exposure and do not manufacture edge. Unknown submission, stale account state, unexplained settlement or clock/data failure stops new orders immediately. Risk code and configuration must be inaccessible to the prediction model.

Live activation, deposits, server changes and any sudo restart remain separate explicit actions. If a future live pilot is approved, size it to learn execution transfer, keep policy frozen, and suspend on the same cash/data limits plus a preregistered drift rule; retraining and resumption require a new version and fresh evidence. Do not build autonomous retraining before the first valid champion exists.

## Ambition applied and handoff

Goal beyond the goal: spend capital only on an OTC policy whose measured edge survives the actual contract, and make the failed-search loop stop consuming attention.

Altitude: (1) understand the archived results, (2) test the correct received information and contract, (3) enforce a reproducible research-to-practice decision. Depth: start with raw receipt events and accepted cash contracts; use causal mutation, independent replay, block uncertainty and untouched confirmation. Hard target: zero future-driven feature changes or unexplained admitted settlement differences. Range: experimental design limits selection bias; reliability engineering proves stream health; forensic accounting proves money movement. Speed is not the standard being raised.

Already available: archived source/reports/parquet, negative controls and injected-edge examples, Python tools and domain contracts. Missing or unverified: full raw receipt exports, continuing collector, current permitted integration, offered/accepted contract evidence, true public flow, and fresh confirmation data. Offline unit 0 is executable now after implementation is commissioned; empirical profitability cannot be resolved from this plan alone.

```text
Implement unit 0 of docs/plans/2026-11-05-binary-otc-edge-plan.md in an isolated OTC worktree. Keep crypto services untouched. Start with the archived source tag and raw provenance, reproduce prior counts/returns, quantify payout availability and product defects where raw timestamps permit it, and retain missing values honestly. Add immutable OTC event/cash contracts and deterministic regression/causality tests plus corrupted-data evals. Produce the audit.json and matched before/after report specified in unit 0. Pass only when an independent critic can reproduce every number and future-only mutations cannot change past features. Do not train a new model, connect accounts, restart production or place orders as part of unit 0.
```

Audit evidence and reproduction commands accompany this plan in [the evidence bundle](../research/binary-edge-2026-11-05/README.md). No running service needs restarting for this documentation/evidence change. **Next implementation action: unit 0, the provenance and contract-gap audit.**
