# OTC research direction, 30 October 2026

Recommendation: a bounded, deterministic OTC research programme with agent-assisted investigation and an independent judge. Restore trustworthy observation before considering another model. Keep crypto development separate. No profitable OTC strategy has been demonstrated; that is different from proving that none can exist.

This is a research plan, not an implementation or live-trading approval. No server service was changed, no trade submitted, no model trained, and no crypto code edited during this investigation. The existing Kaggle credential file has mode 600; its contents were not printed or copied into this document. Account authentication and available accelerator quota still need verification before training.

## Outcome and reference

Goal beyond the goal: spend effort only on OTC hypotheses that can survive an executable, forward test, and stop automatically when evidence says they cannot.

Success is either a reproducible positive net-expectancy candidate or a well-powered rejection with its evidence preserved. Daily profits and perfect prediction are not targets. An inconclusive test is neither a profitable candidate nor proof of impossibility.

Reference: actual broker contract and settlement behaviour, not candle-chart screenshots. Research analog: Microsoft's RD-Agent proposal/experiment/feedback loop, with a much smaller implementation. A frozen independent review rubric lives at `/tmp/otc-research/critique/rubric.md`.

Ambition applied:

- Altitude: reproduce prior results; repair the evidence chain; make future proposals pass an automated, independent gate before consuming more attention or capital.
- Depth: start with raw receive timestamps, payouts, accepted strikes and settlements. Use causal replay, negative controls, injected edges, blocked resampling and fresh forward data. Hard target: zero future-dependent features or unexplained settlement mismatches in the audited fixtures.
- Range: use experimental design to control repeated search, reliability engineering to detect dead collectors, and forensic accounting to reconcile each trade's cash flow. Agents inspect these concerns independently; they do not vote a strategy into profitability.

## What was verified

Local reference is tag `otc-binary-final-2026-10-30`. The main branch already removed the OTC application and is being developed for crypto. Do not restore that tag over the shared checkout. Historical code is recoverable with `git show` or in a dedicated OTC worktree.

The prior [direction reset](../../plans/2026-10-30-direction-reset.md) reports three research rounds. Saved predictions and reports remain under `data/archive/otc-binary-2026-10-30/research/`. Recomputing round-three trade counts and mean returns from saved trade files reproduced the reported numbers. That checks the arithmetic, not the causal validity of their input data.

| Evidence | Finding | Interpretation |
|---|---|---|
| First Kaggle round | `any_edge=false`; best near-breakeven candidate unstable across test halves | No promotion justified |
| Round-three LightGBM | 74,088 unseen trades; about -5.04% return per unit staked | Negative under its recorded replay assumptions |
| Archived feature/crowd tests | 11 pass, despite two reproduced defects below | Green tests did not cover all causal failure modes |
| Server Docker inventory | No running containers; collector container exited with code 1 about three weeks ago | Fresh collection is not operating |
| Server database | 5,784,461,312 bytes; modified October 8 | Do not mistake the database's existence for continuing collection |
| Public deals | Zero stored events | Flow research requires new capability verification, not another model on existing data |
| Read-only database aggregate | 14,625,770 realtime rows; latest candle starts October 8 at 06:11:23 UTC; 1,766,561 mood samples, latest bucket 12:31:25 UTC | Different streams stopped at different times; no weeks of new forward candles |

The server was inspected over SSH with read-only SQLite access. No environment files or account secrets were dumped. Runtime notes and audit probes are in `/tmp/otc-research/`. These temporary artifacts can expire. Before implementation, create a hash manifest and preserve the evidence in an approved private external artifact store, keeping binaries out of git; if unavailable, regenerate the probes and metadata and record the changed snapshot date. Do not claim an expired API snapshot was reproduced exactly. Critic artifacts remain under `/tmp/otc-research/critique/` for this task.

### Two reproduced defects to fix before trusting another result

1. **Payout availability can precede observation.** The collector floors payout observations into 300-second buckets; round three joins those bucket timestamps backward onto 120-second decisions. A synthetic observation at second 250 is accepted for a decision at second 120 when stored under bucket zero. This is possible future information in both payout accounting and a model input. The server query confirms 527,820 payout records, with server-receipt minus bucket offset ranging from 3 to 299,999 ms (mean 148,362 ms). The number of actual research joins affected and their P&L impact remain unmeasured. Five-second mood buckets also lose timestamp precision, but aligned two/five-minute decisions do not automatically incur the same crossing. Do not label every historical mood join leaked.
2. **Cross-asset membership depends on a future outcome.** The feature matrix drops future dojis before round three computes market-wide mood from surviving target rows. Changing asset B's future candle into a doji changes asset A's earlier `market_mood` from 0 to -0.3 in the probe. Market context must instead come from the as-of available universe, independently of which future targets survive labeling.

Evidence: `/tmp/otc-research/audit/probe.py`, `probe-results.json`, and the separate local audit report. These defects weaken research validity; they do not imply that correcting them will reveal an edge. Existing negative results remain a strong reason against another blind model sweep.

Also repair in the next implementation:

- Inventory actual product/source combinations first. Preserve `(broker, asset, instrument_type, expiry_rule, source)` identity through features and settlement; never average turbo/binary/digital mood together. Declare a payout-source priority before analysis, reject conflicting quotes, and test that another product or lower-priority source cannot change a decision.
- No default 85% payout for missing or stale observations in a tradeable replay. Mark unknown and abstain.
- Keep refunds as zero-P&L outcomes in the decision ledger. Excluding them from a conditional win-rate display is different from removing decisions before feature generation.
- The existing forward preregistration uses fixed-payout win-rate gates and two inspection points. Preserve it as historical evidence, then register a new protocol with variable-payout P&L and an explicit joint error budget. The old two-look z thresholds are not automatically invalid: the audit finds their one-sided union bound below 5%; the key deficiencies are payout assumptions and dependence. Do not quietly overwrite its rules.
- Candle open/close predictions are proxy labels. Broker expiry schedules, purchase cutoffs, accepted strike, quote arrival and actual settlement must define an executable experiment.

## GitHub research: choose components, not a replacement bot

Repository statistics are snapshots from GitHub's API on October 30. A push can be documentation or a branch change; it is not proof of a recent production fix. Stars are an adoption signal, never evidence of trading profit. The [companion repository review](2026-10-30-github-review.md) records 24 repository snapshots, selected code checks and issue evidence; the [local audit](2026-10-30-local-audit.md) records exact archived file/line references.

| Repository | Snapshot | Decision for OTC |
|---|---|---|
| [iqoptionapi/iqoptionapi](https://github.com/iqoptionapi/iqoptionapi) | 276 stars; pushed 2024-08-12 | Keep a pinned, narrow adapter only after practice-feed contract tests. Unofficial and operationally fragile. |
| [Lu-Yi-Hsun/iqoptionapi](https://github.com/Lu-Yi-Hsun/iqoptionapi) | 391 stars; pushed 2026-07-01 | Not an automatic upgrade. Open issue [369](https://github.com/Lu-Yi-Hsun/iqoptionapi/issues/369) reports the API not working. Inspect actual commits, not push date alone. |
| [ChipaDevTeam/BinaryOptionsTools-v2](https://github.com/ChipaDevTeam/BinaryOptionsTools-v2) | 137 stars; pushed 2026-10-30 | IQ Option is explicitly on its roadmap, not supported. Reject as an IQ Option replacement today. |
| [microsoft/qlib](https://github.com/microsoft/qlib) | 49,830 stars; pushed 2026-10-30 | Study dataset/workflow separation. Do not import an investment platform to settle fixed-expiry binaries. |
| [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | 15,143 stars; pushed 2026-10-21 | Best research-process analog. Borrow the proposal/evaluation loop; default API configuration conflicts with this repo's local-Claude constraint. |
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | 118,534 stars; pushed 2026-10-27 | Useful comparison, not an OTC order engine. Current README does describe point-in-time/backtesting improvements; dismissing it as having none would be outdated. Still no verified fit to this broker's feed and settlement in this review. |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 16,889 stars; pushed 2026-10-25 | Do not start with RL. A simulator with wrong prices/rewards trains an agent to exploit the simulator. |
| [kernc/backtesting.py](https://github.com/kernc/backtesting.py), [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 9,164 / 9,594 stars | Good research tools, but ordinary position P&L is not a binary contract. Retain the small existing settlement code if validated. |
| [hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab) | 4,960 stars; pushed 2023-10-02 | Do not assume a maintained, freely reusable implementation from the brand name. Verify license and available source first. |

Recommended minimal stack: existing Python/NumPy/pandas and deterministic settlement contracts; scikit-learn logistic baseline; one gradient booster, preferably the already-used LightGBM, after timing repair. Use maintained `arch` block-bootstrap primitives if dependency review confirms fit, rather than inventing resampling. CatBoost is a second choice when categorical handling matters; its inclusion must consume an explicit trial, not silently expand the search.

No reviewed repository supplied independent, reproducible, broker-matched forward profit evidence sufficient to justify copying its strategy. This is a conclusion about the sampled sources, not every public or private strategy. Martingale code and screenshots are not substitutes for a timestamped settlement ledger.

Primary documentation: [time-ordered splitting](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), [arch bootstrap tools](https://bashtage.github.io/arch/bootstrap/bootstrap.html), and [IQ Option's OTC description](https://blog.iqoption.com/en/what-is-otc-trading-a-guide-for-weekend-and-off-hours-traders/). The broker describes platform-specific quotes outside a public exchange; that does not reveal its generator or prove a particular manipulation mechanism.

## Research hypotheses, ranked and bounded

Freeze a maximum of three hypothesis families and twelve total parameter/model configurations for this cycle. Every alternative inspected counts, including rejected agent proposals that are actually backtested. Old data is development data because its results have already been inspected. Fresh forward data is the final judge.

1. **Payout-aware crowd fade.** Replicate the old 0.30 <= abs(call_fraction - 0.5) < 0.45 band without retuning it, using true availability timestamps and actual payout. Ask whether any effect survives economics and execution. This is the best-supported lead, not a candidate already ready to trade.
2. **Observable public-flow imbalance and response.** The server has zero `live_deal_events`, so this family is currently blocked. Only after a bounded practice collection proves the endpoint provides events with usable receipt timestamps: test count versus amount imbalance and whether prices react after the information arrives. Do not infer retail identity, institutional flow or complete market coverage. Kill this family if coverage is absent or latency consumes the effect.
3. **Feed structure and cross-asset response.** Test causal lag/response or stable short-horizon reversal conditional on data quality, against block-shifted nulls and asset/time holdouts. Measure duplicate/synthetic common movement first. Cross-asset correlation alone is not an executable lead. No attempts to exploit authentication or interfere with the broker.

Fresh candle models, transformers, RL and wider indicator voting are deferred unless one of these families shows predictive information that survives corrected replay. A larger GPU cannot create information missing from the inputs.

## Economics and the judge

For a unit stake and net winning payout `r`, expected profit is `p_win*r - p_loss`; refunds contribute zero. With no refunds and fixed payout, breakeven is `1/(1+r)`.

| Net winning payout | Breakeven, excluding refunds |
|---:|---:|
| 80% | 55.56% |
| 82% | 54.95% |
| 85% | 54.05% |
| 89% | 52.91% |
| 90% | 52.63% |

These values were computed with Python. At a hypothetical 54.9% win rate, expectancy is +1.565% of stake at 85% payout but -0.082% at 82%. Neither is a forecast. Variable payouts require per-trade P&L, not comparison of an overall win rate with an averaged breakeven.

Proposed frozen promotion gate, registered before any new forward outcomes are inspected:

- Timestamp every observation's arrival, decision, intended expiry, accepted entry/strike if present, settlement and payout provenance. Unknown expiry, stale payout or missing boundary quote means abstain, never interpolate a winning outcome.
- Use expanding chronological development folds, purging overlapping label intervals across all assets. Fit scaling, calibration, feature selection and confidence thresholds inside training/validation only. TimeSeriesSplit by itself is not a cross-asset event-purging implementation.
- Estimate uncertainty from time blocks containing all assets together, preserving simultaneous exposure. Choose block lengths from development diagnostics; report sensitivity to longer blocks. IID Wilson intervals alone cannot establish portfolio expectancy.
- Final test has one scheduled inspection on a fixed calendar end date selected before collection. Development-only seeded block simulation determines the required duration/sample for 80% power at alpha=0.05/12 to detect +1% net return per stake under the complete composite gate, including chronological halves, stress and multiplicity. Require at least 30 distinct trading days and 30 nonoverlapping inference-length time blocks, in addition to the simulated sample requirement; the simulator may demand more. Freeze the end date, block length, stress scenarios and minimum opportunity count before collection. Do not extend the date based on observed outcomes. If the estimate exceeds the collection budget, report underpowered rather than lowering the target.
- Maximum collection budget is 90 calendar days after collector acceptance. No profitable pass from an underpowered result. At the deadline: pass, reject or inconclusive with no capital promotion.
- Estimand: mean net P&L per unit stake of accepted decisions under one frozen policy and settlement protocol. The minimum useful design effect is +1%. Primary statistic: lower one-sided family-adjusted 95% confidence bound on this mean must exceed zero. Use Bonferroni across all twelve allowed configurations for the final gate; any extra inspected final outcomes invalidate this fixed protocol and require fresh data. No daily significance peeking.
- Require positive total P&L in both chronological halves and under a predeclared delay/payout stress derived from practice measurements. A strategy depending on a single asset/session is scoped to it and retested; it is not advertised as a general OTC edge.
- Terminal classification, evaluated only at the frozen date: PASS if every promotion criterion holds; otherwise REJECT the minimum-useful-effect hypothesis if a valid separately family-adjusted upper confidence bound is below +1%; otherwise INCONCLUSIVE. Insufficient coverage, blocks, sample or settlement validity is INCONCLUSIVE regardless of point estimate. A rejection of +1% does not prove zero or negative expectancy. A positive but smaller effect may pass the positive-expectancy gate; report its size explicitly, never call it a confirmed +1% effect.
- Keep counterfactual shadow P&L and broker-settled practice P&L in separate columns and confidence calculations. Shadow-only success is a research candidate, not executable or live-profit proof. Stage 2 practice orders validate the contract; subsequent practice execution validates the frozen candidate at operational scale.
- Report trade count, abstention rate, missing-data rate, daily P&L, drawdown, correlated exposure and concentration alongside confidence intervals. Confidence in average return is not a capital-risk limit.

The block bootstrap still assumes enough stability and enough independent time blocks. Abrupt regime changes, low opportunity counts or unreliable practice/live parity can leave the result inconclusive even after 90 days.

## Small architecture and bloat cuts

Do not introduce a new orchestrator, message bus, dashboard or generic broker abstraction for this plan. Use one isolated `services/otc_research/` unit with its own README, configuration, tests, evals and command entrypoint. Separate modules handle collection, immutable manifests, feature availability, replay and reports. SQLite is adequate for append-only observations; Parquet is adequate for frozen research snapshots. Reuse existing typed contracts through public boundaries, never import crypto internals.

Keep/revalidate: raw harvester schema, clock/health observations, explicit binary settlement contracts, trial registry, purged validation concepts, raw predictions and reproducibility hashes.

Keep archived: legacy bot orchestration, redundant scanners, strategy voting, old trainer variants and failed weights. Do not resurrect all of them to run one study. Recover only code a named experiment needs.

Remove from a future restored OTC runtime: default trading on unknown payout; martingale/recovery sizing; duplicate state stores; import-time trading side effects; switches that silently bypass gates. Each removal needs a dependency check and regression evidence. No deletion is performed in this planning task.

Leave all crypto paths, deployment and agent work untouched. Use an isolated worktree/branch before implementation, with only OTC-specific paths shared through reviewed contracts.

## Deterministic, agent and human roles

| Approach | Useful job | Main failure | Decision |
|---|---|---|---|
| Deterministic only | Collect, replay, label, score, enforce risk | Explores only hypotheses someone specifies | Mandatory foundation |
| Full research-agent harness | Read literature/code, propose a falsifiable JSON experiment, run permitted development jobs | Repeated search, leakage, self-grading, growing complexity | Add after the deterministic judge rejects known bad fixtures |
| Human plus agent | Human supplies a market observation; agent translates it into frozen observable rules | Hindsight explanations and discretionary exceptions | Useful research lane; log every pre-outcome decision and compare with baseline |
| Autonomous LLM trade decisions | Potentially interpret genuinely unstructured, timely information | Latency, unstable reasoning, absent OTC-specific information advantage | Not justified by current evidence; at most a separately budgeted paper comparator |

An agent proposal must specify data fields, availability, transformation, labels, baseline, cost model, trial budget and kill criterion. Use local Claude Code through a self-contained `services/llm/` contract only if needed, selecting the best available model explicitly and recording the actual version. Never silently use an external inference API or downgrade the model. Do not build this service during the plan.

The researcher cannot access the sealed forward partition, brokerage credentials, order path or evaluator source. An independent critic receives the deliverable and frozen rubric, not the builder's rationale. Trials are append-only with IDs, code/data hashes, seeds and metrics. A cron/systemd timer plus explicit job states is enough initially. A state machine prevents retries from registering or settling the same trial twice.

Human interventions remain measurable: record the proposed action, timestamp, reason and outcome before reveal. Judge whether intervention improves net expectancy over the same opportunities. Approval is a control, not an alpha source.

## Delivery order and acceptance

| Stage | Deliverable | Gate tests and evals | Exit |
|---|---|---|---|
| 0: evidence repair | Isolated OTC worktree; reproduce the two defects; immutable exports including true timestamps | Each bug test fails on old code; future rewrites, future asset disappearance, delayed messages, duplicates, clock jumps, dojis, stale/missing payout, mixed products and conflicting sources; seeded replay evals | Zero causal violations; reproduce archived arithmetic while documenting changed assumptions |
| 1: collector recovery | Diagnose exit code from bounded, redacted logs; prepare dedicated practice-only collector; health and restart runbook | Disconnect/reconnect and crash recovery; stale-stream alert; no order method reachable; 24h receipt/clock/coverage report | No unalerted stale interval over 60s; >=99% coverage overall and for each required stream/asset against a predeclared session schedule. Unexpected collector/network outages count as missing; exclude only independently evidenced broker closures under a frozen rule. Failed 24h acceptance runs require a diagnosed fix and a new full 24h run, retaining failed reports |
| 2: faithful replay | Expiry/purchase-cutoff fixtures; instrument/product/source inventory and priority; strike/payout provenance; refund handling | Known settlements match exactly; practice-order ledger independently reconciled; injected delay alters fill/abstention appropriately | No unexplained mismatch; proxy-only rows never described as broker-realised P&L |
| 3: bounded development | Three families / twelve trials on spent historical data | Random and block-shifted controls; planted +1% and stronger edges; calibration, power and block-length sensitivity | Monte Carlo evaluates the entire gate: lower 95% binomial confidence bound for planted-edge detection >=80%; upper 95% bound for null-family promotion <=5%. Freeze repetition count and simulation assumptions before running |
| 4: fresh forward | Sealed inputs and frozen executable policies; daily health-only monitoring | Final gate above; no threshold edits; evidence packet independently recomputed | Candidate, rejection or inconclusive; only candidate proceeds to practice execution review |
| 5: optional agent layer | Proposal schema, local-Claude wrapper, independent evaluator access | Invalid JSON, fabricated source, hidden trial, holdout access, evaluator tampering and timeout evals | Zero critical boundary violations in the fixed eval set; no worsening of null-promotion rate |

Small deterministic fixtures belong in the <2s commit gate. Full replay, statistical Monte Carlo and optional model/LLM evals are separate periodic jobs with recorded thresholds and seeds. Every implementation change ships its tests, evals and operating instructions together. Planning-only work has source/evidence validation and independent document review; it does not claim these future suites already exist.

Before a production restart or deployment, present the exact collector command and service diff for confirmation under the repo's production rule. Do not reuse the old compose entrypoint blindly, because it can launch the trading bot. No sudo commands were run. No restart is needed for this document.

## Kaggle policy

Use the highest-performing accelerator actually permitted on the free account for the workload. The [current Kaggle CLI](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md) documents T4 x2 and several other identifiers, explicitly warning that some are restricted to admins or competitions. A supported identifier does not establish free entitlement. The [P100 retirement announcement](https://www.kaggle.com/discussions/product-announcements/735239) makes older P100 advice unsuitable as the default.

Before a job: authenticate without logging the token; inspect account quota/accelerator choices; record `nvidia-smi`, peak memory and a representative throughput benchmark. Prefer a higher free GPU if granted and faster. Otherwise T4 x2 is the documented default; use both only if the training code supports it. Two GPUs do not automatically accelerate one CPU booster. Stop idle sessions and capture partial results/checkpoints within session limits.

Upload only a private, minimal development dataset. Strip account credentials and identifiers. Keep sealed forward labels outside the training job. Store code/config/data hashes and native versus exported prediction parity, including threshold-boundary behaviour. GPU training can be nondeterministic, as [CatBoost documents](https://catboost.ai/docs/en/features/training-on-gpu); deterministic replay of frozen predictions is required, not a promise of bitwise identical GPU retraining. No training is scheduled until stages 0-2 pass and a hypothesis requires it.

## Rewritten execution brief

```text
Build the smallest OTC research system that can prove us wrong. Leave crypto alone.
Start from the archived code and raw server receive timestamps. Reproduce and fix
payout timestamp leakage and future-dependent cross-asset membership with tests
and evals. Restore a monitored practice-only collector after reviewing the exact
service change. Verify expiry, strike, payout and settlement against broker records.
Pre-register three hypothesis families, twelve trials, a fresh forward partition,
a dependence-aware power analysis and one final inspection. Use the best available
free Kaggle GPU only where measurements justify training. Let local Claude propose
experiments but never change the judge or see sealed outcomes. Ship a reproducible
positive net-P&L candidate or a measured rejection/inconclusive result. Pass only
when an independent critic can recompute the evidence and every promotion gate holds.
```

Next direction: stage 0, evidence repair in an isolated OTC worktree. The first result should be a causal, executable replay and a precise collector restart proposal, not another trained model.
