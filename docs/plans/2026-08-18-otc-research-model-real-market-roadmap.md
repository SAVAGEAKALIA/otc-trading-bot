# OTC Research, Model Validation, and Real-Market Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `writing-plans` and execute this plan phase-by-phase, stopping at every promotion gate.

**Goal:** Determine whether the collected OTC data contains a repeatable, payout-positive signal; deploy it safely only after leakage-resistant shadow validation; and create a separate path toward regulated real-market paper and micro-live trading.

**Architecture:** Keep prediction deterministic and testable in Python. Separate collection, feature generation, training, model registry, inference, execution, and monitoring. Treat OpenClaw as an optional, isolated operations/research interface with read-only telemetry and human approvals—not as a signal generator or order executor.

**Tech Stack:** Python 3.12, SQLite for live capture, Parquet for immutable research snapshots, pandas/Polars, CatBoost baseline, PyTorch/ONNX only after tabular baselines, pytest, Docker, Kaggle GPU/CPU notebooks, MLflow or a lightweight artifact manifest, and a regulated broker's paper API for the real-market branch.

---

## Executive decision

### Recommendation

Continue collecting data and training on Kaggle. Do **not** replace the quantitative pipeline with OpenClaw.

OpenClaw is an agent gateway and personal assistant: it connects language models, tools, channels, and host actions. It is not a market-data model, backtester, low-latency execution engine, or source of predictive edge. Its model outputs are nondeterministic, vulnerable to prompt/content injection, hard to reproduce, and unsuitable as the final authority for financial orders.

Use OpenClaw only after the research pipeline is trustworthy, and only for:

- daily research summaries;
- alert triage and runbook lookup;
- querying read-only model, data-quality, and trading-ledger metrics;
- requesting a human-approved pause, rollback, or report;
- scheduling bounded research jobs that cannot access broker credentials.

Do not give OpenClaw:

- broker passwords, API trading keys, session files, or withdrawal access;
- a tool that can submit, modify, or close an order;
- unrestricted shell access on the collection/trading server;
- permission to promote a model or alter risk limits;
- direct exposure to public Telegram/WhatsApp messages with host tools enabled.

### Why this decision fits the current system

- The live collector has been running since July 31, 2026.
- `/home/ubuntu/IQoption/data/ml/market_context.sqlite` is already about **2.78 GB**, with a live WAL around 9 MB.
- The server has **45 GB** total disk, **17 GB free**, **956 MiB RAM**, and is already using swap.
- At approximately 150 MB/day of database growth, storage engineering is urgent before adding another resident agent runtime.
- The repository already contains causal feature work, payout-aware expectancy, temporal splits, calibration, CatBoost, LSTM/ONNX, and shadow-mode concepts. Improving their scientific validity has much higher expected value than adding an LLM decision layer.

## Skills to use during execution, ordered by priority

1. `quant-analyst` — define hypotheses, payout-aware expectancy, uncertainty, risk limits, and promotion gates.
2. `backtesting-frameworks` — implement purged temporal splits, walk-forward evaluation, realistic execution, and anti-leakage controls.
3. `data-engineer` / `data-engineering-data-pipeline` — control SQLite growth, snapshot safely, validate schemas, partition Parquet, and establish retention.
4. `machine-learning-ops-ml-pipeline` — version datasets/features/models, track experiments, enforce promotion and rollback.
5. `deep-research` — refresh regulatory, broker, market-microstructure, and validation evidence before each major design decision.
6. `python-testing-patterns` — create unit, property, integration, parity, and model-quality tests.
7. `python-pro` — refactor training/inference code into reusable deterministic packages.
8. `docker-expert` — isolate collector, inference, monitoring, and any OpenClaw pilot; impose CPU/RAM/storage limits.
9. `workflow-automation` — schedule snapshots, validation, training, reports, drift checks, and human approval checkpoints.
10. `web-security-testing` — threat-model the monitoring API and any OpenClaw tools before exposing them.
11. `trading-ledger` — capture every signal, abstention, order decision, fill, payout, model version, and operator intervention.
12. `writing-plans` — revise this roadmap when a phase changes scope; never silently skip a gate.

## Non-negotiable principles

- No martingale, loss chasing, or stake escalation after losses.
- No random cross-validation on time-series rows.
- No model selection on the final test period.
- No feature whose source timestamp occurs after the decision cutoff.
- No use of candle close data that would not have been available before entry.
- No assumption that OTC behavior transfers to real exchange/FX markets.
- No real-money deployment based only on backtests.
- No model promotion without an immutable dataset ID, code commit, config, metrics, and reproducible artifact hash.
- No autonomous LLM order execution.

## Promotion gates overview

| Gate | Required evidence | Failure action |
|---|---|---|
| Data-ready | Timestamp integrity, bounded missingness, stable collection, safe snapshots, retention headroom | Fix collection; do not train |
| Research-ready | Exact entry/expiry labels, causal features, calendar splits, baselines | Rebuild dataset |
| Candidate-ready | Positive validation lower-bound expectancy and stable walk-forward folds | Reject candidate |
| Shadow-ready | Untouched test passes, artifact parity passes, no concentration failure | Keep offline |
| OTC paper-ready | At least four weeks and 500+ eligible shadow decisions with broker-observed outcomes | Continue shadowing |
| OTC micro-live-ready | Legal/broker gate passed, positive conservative forward expectancy, operational controls tested | Do not fund |
| Real-market paper-ready | Separate market dataset/model, cost-aware backtest, broker simulator integration | Continue research |
| Real-market micro-live-ready | 6–8 weeks paper evidence, incident drills, independent risk controls | Remain paper-only |

---

## Phase 0: Freeze the scientific question

### Task 0.1: Write the strategy research contract

**Files:**

- Create: `docs/research/otc_hypothesis.md`
- Create: `iqoption_bot/research/contracts.py`
- Test: `tests/research/test_contracts.py`

Define one primary question:

> Using only information observable before an exact decision timestamp, can the system choose CALL, PUT, or ABSTAIN for a fixed expiry and achieve positive expectancy after the broker's contemporaneous payout, with a conservative confidence bound, on future calendar periods?

Record:

- asset universe;
- decision cadence;
- entry delay distribution;
- expiry definition;
- settlement rule, including ties;
- payout source and timestamp;
- maximum feature lookback;
- primary metric: conservative expectancy per unit stake;
- secondary metrics: coverage, calibration, drawdown, loss streak, per-asset stability;
- one final untouched test window;
- explicit stop conditions.

**Verification:** The contract can be serialized to JSON and hashed; training refuses to run without it.

### Task 0.2: Establish economic baselines

Implement payout-dependent break-even:

```text
break_even_win_rate = 1 / (1 + payout_fraction)
expectancy = p_win * payout_fraction - (1 - p_win)
```

Examples:

- 75% payout requires 57.14% wins;
- 80% payout requires 55.56% wins;
- 90% payout requires 52.63% wins.

Compare every model against:

- always CALL;
- always PUT;
- asset/hour majority class;
- random direction at matched coverage;
- current rules-only strategy;
- regularized logistic regression;
- shallow CatBoost with limited features.

---

## Phase 1: Protect and control the live dataset

### Task 1.1: Add database health reporting

**Files:**

- Modify: `harvest_market_data.py`
- Create: `scripts/report_market_db_health.py`
- Test: `tests/test_market_db_health.py`

Report without full scans:

- database/WAL size;
- disk free percentage;
- newest timestamp per table using indexed columns;
- rows inserted per minute from `collection_health` deltas;
- duplicate/rejected insert counts;
- per-asset last-seen time;
- clock-offset distribution;
- collector restart count.

Alert at 70%, 80%, and 90% disk use. Stop nonessential high-frequency sampling before disk exhaustion.

### Task 1.2: Define retention by information value

**Files:**

- Create: `docs/research/data_retention.md`
- Modify: `harvest_market_data.py`
- Create: `scripts/compact_market_context.py`
- Test: `tests/test_market_retention.py`

Proposed initial policy, to be confirmed by profiling:

- finalized 2m/5m/15m candles: retain indefinitely in Parquet;
- payout/mood: retain bucketed causal samples indefinitely;
- raw quotes: retain 14–30 days locally, then retain 1-second/10-second aggregates;
- deal flow: retain aggregates required by features; expire raw event detail;
- clock and health samples: downsample older history;
- never delete before a verified snapshot and checksum exist.

Do not run `VACUUM` on the live database while the collector is active. Use a maintenance window and validated backup.

### Task 1.3: Create safe immutable snapshots

**Files:**

- Create: `scripts/snapshot_market_db.py`
- Create: `iqoption_bot/research/dataset_manifest.py`
- Test: `tests/research/test_dataset_manifest.py`

Use SQLite's online backup API or `VACUUM INTO`; do not copy the main file without coordinating WAL state.

Each snapshot manifest must include:

- UTC cutoff;
- source DB schema version;
- row counts by table/partition;
- min/max event and receive timestamps;
- SHA-256 checksums;
- Git commit and collector image ID;
- missingness/duplicate summaries;
- export parameters.

Export partitioned Parquet by table/date/asset. Kaggle consumes immutable snapshot versions, never the live database.

### Task 1.4: Fix deployment ambiguity

The running container currently has both a bind mount at `/app/data` and an anonymous volume targeting `data`. Verify the effective path and remove the ambiguous relative volume in the next controlled deployment.

**Files:**

- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Test: `tests/test_container_paths.py`

Use one absolute `DATA_DIR=/app/data`, one bind/named volume, a non-root user, memory limits, and a health check.

### Task 1.5: Enforce a data-maturity gate

The current roughly 18 days of live context data is suitable for pipeline debugging, not a credible final profitability claim. Continue collection while building the validation system.

Do not unlock final model selection until the snapshot contains, at minimum:

- 8–12 calendar weeks, preferably longer;
- multiple weekends and identifiable volatility/liquidity regimes;
- enough observations after quality filters to populate every walk-forward and untouched-test gate;
- stable clock, payout, quote, and settlement coverage;
- no unresolved schema or collection changes inside the final evaluation window.

Early Kaggle runs are allowed only as diagnostics. Their results must not consume or redefine the future untouched holdout.

---

## Phase 2: Prove timestamp and label causality

### Task 2.1: Build an availability-time model

**Files:**

- Modify: `build_ml_feature_dataset.py`
- Modify: `iqoption_bot/ml/context_features.py`
- Create: `iqoption_bot/ml/availability.py`
- Test: `tests/ml/test_feature_availability.py`

For every field preserve:

- exchange/broker source event time;
- server receive time;
- local receive time;
- corrected/estimated broker time;
- sampling bucket;
- decision cutoff.

A feature is eligible only when `available_at <= decision_at`. Add property tests that truncate all future rows and reproduce the same feature vector.

### Task 2.2: Reconstruct executable labels

Labels must represent what the bot could actually trade, not merely `next_close > current_close`.

For every hypothetical decision record:

- use the actual decision timestamp;
- add measured inference/network/order delay;
- identify broker entry quote/time;
- calculate the exact expiry/settlement timestamp;
- use broker-consistent settlement price and tie handling;
- attach the contemporaneous payout;
- mark unavailable or ambiguous outcomes instead of guessing.

**Verification:** Manually audit at least 200 randomly sampled decisions across assets and hours against raw records.

### Task 2.3: Measure clock and execution uncertainty

Reject or separately tag samples when:

- clock offset exceeds a defined bound;
- quote is stale;
- spread is missing or anomalous;
- payout was not known at decision time;
- the collector has a gap near entry or expiry;
- candle finalization arrived after the decision.

Create sensitivity datasets with entry delays of 0.5, 1, 2, and 5 seconds. A valid edge should not disappear under a small realistic delay.

---

## Phase 3: Create leakage-resistant evaluation

### Task 3.1: Replace per-asset percentage splits with global calendar splits

**Files:**

- Create: `iqoption_bot/ml/splits.py`
- Modify: `kaggle_strategy_independent_tournament.py`
- Modify: `kaggle_candidate_meta_trainer.py`
- Modify: `train_regime_mtf_lstm_v5.py`
- Test: `tests/ml/test_purged_splits.py`

All assets must share calendar cutoffs. Otherwise different asset histories can leak regime information across train/test boundaries.

Use:

- rolling/expanding walk-forward folds;
- an embargo at least as long as maximum feature lookback plus label horizon;
- a calibration window after training;
- a final untouched calendar holdout not used for feature, threshold, asset, or model selection.

### Task 3.2: Separate discovery, calibration, and final testing

Suggested structure after enough history exists:

- development: earliest 50–60%;
- walk-forward validation: next 20–25%;
- calibration/threshold selection: next 10%;
- final untouched test: latest 15–20%, with minimum calendar-duration and trade-count requirements.

The exact dates must be recorded in the dataset manifest. Do not repeatedly inspect the final holdout.

### Task 3.3: Control multiple testing

Every candidate feature, model, threshold, asset filter, and regime rule is another trial.

Track all trials and apply:

- a pre-registered primary metric;
- limited model families;
- nested selection where feasible;
- probability-of-backtest-overfitting or combinatorial purged CV analysis;
- deflated performance statistics or bootstrap adjustment;
- clustered bootstrap by day/session, not IID row bootstrap.

Reject candidates that win only after extensive unrecorded tuning.

---

## Phase 4: Run the Kaggle model tournament

### Task 4.1: Make CatBoost the primary candidate

Train in this order:

1. logistic regression baseline;
2. small CatBoost on candle-only causal features;
3. CatBoost plus spread/payout/mood;
4. CatBoost plus deal-flow aggregates;
5. regime-specific or meta-gated CatBoost;
6. LSTM/TCN only if tabular models show repeatable edge.

Why: CatBoost is cheaper, easier to interpret, less fragile on modest datasets, and simpler to keep in training/live parity. Deep temporal models should have to beat it out-of-sample, not merely report higher training AUC.

### Task 4.2: Use payout-aware selection

Threshold selection must maximize conservative expected value, not accuracy or ROC AUC.

For each fold report:

- number of decisions and trades;
- coverage;
- average payout;
- win rate and Wilson/cluster-bootstrap lower bound;
- expectancy and lower-bound expectancy;
- maximum drawdown and longest loss streak;
- Brier score, ECE, reliability curve;
- per-asset/hour/day/regime results;
- performance after 1–5 second entry-delay perturbations.

### Task 4.3: Candidate promotion criteria

A suggested initial offline gate:

- at least 1,000 actionable holdout trades overall;
- sufficient calendar coverage, including multiple weekends/regimes;
- positive 95% lower-bound expectancy after observed payout;
- preferred safety margin: lower-bound expectancy at least +0.02 stake/trade;
- positive expectancy in at least 70% of walk-forward folds;
- no single asset supplies more than 25% of total profit;
- no catastrophic asset/regime subgroup hidden by aggregate results;
- stable performance under realistic entry delay;
- calibration better than or competitive with the baseline;
- exact feature and ONNX/CatBoost parity between Kaggle and live code.

These thresholds are research governance, not a promise of profitability. Tighten them if many candidates are tested.

### Task 4.4: Produce a reproducible model bundle

**Files:**

- Create: `iqoption_bot/ml/model_manifest.py`
- Create: `scripts/validate_model_bundle.py`
- Test: `tests/ml/test_model_bundle.py`

Bundle:

- model and calibrator;
- feature list/order/types;
- library versions;
- dataset and research-contract hashes;
- split dates;
- threshold policy;
- payout assumptions;
- metrics and subgroup tables;
- artifact hashes;
- explicit approved/declined state;
- rollback predecessor.

---

## Phase 5: Shadow deployment—still no real money

### Task 5.1: Run predictions without affecting orders

**Files:**

- Modify: `iqoption_bot/scanner.py`
- Modify: `iqoption_bot/strategies/ml_catboost_directional_strategy.py`
- Modify: `iqoption_bot/strategies/ml_catboost_gate_strategy.py`
- Modify: `iqoption_bot/trade_logger.py`
- Test: `tests/test_shadow_ml.py`

Log every eligible decision, including abstentions:

- model/version;
- features hash;
- predicted/calibrated probability;
- threshold and direction;
- payout and expected value;
- reason for trade/abstain;
- data freshness;
- eventual broker-observed result;
- counterfactual rules-only decision.

### Task 5.2: Forward-test for at least four weeks

Require at least 500 eligible shadow trades and multiple market regimes. Prefer longer if coverage is low.

Promotion requires:

- positive conservative forward expectancy;
- no unexplained training/live feature drift;
- no meaningful discrepancy between simulated and broker-observed settlement;
- stable latency and data freshness;
- no concentration in one asset/hour;
- incident-free rollback and kill-switch drills.

If shadow performance fails, return to the hypothesis stage. Do not tune against every bad week.

---

## Phase 6: Optional OpenClaw pilot

### Task 6.1: Deploy only on an isolated host

Do not install OpenClaw on the current 956 MiB collection server. Use a separate small VM/container/OS user with no mounted trading secrets.

Configure:

- authenticated private channel only;
- sandbox enabled;
- network allowlist;
- no direct SSH key for the trading host;
- read-only monitoring API credentials;
- explicit human approval for any pause/rollback request;
- no plugin from an unreviewed registry;
- full audit log and cost budget.

### Task 6.2: Expose a narrow read-only telemetry API

**Files:**

- Create: `iqoption_bot/ops/read_api.py`
- Create: `iqoption_bot/ops/schemas.py`
- Test: `tests/ops/test_read_api.py`

Allowed endpoints:

- `/health`;
- `/collector/status`;
- `/model/current`;
- `/model/drift`;
- `/shadow/summary`;
- `/risk/status`;
- `/incidents/recent`.

Return aggregate metrics only. Never return `.env`, session cookies, broker identifiers, raw messages, filesystem paths containing secrets, or order-capable tokens.

### Task 6.3: Evaluate OpenClaw by operations metrics

Run a 30-day pilot and measure:

- useful alerts caught;
- false alerts;
- operator time saved;
- hallucinated or unsafe suggestions;
- prompt-injection test results;
- model/API cost;
- uptime/resource use.

Keep it only if it saves measurable operator effort without expanding the trading trust boundary.

---

## Phase 7: OTC micro-live gate, if lawful and supported

Before funding:

1. Verify the platform entity, license, product legality, complaint history, withdrawal terms, and local tax/reporting obligations for the user's actual jurisdiction.
2. Confirm API automation does not violate broker terms.
3. Confirm the account can withdraw successfully before scaling deposits.
4. Treat CFTC/SEC binary-options fraud warnings and jurisdictional restrictions as a serious product-level risk, not just a model risk.

Initial controls:

- practice account first;
- fixed fractional stake no greater than 0.10–0.25% of equity per trade;
- daily stop near 1% equity and weekly stop near 3%, subject to independent review;
- one open OTC exposure at a time initially;
- no martingale;
- payout floor and expected-value floor;
- hard stale-data/latency rejection;
- server-side daily/weekly kill switch independent of the model;
- manual funding limits and no withdrawal permission in automation.

Scale only after a predeclared number of forward trades and calendar weeks, using conservative confidence intervals. Any scale-up is a new experiment with a new cap.

---

## Phase 8: Separate real-market branch

OTC binary options and real markets have different labels, microstructure, costs, execution, and legal risks. Do not reuse the OTC model unchanged.

### Task 8.1: Choose one regulated market and broker

Evaluate availability in the user's jurisdiction, regulation, custody, API terms, paper environment, data licensing, fees, minimum account, and tax treatment.

Candidate routes to investigate:

- liquid spot FX through a properly regulated broker with practice API;
- major equity/index ETFs through a broker such as Interactive Brokers, where available;
- exchange-traded futures only after margin/leverage competence and broker approval.

Prefer one liquid instrument and 5m–1h holding periods initially. Avoid attempting high-frequency trading from this infrastructure.

### Task 8.2: Implement a broker-neutral interface

**Files:**

- Create: `iqoption_bot/brokers/base.py`
- Create: `iqoption_bot/brokers/paper.py`
- Create: `iqoption_bot/brokers/ibkr.py` or the selected regulated-broker adapter
- Create: `iqoption_bot/execution/order_manager.py`
- Create: `iqoption_bot/risk/risk_engine.py`
- Test: `tests/brokers/`
- Test: `tests/execution/`
- Test: `tests/risk/`

Separate:

- quotes/bars;
- positions/account state;
- order submission/cancel/replace;
- fills and partial fills;
- commissions/slippage;
- idempotency/reconciliation;
- market-hours/calendars;
- risk approval.

The model emits a proposed target or signal. The deterministic risk engine alone decides whether an order is permitted.

### Task 8.3: Build a real-market backtest

Model:

- bid/ask execution rather than mid-price fantasy fills;
- commissions, spread, slippage, market hours, and rejected/partial orders;
- delayed entry and next-bar availability;
- position sizing and overlapping exposure;
- corporate actions for equities;
- rollover/financing for FX/CFDs where applicable.

Use a separate research contract, datasets, features, labels, model registry, and final holdout.

### Task 8.4: Paper trade before micro-live

Require 6–8 weeks and at least 500 paper decisions, plus:

- positive net expectancy after all modeled costs;
- execution reconciliation accuracy;
- tested restart/reconnect behavior;
- maximum drawdown inside the predefined budget;
- no unexplained divergence from the backtest;
- successful kill-switch, duplicate-order, stale-price, and disconnect drills.

### Task 8.5: Micro-live rollout

Start with the smallest economically meaningful position and a strict loss budget. Suggested engineering caps for review:

- 0.05–0.10% equity risk per trade;
- 0.5% daily loss stop;
- 1.5–2% weekly stop;
- low concurrent exposure;
- automatic return to paper mode on reconciliation, drift, or latency failure.

Do not increase size based on a short winning streak. Require a scheduled monthly review with versioned evidence.

---

## Phase 9: Monitoring and governance

### Task 9.1: Build dashboards and alerts

Track:

- data freshness/gaps/clock drift;
- disk/WAL growth;
- feature distribution drift;
- probability/calibration drift;
- trade coverage and payout distribution;
- expectancy confidence bounds;
- loss streak/drawdown;
- per-asset/regime concentration;
- inference and order latency;
- model and code versions;
- reconciliation errors.

### Task 9.2: Define automatic demotion

Demote to shadow/paper when:

- data-quality gate fails;
- model artifact/hash mismatch occurs;
- conservative rolling expectancy crosses the predeclared boundary;
- drawdown/loss limit is reached;
- feature drift exceeds limits;
- broker reconciliation fails;
- clock or latency becomes unsafe;
- the model version is unregistered.

OpenClaw may explain the alert and link the runbook, but it must not override demotion.

### Task 9.3: Maintain the trading ledger

Every decision must be reconstructable from immutable records. Record human overrides, deployment approvals, incidents, and model changes. Produce weekly and monthly reports even when no trades occur.

---

## Research evidence and sources

1. OpenClaw official README: describes it as a personal AI assistant/gateway connecting models, tools, channels, and host actions—not a quantitative trading system. https://github.com/openclaw/openclaw
2. OpenClaw security guidance: tools can run on the host; inbound content is untrusted; sandboxing and strict tool policy are required. https://docs.openclaw.ai/gateway/security
3. OpenClaw security policy/trust model: the model is not a trusted principal; prompt injection must be assumed; plugins share gateway/host trust. https://github.com/openclaw/openclaw/blob/main/SECURITY.md
4. CFTC/SEC Investor Alert on Binary Options and Fraud: highlights complaints including withdrawal refusal, identity theft, and software manipulation. https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/fraudadv_binaryoptions.html
5. Scikit-learn `TimeSeriesSplit`: training on future observations and evaluating on past observations is inappropriate; successive training sets accumulate prior data. https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
6. Bailey et al., “The Probability of Backtest Overfitting”: motivates explicit control of selection bias from repeated strategy trials. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
7. Interactive Brokers TWS API documentation: official API can retrieve/send data and orders through TWS/IB Gateway; use only after jurisdiction/account suitability checks. https://www.interactivebrokers.com/docs/tws-api/doc/introduction
8. OANDA v20 REST API documentation: a possible regulated-FX/practice route where legally available. https://developer.oanda.com/rest-live-v20/introduction/
9. Current repository CodeGraph and server inspection on 2026-08-18: causal feature code, payout-aware thresholding, temporal split work, live collector command, storage growth, and deployment mounts.

## Immediate next seven actions

1. Do not install OpenClaw on the current trading/data server.
2. Add disk/database health alerts immediately.
3. Create a safe SQLite snapshot and immutable manifest.
4. Profile table sizes and set retention/downsampling before the database consumes remaining disk.
5. Finalize exact executable labels and timestamp-availability tests.
6. Export the first versioned Parquet dataset and run baseline/ CatBoost walk-forward experiments on Kaggle.
7. Keep all model output in offline/shadow mode until the promotion gates are met.

## Definition of success

The project succeeds even if no profitable model is found, provided it reaches a trustworthy answer without risking capital. A negative result from a clean, reproducible test is more valuable than a profitable-looking result contaminated by leakage, selection bias, unrealistic labels, or execution assumptions.
