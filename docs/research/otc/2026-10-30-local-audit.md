# OTC repository audit, 2026-10-30

Scope: read-only repository and archived local artifacts. No production call, checkout, repo edit, training run, or crypto change. Archived source references below mean tag `otc-binary-final-2026-10-30`, inspectable with `git show TAG:path`. Main HEAD observed `d01ee73`.

## What already exists

`README.md:3-14` says OTC is archived and crypto is current. The historical bot and research code remain in the tag/branch, not current imports. Do not check out that tag in the shared directory. Use an isolated OTC worktree when implementation starts.

The project has already done substantially more OTC experimentation than an initial glance suggests. `data/archive/otc-binary-2026-10-30/research/run1/results.json` records 14 configurations, `any_edge=false`; `run2/tournament_results.json` records nine families, `any_candidate=false`; `round3/crowd_results.json` has no candidate in four crowd strategies. The raw prediction/trade parquet files are present, not just prose. Round 1 includes CatBoost/MLP/GRU and rule/meta strategies; round 2 includes logistic/LightGBM/XGBoost/GRU/TCN/transformer/kNN. More architecture search on the same inputs would repeat spent research.

I independently recomputed every nonempty round-3 strategy's seen/unseen trade counts and mean PnL from the saved trade parquet, exactly matching the JSON. LightGBM 90,583 total trades, XGBoost 67,021, logistic 11,052. This confirms report arithmetic, not execution validity. Existing archived feature/crowd tests pass: **11 passed in 9.04s** under an isolated temporary module loader. These are not a full historical-suite run.

`docs/plans/2026-10-30-direction-reset.md` is a useful evidence inventory but its categorical claims (“No amount of ML ... fixes this”, “no exploitable structure”) exceed the experiments. The supported claim is **no demonstrated tradable edge in tested datasets, hypotheses, and sampling/execution assumptions**. Its own power caveat and spent-holdout admission are good and should remain.

## New validity defects found

### 1. Payout bucket timestamps can reveal future information

Archived `trading_platform/scripts/harvest_market_data.py:538-579` stores both actual received/server timestamps and `observed_bucket_ms = observed // interval_ms * interval_ms` (lines 554-555). The documented default payout interval is 300 seconds (`docs/archive/otc-binary/market-data-harvester.md:104-109`). Existing exports use the bucket, while round-3 reads it as `payout_ms` and includes payout in features (`trading_platform/research/studies/otc_crowd_study.py:267-276`). Backward joining in `crowd_features:92-94` cannot recover true availability.

Executable counterexample: a payout first observed at second 250 is bucketed to second 0 and accepted at a second-120 entry. Probe result: future payout 0.82 was accepted. This is a confirmed capability of the code; **actual affected-row prevalence must be measured from source timestamps**, not inferred from the example.

Mood uses the same flooring at harvester lines 498-499. Default 5s buckets align with 120s/300s entries, so this does not by itself prove post-entry mood leakage under the default cadence. It can violate the claimed 1s exclusion buffer. Nonaligned decisions, changed intervals and clocks need their own checks. Do not generalize the payout counterexample blindly to all mood rows.

Required research change: export receive and broker timestamps plus offset and product, compute availability explicitly, join on availability rather than grouping keys, retain stale/missing status, and report affected-row fractions before rerunning any results.

### 2. Round-3 market mood depends on future label availability

`trading_platform/research/studies/otc_feature_matrix.py:139` removes target dojis and invalid next-candle rows. `otc_crowd_study.py:89` subsequently computes `market_mood` by grouping those already-filtered rows, so a different asset's future target being a doji changes the set contributing to a decision-time feature. Synthetic probe: A's market mood is 0.0 when A and B are present; when B is removed because its future candle is a doji, A's market mood becomes -0.3.

Fix in a future implementation: compute cross-asset features from the decision-time available universe independently of label eligibility, then join labels. Add a mutation that changes only another asset's future doji/missing label and asserts A's features stay unchanged. Existing future-rewrite tests do not catch this downstream transformation.

### 3. Missing payout is silently replaced with 0.85

`otc_crowd_study.py:31-32,92-94` joins payout with a ten-minute tolerance and uses a constant fallback. `main:269` averages sources for turbo-option. This is disclosed by the rubric but does not establish executable EV. Round-3 includes fallback values as model inputs and trade returns. Report fallback fraction by time/asset and exclude unknown payout from confirmatory execution claims. Product/source priority must be explicit.

### 4. Product mixing and quote-versus-contract gap

`otc_feature_matrix.py:41` averages mood by asset/time, dropping `itype`; `main:184-185` loads but does not filter product first. Turbo/binary/digital mood is not automatically interchangeable. Confirm actual products in raw data.

Most models label close-versus-open of the next candle (`otc_feature_matrix.py:99-102`). They do not prove actual strike accepted, expiry assigned, delayed entry, rejection, settlement, or refund rules. The archived OTC shadow docs explicitly say broker history transport and real practice validation remain incomplete (`docs/archive/otc-binary/research/otc_shadow_vertical.md`, Authoritative settlement / Remaining gates). Preserve candle studies as research screens, not deployable PnL evidence.

### 5. Statistical decision criteria need a new explicit contract

The model searches use per-trade Wilson bounds, while trades across assets and time can be dependent. Round 2 uses day-bootstrap for log-loss, but not its primary trade-profit gate. Future primary gate should use **realized per-stake net PnL with time-block uncertainty and fixed horizon**, not only win-rate versus averaged breakeven. Variable payout and outcome dependence make pooled win-rate shortcuts inadequate; preserve per-trade PnL.

The preregistered band file declares two expiries and two looks (z=2.50 early, z=2.241 final). Do not casually call this invalid alpha spending: two lower-tail decisions per expiry imply a conservative union-bound family alpha of about 0.0374, below one-sided 0.05. But the file does not clearly state one-/two-sided family convention, block dependence assumptions, expiry-specific scheduling, and stopping disposition. Its fixed 0.540541 gate assumes 0.85 payout even though actual payouts changed. Freeze a dated addendum before any new data is examined; retain original rule unchanged for historical comparability and do not relabel results as the original preregistration.

The combined plan controls prospective decisions: preserve the original band definition and protocol as historical evidence, but use the newly registered payout-aware protocol for promotion.

The old September-October holdout is spent and the round-3 “unseen” label means not used to discover that particular lead, not globally untouched across all prior research. Post-October-8 data is necessary for genuine confirmation.

## Reuse and bloat decisions

Keep/extract only after validation:
- The collector schema with actual observation/clock fields, completed-candle checks, health rows, raw SQLite and immutable exports.
- Deterministic feature and payout accounting ideas, causal mutation tests, trial registry concept, purged windows, native/export parity verification.
- The saved negative results and failed trials. They prevent agents from rediscovering rejected work.
- Broker-authoritative settlement and idempotency principles from current domain contracts without moving crypto files.

Do not resurrect:
- `APIWorker`/`OTCScanner` monolith, strategy voting, martingale/anti-martingale, mutable Telegram risk/account controls, JSON/balance-inferred settlement authority. The earlier audit documents these (`docs/archive/otc-binary/research/current_system.md`, Components requiring isolation or replacement).
- Every historical trainer/model family as a maintained runtime. Current archive already removed much of this bloat.
- The multi-market custom OMS and agent orchestration as a prerequisite for discovering an OTC edge. A small research/collector boundary is enough first.
- A deep-model tournament or RL framework before showing fresh information beats an abstain/no-trade baseline and simple supervised baselines under executable labels.

## Next experiment priority

1. Re-export true availability and complete product identity; audit payout leakage, missing data, source clocks, duplicate identity, and stream continuity.
2. Preserve old results as negative exploratory evidence, fix the two demonstrated feature defects with tests, and reproduce fixed historical screens without claiming a fresh holdout.
3. Restore reliable read-only collection in an isolated OTC deployment only after the plan is accepted; freeze future start time from actual collected state.
4. Maintain the frozen crowd-band forward screen, plus a deliberately small new hypothesis budget using genuinely new information such as timestamped public deal-flow/count-versus-amount divergence, quote freshness, and payout regime. All are hypotheses, not claimed edges.
5. Deterministic runner controls datasets, splits, metrics, trial count, and promotion. Agents propose hypotheses and interpret failure; humans approve trial-budget or deployment changes. No LLM in the order path.
6. Validate actual practice strike/expiry/settlement and latency before any monetary claim. GPU training is downstream of this gate, not the first task.

## Audit artifacts

- `/tmp/otc-research/audit/probe.py`: deterministic source-extraction and counterexamples plus round-3 result recomputation.
- `/tmp/otc-research/audit/probe-results.json`: concrete counterexample values.
- `/tmp/otc-research/audit/run_archived_tests.py`: isolated archived test runner; no shared worktree checkout.
- `/tmp/otc-research/audit/test_otc_feature_matrix.py`, `test_otc_crowd_study.py`: tests extracted from the archive.

This audit made no runtime changes. Its findings feed the [combined research plan](2026-10-30-research-direction.md); raw probes remain outside the repository.
