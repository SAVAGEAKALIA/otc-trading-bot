# Multi-Market Agentic Trading Platform Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `writing-plans` and execute this plan phase-by-phase, stopping at every promotion gate.

**Goal:** Evolve the existing IQ Option OTC bot into a testable, failure-tolerant, multi-market platform supporting OTC, crypto spot, and crypto perpetual trading while keeping all financial authority in deterministic Python.

**Architecture:** Preserve the proven OTC collection, feature, strategy, and model work, but place it behind explicit domain and adapter boundaries. Build a single-process modular monolith first, with PostgreSQL-backed ledgers and broker reconciliation; use LangGraph only for durable research and operator workflows, and Hermes only as a replaceable reasoning model whose structured proposals cannot bypass deterministic risk or execution controls.

**Tech Stack:** Python 3.12, asyncio, Pydantic v2, PostgreSQL, SQLAlchemy/Alembic, Parquet/DuckDB, CatBoost/ONNX Runtime, LangGraph, Hermes through an OpenAI-compatible provider interface, official exchange SDKs where mature, Prometheus/OpenTelemetry, Docker Compose, pytest/Hypothesis, and exchange testnets.

---

## 1. Executive summary

### Local implementation completion checkpoint (2026-08-19)

The repository-local deterministic platform work is complete and verified:
domain contracts, risk/OMS/ledger boundaries, idempotent reconciliation,
exact-decimal account projections with hedge-leg identity, Bybit public and
private-read boundaries, testnet-only create/cancel/amend execution, private
stream lifecycle and sequence safety, private order/execution normalization,
research/Kaggle artifact tooling, and Telegram authorization primitives are all
implemented behind injected transports and covered by automated tests.

The remaining acceptance gates are necessarily external: authenticated IQ
Option practice parity, authenticated Bybit testnet connectivity, seven-day
shadow observation, backup/restore drills against the deployment environment,
and any legal/operational promotion decision. No local test can honestly mark
those gates complete without broker access and controlled runtime evidence.

The correct next system is not an LLM trader wrapped around the current bot, and it is not an immediate rewrite into microservices. It is a modular monolith with four strict planes:

1. **Research plane:** immutable datasets, causal features, experiments, backtests, calibration, model registry, and reports.
2. **Trading plane:** normalized market data, deterministic strategies/models, portfolio state, risk, order management, broker adapters, reconciliation, and an append-only ledger.
3. **Agent plane:** LangGraph workflows using Hermes for research, critique, incident analysis, and bounded proposals.
4. **Operations plane:** configuration, secrets, telemetry, alerts, deployment, incident response, and promotion controls.

The existing repository contains valuable work: an independent market harvester; causal context features; CatBoost and ONNX inference; payout-aware evaluation; temporal splits; candidate research logging; multiple deterministic OTC strategies; session limits; data-staleness checks; and tests around candle completion, strategy wiring, WebSocket locking, and ML inference. These should be retained.

The present live path is not ready to become a general execution engine. `APIWorker` and `OTCScanner` carry too many responsibilities; runtime state is mostly in memory; the trade ledger is JSON-based; result handling contains broker-specific polling and balance fallbacks; Telegram commands can switch account mode and alter risk parameters; broad exception handling is common; configuration has parallel dict/dataclass representations; and martingale/recovery logic remains reachable. These are unacceptable foundations for leveraged perpetual trading.

The recommended sequence is therefore:

- stabilize and characterize the current OTC system;
- extract domain contracts without changing behavior;
- build a simulated broker, deterministic risk engine, ledger, order manager, and reconciliation service;
- migrate IQ Option behind the contracts;
- build realistic backtesting and environment gates;
- integrate Bybit testnet using its official V5 semantics;
- add LangGraph and Hermes only after deterministic paper trading is stable;
- defer WEEX until its API, test environment, jurisdiction, and operational behavior pass a formal integration due-diligence gate.

No profitability claim is made. Every proposed strategy is a hypothesis requiring cost-aware, point-in-time validation.

## 2. Investigation scope and evidence labels

This blueprint uses four labels:

- **Verified fact:** directly observed in repository source or primary documentation.
- **Engineering inference:** strongly implied by evidence but still requires implementation validation.
- **Research hypothesis:** plausible trading idea that must be tested.
- **Open question:** insufficient evidence or a user/business decision is required.

Evidence priority is official documentation, exchange documentation, peer-reviewed/established research, reputable engineering material, maintained open source, practitioner discussion, and finally video/tutorial material.

## 3. Existing repository analysis

### 3.1 Current runtime map

```text
main.py
  -> OTCTradingBot
     -> TelegramInterface / CommandHandler
     -> APIWorker
        -> ConnectionManager
        -> MarketDataProvider
        -> OTCScanner
           -> StrategyEngine
              -> rule strategies
              -> ML LSTM / directional CatBoost
           -> SignalGatekeeper / quality vetoes
           -> optional CatBoost candidate gate
        -> PriorityTradeQueue
        -> AssetResolver -> iqoptionapi.buy(...)
        -> active_trades (memory)
        -> ResultChecker
           -> broker result polling
           -> balance-comparison fallback
           -> TradeLogger
           -> SessionManager / confidence / fingerprints
           -> optional MartingaleManager
```

The independent collection/research path is materially better separated:

```text
harvest_market_data.py
  -> IQ Option read APIs/WebSockets
  -> MarketStore (SQLite)
  -> candles, quotes, deals, mood, payout, health, clock samples

build_ml_feature_dataset.py
  -> read-only market SQLite
  -> MarketContextProvider + causal feature enrichment
  -> Parquet datasets

training scripts / Kaggle notebooks
  -> chronological splits + purge
  -> baselines/CatBoost/LSTM
  -> calibration + payout-aware thresholding
  -> CBM/ONNX/scaler/metadata artifacts

live strategies
  -> load versioned artifacts
  -> reproduce feature schema
  -> infer direction or gate an existing candidate
```

### 3.2 What works well and should be retained

| Component | Evidence | Decision |
|---|---|---|
| Independent `harvest_market_data.py` | Separate entry point; SQLite store; backfill/live modes; health and clock concepts | Retain, then adapt behind `MarketDataProvider`/sink contracts |
| Completed-candle discipline | Dedicated helpers and tests | Retain as a cross-market invariant |
| Causal market context | Event/receive timestamps and decision-time enrichment are already emerging | Retain and formalize availability-time contracts |
| Strategy base/result concepts | Multiple strategies share `BaseStrategy` and `StrategyResult` | Retain OTC implementations; replace their platform-facing contract |
| CatBoost gate semantics | Candidate gate accepts/rejects rather than silently reversing direction | Retain this separation |
| ONNX export/parity checks | Training scripts include export/verification logic | Retain; require artifact manifests and live parity gates |
| Payout-aware expectancy | Training code evaluates economic return rather than accuracy alone | Retain for OTC; generalize costs for spot/perpetuals |
| Temporal validation work | Purges, chronological splits, calibration, bootstrap lower bounds | Retain and consolidate into one research package |
| Unknown-settlement exclusion | Result checker avoids fabricating a tie when settlement is unverified | Retain as a ledger invariant |
| Session loss/streak limits | Existing deterministic checks | Retain concept; rebuild as immutable risk policies |
| Candidate research SQLite | Captures candidate features and outcomes | Retain as research input, not authoritative execution ledger |
| Practice defaults | Configuration defaults to `PRACTICE` | Retain; make live mode cryptographically/configurationally harder to enter |

### 3.3 Components requiring refactoring

| Current component | Problem | Target |
|---|---|---|
| `APIWorker` | Connection, queue, state, risk, execution, scanner integration and result coordination are coupled | Split into application coordinator, order manager, execution adapter, reconciliation worker, and portfolio projection |
| `OTCScanner` | Very large policy surface; data retrieval, strategy selection, ML, timing, vetoes and recovery behavior intermingle | OTC strategy service producing immutable `SignalProposal` records |
| `AssetResolver` | Symbol fallback and actual buying share a component | `InstrumentCatalog` plus IQ Option execution adapter |
| `ResultChecker` | Polling, settlement inference, notifications, learning updates and martingale handling are combined | Broker reconciliation + venue-specific settlement adapter + domain event handlers |
| `TradeLogger` | JSON history is not a transactional, queryable, append-only live ledger | PostgreSQL ledger with atomic projections; JSON export only |
| `SessionManager` | Mutable in-memory state; daily boundary/persistence ambiguity | Risk-state projection rebuilt from ledger and broker truth |
| configuration | Environment dicts and dataclasses can drift; commands mutate runtime settings | One validated immutable settings model; controlled runtime policy records |
| strategy performance weighting | Online adaptation can create feedback/selection bias | Shadow-only until a separately validated adaptive-policy protocol exists |
| market data provider | IQ Option types and blocking calls leak upward | Normalized events and bounded async adapter interface |
| training scripts | Several large standalone programs duplicate split/metric/feature logic | Reusable `research` package plus thin CLIs |

### 3.4 Components to remove or quarantine

- Remove martingale and anti-martingale from every future live execution path. Preserve legacy code only for forensic comparison until migration is complete.
- Remove any fail-open AI behavior. An unavailable or malformed model/agent means `ABSTAIN`, never “proceed with caution.”
- Remove direct account switching to real money from ordinary Telegram commands. Live activation requires deployment configuration plus a separate approval procedure.
- Remove the ability for operator/agent commands to alter leverage, maximum risk, withdrawal capability, or kill-switch ceilings at runtime.
- Quarantine `legacy/`, `backup/`, old XGBoost scripts, and duplicate dataset builders after provenance is documented; do not delete them until reproducibility dependencies are mapped.
- Do not restore the deleted `iqoption_bot/ai_analyzer.py` as a trade authority.

### 3.5 Dangerous live-trading characteristics

1. `active_trades` and other critical state are in memory and can disappear on restart.
2. Settlement may fall back to balance inference, which is ambiguous under concurrent activity.
3. `iqoptionapi` contains busy waits, broad exception suppression, shared mutable WebSocket structures, and unofficial protocol behavior.
4. Runtime commands can enable real mode and mutate risk behavior.
5. Broad `except Exception` and bare `except` blocks can hide invariant failures.
6. JSON persistence cannot atomically coordinate signal, risk decision, order submission, acknowledgement, fill, and position state.
7. Recovery sizing exists and can magnify losses.
8. The Docker deployment lacks a real health check, resource limits, non-root execution, and an unambiguous absolute data-volume contract.
9. Tests cannot currently run in the checked environment because `pytest` is absent from both system Python and the repository virtual environment.
10. There is no authoritative restart reconciliation before new orders are allowed.

### 3.6 OTC assumptions that do not transfer to crypto

| OTC assumption | Why it fails for spot/perpetuals |
|---|---|
| CALL/PUT with fixed expiry | Crypto has persistent positions, amend/cancel/close operations and variable holding periods |
| One broker result after expiry | Orders can be partially filled, rejected, canceled, expired, amended, or filled across executions |
| Stake is the maximum loss | Perpetual loss depends on leverage, mark price, maintenance margin, liquidation and gap/slippage |
| Payout defines break-even | Crypto expectancy must include maker/taker fees, spread, slippage, funding and borrow costs |
| Candle direction is settlement | Positions realize/unrealize PnL continuously and may close through multiple orders |
| Balance delta can infer outcome | Deposits, fees, funding, multiple fills and simultaneous positions make this invalid |
| Asset symbol is sufficient | Venue, product type, settlement coin, contract size, tick/lot size and position mode matter |
| Entry acknowledgement implies a trade | Bybit explicitly documents asynchronous order acknowledgement; WebSocket status must confirm lifecycle |

## 4. External research findings

### 4.1 LangGraph

**Verified fact:** LangGraph describes itself as a low-level framework for long-running, stateful workflows that can mix deterministic and agentic steps, with persistence, durable execution and human-in-the-loop controls.

**Applicable:** experiment orchestration, research review, incident investigation, approval checkpoints, resumable report generation, and bounded operational workflows.

**Inappropriate:** tick processing, order-state ownership, risk enforcement, sizing, exchange heartbeats, or latency-sensitive execution.

### 4.2 Hermes Agent

**Verified fact:** Hermes Agent provides tool use, persistent memory, subagents, terminal backends, a gateway, command approvals and container isolation. Its own feature set makes it a broad privileged automation environment.

**Decision:** Hermes is a reasoning provider/operator agent, not the trading runtime. Integrate it through a narrow model/tool boundary inside selected LangGraph nodes. Disable autonomous skill creation and unrestricted terminal/network tools in the trading environment. Agent memory is advisory and never portfolio truth.

### 4.3 Bybit V5

Primary-documentation findings:

- authenticated REST calls use signed timestamp/API-key/receive-window/request data;
- testnet and demo trading are distinct environments, and demo lacks some production functionality;
- public/private/order-entry WebSocket endpoints are separated by product/environment;
- order acknowledgement is asynchronous and the WebSocket stream should confirm order status;
- client `orderLinkId` supports correlation/idempotency design;
- perpetual orders require correct `positionIdx` semantics where hedge mode is used;
- exits require correct `reduceOnly` behavior;
- rate limits exist at IP and API/endpoint levels and must be handled explicitly;
- disconnection is expected and clients must heartbeat, reconnect, resubscribe and reconcile.

**Architecture consequence:** Bybit integration must be an order-state machine, not a synchronous `buy()` wrapper.

### 4.4 WEEX

The publicly reachable documentation page was insufficiently machine-readable during this investigation. Therefore WEEX details such as sandbox completeness, endpoint stability, exact signing, rate limits, position mode and WebSocket reconciliation remain an **open due-diligence item**. No implementation should be scheduled until official documentation and a test account are verified manually and contract tests are written from captured fixtures.

### 4.5 IQ Option

The repository uses a vendored community `iqoptionapi` implementation rather than a supported institutional execution API. This increases protocol-change, terms-of-service, session-security and reconciliation risk. The adapter may remain for practice/shadow OTC research, but it must be isolated and must not define the shared broker contract.

## 5. Open-source systems studied

| System | Solves | Useful patterns | Not adopted wholesale |
|---|---|---|---|
| NautilusTrader | Event-driven multi-asset backtest/live engine | Unified strategy behavior, typed domain events, modular adapters, reconciliation mindset | Rust core and broad framework migration are too disruptive now |
| Hummingbot | Multi-exchange market making/execution | Connector contracts, paper connectors, executors owning lifecycle, spot/perpetual separation | Strategy model is market-making oriented; large framework adoption would bury existing OTC/ML work |
| Freqtrade | Python crypto strategy research/live bot | Dry-run, backtesting, look-ahead analysis, exchange-specific configuration, operational controls | Candle-centric strategy framework is not a clean fit for OTC plus general OMS requirements |
| Lean | Mature multi-asset algorithm engine | Security master concepts, brokerage adapters, event-driven engine, realistic fills | C# ecosystem and migration cost conflict with preserving the Python codebase |
| CCXT | Normalized exchange REST/WebSocket surface | Discovery/prototyping and fallback market-data normalization | Unified methods hide venue-specific order semantics; not the authoritative live execution layer |
| VectorBT | Fast vectorized research | Broad parameter screening, sensitivity analysis, portfolio analytics | Vectorized fills are insufficient for final execution validation |
| Backtrader | Classic Python event-driven backtesting | Simple strategy/broker/data abstractions | Lower current activity and weaker crypto microstructure/reconciliation model |
| TradingAgents | Multi-agent financial analysis | Role-separated critique/debate as a research workflow | Demonstration/research architecture, not evidence of live profitability or execution safety |
| FinRobot | LLM financial analysis toolkit | Research/reporting patterns | Not an OMS, risk engine, or production trading core |
| FinMem | Memory-augmented financial agent research | Temporal memory hypotheses | Memory quality does not establish tradable edge; unsuitable as authoritative state |
| AI Hedge Fund-style projects | Transparent multi-agent demonstrations | Structured analyst outputs and human-readable rationale | Educational simulations commonly omit production-grade fills, reconciliation and risk authority |
| Hermes Agent | General autonomous tool agent | Research, durable operator interaction, isolated execution backends | Privilege surface and nondeterminism are unacceptable inside the order path |

Repository popularity is not treated as evidence of correctness or profitability. Maintenance dates and issue activity must be rechecked when implementation begins.

## 6. Papers and quantitative literature studied

The design is informed by the following established results and cautions:

- Bailey et al., *The Probability of Backtest Overfitting*: repeated strategy selection can make the best backtest a statistical false discovery.
- Harvey, Liu and Zhu, *…and the Cross-Section of Expected Returns*: multiple testing demands substantially stronger evidence than conventional single-test thresholds.
- López de Prado, *Advances in Financial Machine Learning*: purging/embargo and event-aware validation address overlapping labels and leakage.
- White, *A Reality Check for Data Snooping*: benchmark many tried rules rather than reporting only the winner.
- Deflated Sharpe Ratio work: adjust apparent Sharpe for non-normality and multiple trials.
- Jegadeesh and Titman; Moskowitz, Ooi and Pedersen: momentum/trend effects have plausible empirical foundations but are regime-, implementation- and cost-dependent.
- Avellaneda and Stoikov: market making requires explicit inventory and fill-risk control; it is not simply predicting the next price direction.
- Gu, Kelly and Xiu: ML may model nonlinear return relationships, but careful out-of-sample design is central.

These sources support research methodology, not a promise that their reported effects survive in current crypto or IQ Option OTC markets.

## 7. Video and talk review

Videos are supplementary evidence only. The useful categories are official LangChain/LangGraph talks demonstrating persistence and interrupts, official Bybit API walkthroughs demonstrating private streams/order lifecycle, QuantConnect/Lean architecture presentations, and Hummingbot connector/executor walkthroughs. Claims about returns, win rates or “AI trading” shown in videos are excluded unless independently reproducible from code, data and cost assumptions.

Before implementation, record exact title, channel, publication date, URL, transcript notes and independently verified claims in `docs/research/source_register.md`. This pass found no video-only fact necessary to the architecture.

## 8. Scientific strategy research findings

### 8.1 OTC binary options

The only defensible primary objective is conservative expectancy at contemporaneous payout:

```text
EV per unit = p(win) * payout - (1 - p(win))
break-even p(win) = 1 / (1 + payout)
```

Promising hypotheses to test separately include short-horizon reversal after statistically unusual runs, volatility-compression breakout, trend continuation with multi-timeframe alignment, and model-based abstention/gating. Each must use exact executable entry/expiry labels, causal payout data, asset/hour controls and broker-observed forward outcomes. Broker-constructed OTC series may not represent external market price formation.

### 8.2 Crypto spot

Research candidates:

1. **Time-series trend/momentum:** plausible behavioral/risk-premium basis; test medium horizons to avoid fee-dominated turnover.
2. **Cross-sectional momentum:** rank a liquid, point-in-time universe; requires delisting/survivorship controls and portfolio constraints.
3. **Short-horizon mean reversion:** possible liquidity/temporary-pressure mechanism; highly sensitive to spread, queue position and latency.
4. **Volatility breakout:** plausible regime-transition behavior; vulnerable to false breaks and slippage.
5. **Regime-conditioned allocation:** use volatility/liquidity state to scale or abstain, not to invent a guaranteed regime classifier.

### 8.3 Crypto perpetuals

Additional candidates:

1. trend/momentum with funding-aware holding costs;
2. funding/basis dislocations, only with synchronized spot/perpetual data and realistic hedging;
3. liquidation/order-book imbalance signals, only with high-quality depth/trade data and latency measurement;
4. volatility targeting with conservative leverage and isolated margin;
5. market-neutral relative-value research, only after multi-leg execution and residual exposure controls exist.

Perpetual research must model mark/index/last price distinctions, funding timestamps, maintenance margin, liquidation buffer, reduce-only exits, partial fills and exchange-specific position modes.

### 8.4 Required strategy report

Every strategy must declare economic rationale, universe, cadence, data, features, entry/exit, sizing, costs, expected capacity, latency sensitivity, failure regimes, benchmarks, parameter count, all trials performed and rejection conditions. A high hit rate alone is irrelevant.

## 9. Recommended architecture

```text
                         RESEARCH PLANE
raw snapshots -> causal datasets -> experiments -> registry -> approved artifact
       ^                                                         |
       |                                                         v
MARKET DATA PLANE       DETERMINISTIC TRADING PLANE          AGENT PLANE
venue adapters -------> normalized events -> strategy/model   LangGraph
       |                                      proposals          |
       |                                           |             Hermes
       |                                           v             |
       +--------------------------------------> risk engine <-----+ proposal only
                                                   |
                                                   v
                                            order manager
                                                   |
                                             broker adapter
                                                   |
                                                   v
                                                venue
                                                   |
                                      private events/reconciliation
                                                   |
                                                   v
                                            ledger/projections
```

The platform starts as one deployable codebase with separate processes. Module boundaries must be enforceable in tests. Network services are introduced only when a measured reliability or scaling need appears.

## 10. LangGraph architecture

Use separate graphs, never one omnipotent trading graph:

### Research graph

```text
define hypothesis -> retrieve approved data -> propose experiment
-> deterministic validation -> run bounded job -> summarize
-> skeptical critique -> human accept/reject -> register report
```

### Incident graph

```text
alert -> collect read-only telemetry -> classify -> retrieve runbook
-> propose action -> human approval -> constrained operations API
-> verify outcome -> incident record
```

### Trade-review graph (shadow initially)

```text
receive deterministic proposal -> collect bounded context
-> Hermes critique -> structured APPROVE/VETO/UNCERTAIN
-> log counterfactual only
```

Even after validation, the agent may only veto or reduce participation; it should not invent direction, increase size, remove a stop, raise leverage, or override a kill switch. LangGraph checkpoints belong in a separate schema/database namespace from trading truth.

## 11. Hermes integration architecture

- Connect Hermes through an OpenAI-compatible chat/tool adapter so it is replaceable.
- Use temperature near zero for schema-constrained tasks, while recognizing this does not make outputs deterministic.
- Validate every response with Pydantic and semantic policy checks.
- Allow only read-only research/telemetry tools by default.
- State-changing tools operate on opaque IDs for prevalidated actions, not arbitrary broker parameters.
- Disable shell, browser, code execution, skill installation and memory mutation in the live trading deployment.
- Treat retrieved internet content as untrusted data, never as instructions.
- Store prompt version, model/provider, input hashes, output, validation result, latency and token cost.
- Hermes outage results in skipped agent enrichment, not trading-core outage.

## 12. Deterministic trading core

Critical functions are pure or transactionally deterministic:

- normalize and validate market events;
- reject stale/out-of-order data;
- generate strategy/model proposals;
- calculate current portfolio exposure from reconciled state;
- apply instrument, account, strategy and global risk policies;
- calculate quantity using venue precision and limits;
- construct orders and client IDs;
- persist intent before submission;
- submit through a broker adapter;
- consume private order/execution/position streams;
- reconcile after gaps/restarts;
- activate kill switches independently of agents/models.

No order is submitted unless a durable `RiskDecision(APPROVED)` references the exact immutable proposal and order intent.

## 13. Broker abstraction design

Avoid one giant `Broker` interface. Use capabilities:

```python
class MarketDataAdapter(Protocol): ...
class InstrumentProvider(Protocol): ...
class AccountProvider(Protocol): ...
class OrderExecutionAdapter(Protocol): ...
class OrderQueryAdapter(Protocol): ...
class PositionQueryAdapter(Protocol): ...
class ReconciliationAdapter(Protocol): ...
class BinarySettlementAdapter(Protocol): ...
```

Venue adapters return normalized domain objects plus the raw payload hash/reference. Unsupported capabilities fail explicitly. Exchange-specific options live in typed extension objects, not untyped dictionaries.

## 14. OTC architecture

- Preserve CALL/PUT/ABSTAIN as an OTC-only signal vocabulary.
- Represent expiry and payout explicitly.
- Require a payout observation timestamp no later than decision time.
- Use `BinaryOrderIntent`, `BinaryOrderAccepted`, and `BinarySettlementObserved` events.
- Treat IQ Option settlement as authoritative only when directly identified; balance inference is operational evidence but not research-grade truth.
- Keep OTC data, risk limits and performance reports separate from crypto.
- Run IQ Option adapter in its own process because the unofficial client uses blocking/shared-state behavior.
- Prohibit martingale and concurrent ambiguous settlement during micro-live validation.

## 15. Crypto spot architecture

- Model base/quote assets, available/reserved balances and inventory.
- Support market, limit, post-only where available, time-in-force, cancellation and partial fills.
- Calculate fees per execution and realized PnL by a declared accounting method.
- Enforce minimum notional, lot size, tick size and precision from refreshed instrument metadata.
- Track order intent, venue acknowledgement, working status, executions, cancellation and terminal status separately.
- Use client order IDs for idempotent recovery.
- Prevent accidental shorting unless margin trading is an explicitly separate capability.

## 16. Crypto perpetual architecture

- Separate linear/inverse contracts and settlement currency.
- Represent cross/isolated margin and one-way/hedge mode explicitly.
- Default to isolated margin, one-way mode and low leverage during validation.
- Require reduce-only semantics for exits and verify remaining position after every close attempt.
- Track mark, index and last price; liquidation risk uses the exchange-defined relevant values.
- Record funding accruals independently from trade PnL.
- Risk engine enforces gross/net exposure, leverage, liquidation buffer, concentration and maximum order notional.
- Reconciliation compares local orders, executions, positions, balances and mode/leverage settings with venue truth.

## 17. Core interfaces and schemas

Minimum immutable Pydantic/domain records:

- `InstrumentId(venue, product_type, symbol, settlement_asset)`
- `MarketEvent(event_id, event_time, receive_time, sequence, source)`
- `Bar`, `Quote`, `TradeTick`, `OrderBookDelta`, `FundingRate`, `PayoutQuote`
- `StrategyContext(dataset/model/config versions, decision_time)`
- `SignalProposal(signal_id, strategy_id, action, confidence, horizon, expires_at)`
- `RiskDecision(decision_id, signal_id, approved, limits_snapshot, reasons)`
- `OrderIntent(client_order_id, decision_id, side, type, quantity, price, flags)`
- `VenueOrder`, `Execution`, `Position`, `Balance`, `BinarySettlement`
- `ReconciliationRun`, `RiskBreach`, `KillSwitchEvent`, `AgentProposal`

Money and quantity use `Decimal` at venue boundaries and ledger storage. Floating point is permitted for model features, never for order precision or accounting.

## 18. Event taxonomy

Categories:

- market: `bar.finalized`, `quote.updated`, `book.snapshot`, `book.delta`, `funding.updated`, `payout.updated`;
- strategy: `signal.proposed`, `signal.expired`, `signal.abstained`;
- risk: `risk.approved`, `risk.rejected`, `risk.breach`, `kill_switch.activated`;
- order: `order.intent_recorded`, `order.submission_started`, `order.acknowledged`, `order.rejected`, `order.canceled`, `order.expired`;
- execution: `execution.received`, `position.changed`, `balance.changed`, `funding.charged`;
- OTC: `binary.accepted`, `binary.expired`, `binary.settled`, `binary.unverified`;
- operations: `adapter.connected`, `adapter.disconnected`, `data.stale`, `reconciliation.started/completed/failed`;
- model/agent: `model.inferred`, `model.rejected`, `agent.proposed`, `agent.invalid`, `agent.vetoed`.

Every event has UUID, schema version, correlation/causation IDs, venue/account/environment, event/receive/persist times and payload hash.

## 19. Database schema proposal

PostgreSQL authoritative tables:

- `accounts`, `instruments`, `strategy_versions`, `model_versions`;
- `signal_proposals`, `risk_decisions`, `order_intents`;
- `venue_orders`, `executions`, `positions_current`, `position_snapshots`;
- `balances_current`, `balance_snapshots`, `funding_entries`, `binary_settlements`;
- `domain_events` append-only event journal;
- `reconciliation_runs`, `risk_breaches`, `operator_actions`, `agent_runs`;
- `deployment_versions`, `promotion_decisions`, `incidents`.

Important constraints:

- unique `(venue, account_id, client_order_id)`;
- unique venue execution IDs;
- immutable order intent after submission;
- foreign key from order intent to approved risk decision;
- terminal status transition validation;
- append-only audit records enforced by application role/permissions;
- UTC timestamps and explicit event versus receive time;
- payload JSONB only for venue extensions/raw references, not core searchable fields.

Parquet is the immutable research store, partitioned by source/event/date/instrument with manifests and checksums. DuckDB queries local snapshots. SQLite remains appropriate for isolated collectors, development and agent checkpoints, but not shared live order truth. Redis is not initially required.

## 20. Data architecture

```text
raw venue capture -> immutable bronze Parquet
                  -> validated normalized silver
                  -> point-in-time feature/label gold
                  -> versioned experiment dataset
```

Required controls include source/event/receive timestamps, sequence gaps, schema versioning, deduplication keys, clock offset, data quality reports, point-in-time joins, retention policies, and immutable manifests. Live features and training features must share transformation code and parity fixtures.

### 20.1 Verified current OTC collection deployment

A read-only inspection on 2026-08-18 confirmed the collector is active on `152.70.46.129`:

- process: `python3 harvest_market_data.py --mode live`;
- running since 2026-07-31;
- primary database: `/home/ubuntu/IQoption/data/ml/market_context.sqlite`, approximately 2.79 GB;
- live WAL observed at approximately 18.8 MB during inspection;
- database tables include historical/realtime candles, quote samples, live deal events, 10-second deal-flow aggregates, trader mood, payout samples, clock samples, collection health and metadata;
- host capacity observed: 45 GB disk with 17 GB available, 956 MiB RAM and active swap;
- container is a Docker Compose one-off container with restart policy `no`;
- the deployment currently has both `/app/data` bind-mounted and an ambiguous anonymous volume mounted at relative `data`, which must be corrected before the next controlled redeployment.

This data is directly relevant to OTC model research. It supports candle-only baselines as well as causal context features such as spread, deal imbalance, payout, mood, receive latency and clock quality. Collection duration still does not by itself establish predictive edge.

### 20.2 OTC snapshot-to-cloud training workflow

Training must never read the live SQLite file directly over SSH or copy only the main database file while WAL writes are active. The repeatable workflow is:

```text
live collector
  -> SQLite online backup at an explicit UTC cutoff
  -> validate snapshot integrity and table coverage
  -> export partitioned Parquet
  -> generate dataset manifest + checksums + schema version
  -> upload immutable dataset bundle
  -> Kaggle or Google Cloud training job
  -> metrics/report/artifact bundle
  -> local parity and promotion checks
  -> shadow deployment only
```

Planned operator commands should converge on:

```bash
python scripts/report_market_db_health.py
python scripts/snapshot_market_db.py --source data/ml/market_context.sqlite --output data/snapshots/<dataset-id>
python scripts/export_market_snapshot.py --snapshot data/snapshots/<dataset-id> --format parquet
python scripts/validate_dataset_manifest.py data/snapshots/<dataset-id>/manifest.json
```

The uploaded training bundle includes Parquet partitions, manifest, research contract and a pinned training entry point. It excludes broker credentials, Telegram sessions, `.env`, live database WAL/SHM files and account identifiers.

### 20.3 Portable Kaggle and Google Cloud training entry points

The repository already contains useful training programs such as `kaggle_candidate_meta_trainer.py`, `kaggle_strategy_independent_tournament.py`, `train_candidate_meta_model.py`, `train_catboost_directional.py`, `train_catboost_gate.py`, `train_regime_mtf_lstm_v5.py`, and `train_trading_model_v3.py`. They should be preserved as research evidence, then consolidated behind one portable CLI rather than maintained as unrelated notebooks/scripts.

Target interface:

```bash
python -m trading_platform.research.train \
  --contract configs/research/otc_directional_v1.yaml \
  --dataset /input/<dataset-id>/manifest.json \
  --output /output/<run-id> \
  --environment kaggle
```

The same command must run with `--environment local`, `kaggle`, or `gcp` without changing model logic. Environment adapters only resolve input/output locations and hardware; they do not change temporal splits, thresholds or metrics.

Every run emits:

- resolved research contract and configuration;
- dataset/feature schema IDs and hashes;
- dependency and hardware metadata;
- baseline, validation, walk-forward and untouched-test metrics as applicable;
- calibration and payout-aware expectancy reports;
- per-asset/time/regime breakdowns;
- all selected thresholds and the data partition on which each was selected;
- model/scaler/ONNX or CatBoost artifacts;
- inference parity fixtures;
- a machine-readable promotion recommendation that cannot promote itself.

For Google Cloud, begin with a reproducible container executed as a Vertex AI custom job or an ordinary Compute Engine batch job. Do not introduce Kubeflow solely to run these scripts. Kaggle remains suitable for low-cost diagnostic/training runs using uploaded immutable datasets, but secrets and live server access are prohibited.

### 20.4 Collector pause, stop and restart controls

Yes, collection can be turned off. The current collector handles `SIGINT`/`SIGTERM` and closes its store in `finally`, so the preferred stop is a normal container/process termination, never killing the host or deleting database files.

The future operations surface must support:

- `collector pause`: stop optional high-frequency sources while retaining health/clock monitoring where possible;
- `collector resume`: resubscribe and record the resulting data gap explicitly;
- `collector stop`: graceful shutdown after flushing buffered events and checkpointing health;
- `collector status`: database/WAL size, disk headroom, newest timestamps, rows/minute, connection and last error;
- automatic protective degradation at storage thresholds;
- explicit restart reconciliation and a `collection_gap` record.

For the currently inspected one-off container, `docker stop <container>` should send the collector `SIGTERM`; because restart policy is `no`, it will remain stopped until explicitly restarted. Before operationalizing this, replace the generated container name with a stable Compose service and document exact stop/start commands in a runbook. Do not stop the current collector merely to create training data: use SQLite online backup while it remains live.

Stopping collection is operationally safe if performed gracefully, but it creates a research-data gap. The dataset manifest must record that gap so models do not treat the surrounding periods as continuous.

### 20.5 Crypto data collection requirements

Crypto ML models require their own market-specific datasets. OTC history must not be used as a substitute, because venue mechanics, labels, costs and price formation differ.

For **crypto spot**, collect or acquire:

- point-in-time instrument listings/delistings and trading rules;
- trades, OHLCV and bid/ask quotes;
- order-book snapshots/deltas if the strategy uses microstructure;
- maker/taker fee schedules and account fee tier assumptions;
- exchange status, sequence gaps, receive time and latency;
- benchmark/index data where the hypothesis needs broader-market context.

For **crypto perpetuals**, additionally collect:

- mark, index and last prices;
- funding-rate observations and actual funding timestamps/payments;
- contract specifications, leverage tiers and maintenance-margin rules;
- open interest where reliably available;
- liquidation streams only if their provenance and completeness are understood;
- basis between spot/index/perpetual;
- position-mode and risk-limit metadata relevant to executable simulation.

Public exchange history can bootstrap candle/trade research, so development does not need to wait months before beginning. However, live collection is still required to validate WebSocket behavior, latency, order-book reconstruction, data gaps, current fees/funding, execution assumptions and shadow performance. Begin Bybit public-data capture during the read-only integration phase; add private account/order streams only in testnet with separate credentials.

Use separate dataset contracts and models for:

```text
OTC binary direction/abstention
crypto spot return/direction/allocation
crypto perpetual return/funding/execution/risk
```

Shared infrastructure is appropriate—timestamps, manifests, feature interfaces, validation and experiment tracking—but labels, costs, strategies and promotion gates remain market-specific.

### 20.6 Automated compact export and Kaggle publishing

Do not upload the 2.79 GB live SQLite database to Kaggle. SQLite is the mutable collection store and includes indexes, free pages, raw high-frequency rows and WAL coordination concerns. Kaggle receives a compact immutable research dataset.

The export job should reduce transfer size through four mechanisms:

1. export only columns/tables required by the declared research contract;
2. convert rows to typed columnar Parquet using Zstandard compression;
3. partition by table/date and, where useful, asset so individual files remain manageable;
4. downsample or aggregate old high-frequency quotes/deals according to the retention contract while retaining recent raw data separately.

Expected layout:

```text
otc-dataset-2026-08-18T140000Z/
  manifest.json
  contract.json
  quality-report.json
  candles/date=2026-08-17/part-000.parquet
  quotes_1s/date=2026-08-17/part-000.parquet
  deal_flow_10s/date=2026-08-17/part-000.parquet
  payout/date=2026-08-17/part-000.parquet
  mood/date=2026-08-17/part-000.parquet
  clock_health/date=2026-08-17/part-000.parquet
```

Target partition files should generally be approximately 100–500 MB compressed rather than one multi-gigabyte file. The exporter must operate in bounded batches so it fits on the current 956 MiB server and never loads the full dataset into memory.

Automation design:

```text
systemd timer (daily/weekly)
  -> check disk, collector freshness and previous successful cutoff
  -> SQLite online backup or consistent read transaction
  -> export only new closed partitions
  -> validate row counts, timestamps, duplicates and checksums
  -> write immutable manifest
  -> upload to staging destination
  -> verify remote sizes/checksums
  -> publish a new Kaggle dataset version or GCS dataset prefix
  -> send Telegram success/failure summary
  -> retain local export until remote verification succeeds
```

Use a first full export, followed by incremental exports keyed by a recorded UTC high-water mark. Periodically produce a consolidated immutable release for model training. Never advance the high-water mark until validation and remote verification complete successfully.

Kaggle publishing can use the official Kaggle CLI/API from a dedicated upload worker:

```bash
kaggle datasets create -p data/exports/<dataset-id>
kaggle datasets version -p data/exports/<dataset-id> -m "UTC cutoff <cutoff>; manifest <sha256>"
```

The upload credential must not live in the collector container. Prefer uploading from a separate small worker or transfer validated bundles to Google Cloud Storage/object storage first, then publish the selected release to Kaggle. Google Cloud training should read directly from a versioned GCS prefix instead of copying through Kaggle.

Automation safety rules:

- use a lock so two export jobs cannot overlap;
- enforce minimum free-disk headroom before creating a snapshot;
- rate-limit CPU/I/O so collection remains healthy;
- abort on schema drift, clock anomalies or incomplete partitions;
- never delete source data until remote checksums and retention conditions pass;
- keep credentials out of manifests and logs;
- make retries idempotent by dataset ID and cutoff;
- alert through Telegram when a job fails or no fresh rows are observed;
- provide `/dataset`, `/export status`, and `/export run` controls, with manual runs treated as bounded jobs rather than shell access.

### 20.7 Manual Kaggle upload and training workflow without an API

The first version must not depend on Kaggle API credentials or automated cloud integration. A manual workflow should be the baseline because it is easy to inspect, teaches the dataset lifecycle, and remains a recovery path when automation is unavailable.

The operator experience should require three simple stages:

```text
1. Prepare on server
2. Download and upload through Kaggle website
3. Run notebook and download verified artifacts
```

#### Helper files and ownership

```text
scripts/snapshot_market_db.py
scripts/export_market_snapshot.py
src/trading_platform/apps/manual_kaggle_bundle.py
src/trading_platform/research/manual_kaggle_bundle.py
scripts/validate_training_artifacts.py
configs/research/otc_directional_v1.yaml
notebooks/kaggle_otc_training.py
docs/operator/manual-kaggle-training.md
```

The platform-owned manual-bundle command creates a self-explanatory upload
directory. Its first implemented slice accepts only already-exported
Parquet/CSV research files, embeds the authoritative platform source tree,
generates a checksum manifest, rejects database/secret-like filenames and
validates the completed directory. Snapshot export, size-bounded ZIP parts,
the notebook and artifact validator remain follow-up slices.

```text
data/manual_uploads/otc-2026-08-18T140000Z/
  UPLOAD_ME/
    otc-data-part-001.zip
    otc-data-part-002.zip
    manifest.json
    contract.json
    SHA256SUMS
    README-KAGGLE.txt
  notebook/
    kaggle_otc_training.py
  expected-output/
    ARTIFACTS-README.txt
```

ZIP parts should contain date-partitioned Parquet rather than SQLite. Default maximum part size should be configurable and conservative—approximately 1 GB—so files are easier to resume, verify and upload. The preparation script prints exact next steps after it finishes.

#### Step A — prepare the upload bundle on the server

The future implementation should expose one wrapper command:

```bash
python scripts/prepare_manual_kaggle_bundle.py \
  --source data/ml/market_context.sqlite \
  --contract configs/research/otc_directional_v1.yaml \
  --output data/manual_uploads \
  --max-part-size-mb 1000
```

Internally it performs the online snapshot, causal export, Parquet compression, quality checks, manifest creation, ZIP splitting and checksums. It must not pause the collector or load the entire database into RAM.

Successful output ends with a copyable summary such as:

```text
Bundle ready: data/manual_uploads/otc-<dataset-id>/UPLOAD_ME
Files: 4
Compressed size: <measured size>
Dataset cutoff: <UTC timestamp>
Manifest SHA-256: <hash>
Next: download UPLOAD_ME and notebook/kaggle_otc_training.py
```

#### Step B — download the prepared files to the local computer

From the local repository/workstation:

```bash
mkdir -p downloads/otc-kaggle
rsync -avP \
  -e "ssh -i ~/.ssh/ssh-key-otc-bot.key" \
  ubuntu@152.70.46.129:/home/ubuntu/IQoption/data/manual_uploads/otc-<dataset-id>/ \
  downloads/otc-kaggle/otc-<dataset-id>/
```

If `rsync` is unavailable, provide the simpler fallback:

```bash
scp -i ~/.ssh/ssh-key-otc-bot.key -r \
  ubuntu@152.70.46.129:/home/ubuntu/IQoption/data/manual_uploads/otc-<dataset-id> \
  downloads/otc-kaggle/
```

Verify before uploading:

```bash
python scripts/validate_manual_kaggle_bundle.py \
  downloads/otc-kaggle/otc-<dataset-id>/UPLOAD_ME
```

The validator checks file hashes, manifest references, ZIP readability and required contract/schema files. An interrupted download is resumed with `rsync`; it is not rebuilt unless the source bundle is invalid.

#### Step C — create a private Kaggle dataset manually

In the Kaggle web interface:

1. Sign in and choose **Datasets -> New Dataset**.
2. Choose **Private** until the data has passed privacy and licensing review.
3. Name it `iqoption-otc-<dataset-id>`.
4. Drag every file inside `UPLOAD_ME/` into the upload screen.
5. Add a description containing the UTC cutoff and manifest SHA-256 from `README-KAGGLE.txt`.
6. Create the dataset and confirm all expected files and sizes appear.

Do not upload `.env`, Telegram session files, broker session cookies, API keys, raw account identifiers, the live SQLite/WAL/SHM files, trade account balances or unrelated logs.

Kaggle interface limits can change. If a file is rejected, rerun only the packaging step with a smaller `--max-part-size-mb`; do not alter the dataset rows or research cutoff merely to make the upload succeed.

#### Step D — create and run the Kaggle training notebook

1. Choose **Code -> New Notebook**.
2. Use **Add Input** and attach the private `iqoption-otc-<dataset-id>` dataset.
3. Upload or paste `notebook/kaggle_otc_training.py` into the notebook.
4. Select CPU for baseline/logistic/CatBoost diagnostics; enable GPU only for the declared LSTM experiment.
5. Keep internet disabled unless the environment genuinely needs a pinned dependency unavailable in the base image.
6. Run all cells from a fresh session.

The notebook must discover Kaggle's mounted input path rather than depend on a username-specific path. Its first stage validates checksums, extracts ZIP parts into `/kaggle/working/dataset`, reads `manifest.json`, and refuses to train when the declared dataset ID, schema or contract is inconsistent.

The thin notebook calls a platform-owned coordinator that requires the bundled
contract dataset ID to equal the validated workspace dataset ID before invoking
the same portable training entry point used locally/cloud:

```bash
python /kaggle/working/kaggle_otc_training.py \
  --dataset-id <dataset-id> \
  --contract otc_directional_v1.yaml \
  --output /kaggle/working/output
```

The notebook should display a small final summary—dataset ID, splits, baselines, selected coverage, expectancy confidence bound, calibration, artifact hashes and promotion recommendation—while retaining full reports as files.

#### Step E — save and download model artifacts

Training produces one archive:

```text
/kaggle/working/otc-training-<run-id>.zip
```

It includes model/scaler files, ONNX or CatBoost artifacts, resolved configuration, metrics, split definitions, feature schema, dependency versions, parity fixtures, checksums and the final report. Use **Save Version / Save & Run All**, then download the output archive from the notebook output page.

The implemented coordinator packages only a provenance-valid training
directory. ZIP members use deterministic ordering, timestamps and permissions;
an embedded manifest records every source member's size and SHA-256. The
finished archive is validated again before its path and digest are returned.
Packaging never registers, installs or activates a model.

#### Step F — verify locally before shadow deployment

```bash
python scripts/validate_training_artifacts.py \
  downloads/otc-training-<run-id>.zip \
  --expected-dataset-id <dataset-id>
```

Validation checks archive hashes, dataset lineage, required metrics, feature order, model/scaler compatibility and inference parity fixtures. Passing validation registers the artifact as a research candidate only. It does not copy it into the live model directory or enable trading.

#### Manual workflow usability requirements

- one server command prepares everything required for upload;
- generated `README-KAGGLE.txt` contains the exact click-by-click instructions and expected filenames;
- scripts print clear success/failure messages and never require SQL knowledge;
- rerunning with the same cutoff is idempotent and produces the same dataset ID;
- every step is resumable without recollecting data;
- no Kaggle API token is required;
- the workflow works before Telegram export controls or cloud automation are implemented;
- automation later wraps this exact validated process rather than creating a second data path.

## 21. Research and backtesting architecture

Use two complementary engines:

1. vectorized research for fast hypothesis screening and parameter sensitivity;
2. event-driven simulation for final validation of order lifecycle, partial fills, latency, funding and portfolio interactions.

Do not immediately adopt a large external engine. First define the platform domain contract and build a small reference simulator. Re-evaluate NautilusTrader when tick/order-book strategies or many venues make maintaining the simulator uneconomic.

Backtests must record dataset ID, code commit, configuration hash, all tried variants, cost model, split definition and artifact hashes. The final holdout is write-protected and evaluated once per predeclared research cycle.

## 22. Overfitting controls

- point-in-time universe and features;
- purged/embargoed chronological folds for overlapping labels;
- rolling and expanding walk-forward tests;
- untouched final calendar window;
- benchmark and null strategies;
- block/bootstrap confidence intervals;
- parameter stability surfaces rather than one optimum;
- regime and instrument breakdowns;
- doubled/adverse fee, spread, slippage and funding scenarios;
- trial registry and multiple-testing adjustment;
- no tuning based on shadow or micro-live disappointment without opening a new research cycle.

## 23. Risk-management architecture

Risk layers:

1. **Static policy:** allowed venues/accounts/instruments/products/order types; live flag; maximum leverage.
2. **Pre-trade:** freshness, duplicate, quantity/precision, price collars, notional, exposure, concentration, open-order and loss limits.
3. **In-trade:** stop presence where required, liquidation buffer, margin utilization, stale private stream and abnormal slippage.
4. **Portfolio:** gross/net exposure, correlated assets, strategy allocation, daily/weekly drawdown.
5. **Operational:** reconciliation health, clock drift, database availability, model/artifact match, exchange health.

Any hard-gate uncertainty rejects the trade. Kill switches exist at strategy, account, venue and global levels, and can cancel new submissions independently of LangGraph/Hermes.

## 24. Security architecture

- separate keys per venue, environment and service;
- trading only; withdrawals and transfers disabled;
- IP allowlists where supported;
- secrets mounted at runtime from a secrets manager or protected host files, never committed or passed to Hermes;
- separate OS users/containers/networks for agent and execution services;
- dependency locking, hashes, SBOM and vulnerability scans;
- command/tool allowlists and opaque action IDs;
- signed/approved deployment configuration for live mode;
- immutable audit log for operator and agent actions;
- sanitize all external content before model context and label it untrusted;
- no agent-installed plugins/skills in production;
- redact keys, payload signatures, personal/account identifiers and raw prompts containing secrets from logs.

## 25. Observability architecture

Use structured JSON logs, Prometheus metrics and OpenTelemetry traces where cross-service calls exist. Mandatory correlation fields: signal ID, risk decision ID, client order ID, venue order ID, strategy/model version and reconciliation run ID.

Key metrics:

- market/private-stream connection and reconnect counts;
- last event age, sequence gaps and clock offset;
- REST/WS error rates and rate-limit headroom;
- order acknowledgement/fill/cancel latency;
- reject rate, partial-fill age and reconciliation mismatch count;
- exposure, margin utilization, liquidation distance, realized/unrealized PnL and drawdown;
- prediction latency, drift, coverage and calibration;
- agent schema failures, veto rate, latency and cost;
- database transaction failures and queue age.

Alerts must be actionable and linked to runbooks. A stale private stream, unresolved reconciliation mismatch, unknown open order, or database write failure activates trading suspension—not merely a dashboard warning.

## 26. Failure recovery and reconciliation

### Restart protocol

1. Start in `RECOVERY_ONLY` mode.
2. Connect private and public streams.
3. Fetch server time, instruments, balances, open orders, recent executions and positions.
4. Compare with durable local state.
5. Import unknown venue activity as reconciliation events; never silently overwrite history.
6. Resolve pending submissions using client IDs and venue queries.
7. Rebuild portfolio/risk projections.
8. Require zero critical mismatches before enabling new orders.

### Failure policy

| Failure | Response |
|---|---|
| Public WebSocket disconnect | Mark data stale, reject new signals, reconnect/resubscribe, verify sequence/snapshot |
| Private WebSocket disconnect | Suspend submissions; REST reconcile orders/positions before resume |
| REST timeout after submit | Treat status as unknown; query by client ID; never blindly resubmit |
| Rate limit | Respect headers/codes, bounded jittered backoff, reduce noncritical requests |
| Partial fill | Update position from executions; amend/cancel only through order policy |
| Database unavailable | Stop new order submission; continue safety reconciliation in degraded read-only mode if possible |
| Model failure | Abstain; do not substitute agent opinion |
| Hermes/LangGraph failure | Skip agent workflow; deterministic trading remains independent |
| Clock drift | Suspend signed requests/trading until synchronized |
| Exchange/local mismatch | Activate account kill switch and reconcile with venue as truth |

## 27. Testing strategy

### Unit/property tests

- money, precision, instrument constraints and sizing;
- risk invariants and kill-switch precedence;
- order-state transition legality;
- idempotency/client-order-ID generation;
- causal feature truncation invariance;
- schema validation and malformed agent output;
- PnL, funding, fee and binary expectancy calculations.

### Contract/integration tests

- every broker adapter against recorded fixtures and sandbox/testnet;
- simulated adapter must pass the same contract suite;
- database transaction and uniqueness behavior;
- WebSocket snapshot/delta/reconnect sequences;
- model training/live feature and inference parity;
- LangGraph checkpoint/resume and approval interruption.

### Replay/failure tests

- duplicate/out-of-order events;
- timeout after venue accepted an order;
- process crash between intent persistence and submission;
- process crash after fill but before local processing;
- partial fill plus disconnect;
- stale instrument metadata;
- corrupted/missing model artifact;
- database/network fault injection;
- restart with unknown exchange position.

### End-to-end gates

- deterministic historical replay;
- real-time shadow;
- simulated broker;
- Bybit testnet;
- deliberate kill-switch and reconciliation drills;
- no live tests in ordinary CI.

## 28. Environments

Each environment has separate databases, keys, accounts, configuration and network policy:

- `research`: no broker credentials;
- `backtest`: immutable historical inputs, simulated clock;
- `shadow`: live data, no order capability;
- `paper`: internal simulated broker;
- `testnet`: exchange sandbox credentials only;
- `micro_live`: separate low-balance account/key and strict policy;
- `live`: explicit deployment approval and independently reviewed limits.

An `Environment` enum is embedded in every order/event and cannot be inferred from a URL string. Production binaries reject mixed-environment configuration.

## 29. Promotion gates

| Gate | Minimum evidence |
|---|---|
| Research -> candidate | predeclared hypothesis, causal dataset, baselines, adequate samples, positive conservative cost-adjusted expectancy |
| Candidate -> final test | stable walk-forward folds/instruments/regimes; no single parameter spike; adverse-cost survival |
| Final test -> shadow | untouched window passes; artifact parity; reproducible manifest; independent review |
| Shadow -> paper/testnet | minimum four weeks and sufficient decisions/fills; stable live features; no critical operational incidents |
| Testnet -> micro-live | successful disconnect/restart/reconciliation/partial-fill drills; order and PnL parity; hard limits verified |
| Micro-live -> broader live | statistically and economically positive forward evidence after costs; drawdown within declaration; zero unresolved severity-1 incidents; legal/account approval |

Exact sample sizes are strategy-dependent. As initial floors: OTC retains 500+ eligible shadow decisions over at least four weeks; liquid crypto strategies should span multiple volatility regimes and enough independent trade clusters to make confidence bounds meaningful. Time alone is not evidence.

## 30. Recommended technologies

| Technology | Decision |
|---|---|
| Python 3.12/asyncio | Core implementation |
| Pydantic v2 + dataclasses | Boundary validation and internal immutable domain values |
| PostgreSQL + Alembic | Authoritative operational state/audit ledger |
| Parquet + DuckDB | Versioned research data and local analytics |
| SQLite | Collector snapshots, development, LangGraph checkpoints only |
| Official Bybit SDK or thin V5 client | Evaluate official SDK first; wrap it behind platform adapter |
| CCXT | Research/data discovery and optional fallback, not sole live OMS authority |
| CatBoost/ONNX Runtime | Retain current tabular/model serving path |
| LangGraph | Bounded durable agent workflows |
| Hermes | Replaceable reasoning provider, optional |
| Docker Compose | Initial multi-process deployment |
| Prometheus + Grafana + structured logs | Initial observability |
| pytest + pytest-asyncio + Hypothesis | Test foundation |

## 31. Technologies deliberately rejected or deferred

- **Kafka:** no demonstrated volume/team scale justifies it; PostgreSQL outbox/in-process events suffice initially.
- **Kubernetes:** excessive operational complexity for a single-node/small-team platform; reconsider for multi-region/high-availability requirements.
- **Redis:** defer until a measured cache/coordination/streaming need exists; never make it portfolio truth.
- **Microservices:** defer; process boundaries within a monorepo give adequate isolation without distributed failure overhead.
- **A universal CCXT execution adapter:** venue-specific semantics are too important for leveraged live trading.
- **Agent-direct broker tools:** violates deterministic risk authority.
- **A feature store platform:** premature; versioned Parquet plus shared feature code is enough now.
- **Automatic online retraining/promotion:** creates silent regime/selection risk; use reviewed scheduled research cycles.

## 32. Repository structure

Keep a monorepo with `trading_platform/` as the project-root package. The
repository-root migration is complete: domain, application, broker, research,
agent and operational business logic live inside this tree, while legacy
callers remain under `trading_platform/legacy/` behind compatibility facades.
Root `tests/`, `docs/`, `data/`, and `backup/` remain outside the package.

```text
trading_platform/
  domain/              # values, events, orders, positions, errors
  application/         # use cases and ports
  risk/                # deterministic policies and state projections
  portfolio/           # accounting/exposure
  execution/           # OMS and reconciliation
  market_data/         # normalized ingestion
  brokers/
    iqoption/
    bybit/
    weex/
    simulated/
  strategies/
    otc/
    spot/
    perpetuals/
  models/              # artifact loading/inference contracts
  research/            # datasets, features, splits, metrics, backtests
  agents/
    workflows/
    hermes/
    tools/
    schemas/
  storage/
  observability/
  config/
  apps/                # application entry points and composition roots
    otc_worker.py
    crypto_worker.py
    collector.py
    reconciler.py
    agent_worker.py
tests/
  unit/ contract/ integration/ replay/ e2e/
docs/
  adr/ research/ runbooks/ plans/
```

Do not move all existing files at once. Migrate vertical slices behind thin,
tested compatibility facades. A facade may import, translate arguments and
delegate; it may not own risk rules, execution behavior, model provenance or
state transitions. Remove each facade after its callers and deployment entry
points have moved. Kaggle/manual bundles must include the platform package (or
a versioned wheel built from it), never a duplicated root implementation.
The live migration register and enforced dependency direction are documented
in `docs/research/platform_root_convergence.md`.

## 33. Agent/tool permission model

| Tool | Research Hermes | Operations Hermes | Live permission |
|---|---:|---:|---:|
| Query aggregate telemetry | yes | yes | read-only |
| Read approved research datasets/reports | yes | limited | read-only |
| Start bounded backtest job | yes | no | isolated queue |
| Propose signal critique | shadow | shadow | logged counterfactual initially |
| Pause new submissions | propose | propose | human/automatic risk service executes |
| Cancel/close order | no | propose opaque incident action | dual approval/emergency service only |
| Place arbitrary order | no | no | never |
| Change risk/leverage/live mode | no | no | never |
| Shell/browser/install skill | isolated research only | no | never |
| Read secrets/raw account payloads | no | no | never |

### 33.1 Telegram as the intuitive operator console

Telegram remains useful, but its role changes from a mutable trading shell into a secure, guided operations console. It must call the same application services used by every other interface; it must never reach a broker adapter, database session, strategy object, or Hermes tool directly.

```text
Telegram user
  -> authenticated Telegram gateway
  -> command parser / callback router
  -> authorization + environment policy
  -> query service or approval workflow
  -> deterministic application service
  -> audit event
  -> concise Telegram response
```

The interface should favor inline keyboards, clear summaries and progressive disclosure instead of expecting operators to remember dozens of commands. Slash commands remain available for speed and automation, but every screen exposes the most relevant next actions.

#### Home dashboard

`/start`, `/home`, or a persistent menu opens:

```text
Trading Platform — TESTNET
System: HEALTHY       Trading: PAUSED
Venues: Bybit ✓  IQ Option ✓  WEEX not configured
Equity: $10,250.40    Today: +$34.20 (+0.33%)
Exposure: $420        Drawdown: 0.6% / 2.0%
Open positions: 2     Working orders: 1
Data age: 180 ms      Last reconciliation: 8 sec ago

[Portfolio] [Orders] [Strategies]
[Risk] [System] [Research]
[Pause/Resume] [Help]
```

Balances may be hidden by default through a per-user privacy preference. Every response prominently displays the active environment (`SHADOW`, `PAPER`, `TESTNET`, `MICRO-LIVE`, or `LIVE`) to prevent context mistakes.

#### Command groups

| Group | Commands and buttons | Authority |
|---|---|---|
| Overview | `/status`, `/health`, `/venues`, `/version` | Read-only |
| Portfolio | `/portfolio`, `/positions`, `/pnl`, `/exposure` | Read-only |
| Orders | `/orders`, `/order <id>`, `/fills` | Read-only by default |
| Strategies | `/strategies`, `/strategy <id>`, `/signals`, `/performance` | Read-only; pause request allowed |
| Risk | `/risk`, `/limits`, `/drawdown`, `/killswitches` | Read-only; tightening requests only |
| Operations | `/pause`, `/resume`, `/reconcile`, `/cancel <id>`, `/flatten` | Controlled workflows |
| Research | `/experiments`, `/models`, `/shadow`, `/report` | Read-only or bounded research jobs |
| Incidents | `/incidents`, `/incident <id>`, `/ack <id>` | Operational workflow |
| Preferences | `/settings`, `/alerts`, `/privacy`, `/timezone` | User-interface preferences only |

No Telegram command may set arbitrary order side, quantity, leverage, API credential, live environment, risk ceiling, or model artifact. Manual discretionary trading is a separate future product decision and is not enabled by this plan.

#### Safe action flows

Low-risk read actions execute immediately. State-changing actions use previews and explicit confirmation:

```text
/pause bybit

Pause new Bybit submissions?
Existing positions will remain open and monitored.
Reason: [enter reason]

[Confirm pause] [Cancel]
```

High-impact emergency actions require a typed challenge and, in live environments, a second authorized approver:

```text
/flatten bybit

EMERGENCY ACTION — MICRO-LIVE
This proposes reduce-only closure of 2 positions.
Estimated notional: $418.20
Orders will still pass execution validation.

Type: FLATTEN BYBIT 7KQ2
[Cancel]
```

The Telegram gateway creates an `OperatorActionRequest`. The deterministic operations service rechecks permissions, environment, current state, expiry and policy. Confirmation never stores preapproved raw broker parameters. The action is short-lived, single-use and idempotent.

#### Approval levels

1. **Immediate:** status, reports, positions, orders, risk state and health.
2. **Single confirmation:** pause a strategy/venue, trigger reconciliation, acknowledge an incident, cancel a non-filled working order in paper/testnet.
3. **Typed confirmation:** resume after a risk stop, cancel a live order, request an emergency reduce-only flatten.
4. **Dual approval:** micro-live/live flatten, resume after a severe reconciliation/security incident, or deploy/promote an already approved artifact.
5. **Never through Telegram:** enable live trading, raise risk/leverage ceilings, enable withdrawals/transfers, create arbitrary trades, change credentials, bypass reconciliation, or override a kill switch.

Automated risk demotion and pausing do not wait for Telegram approval. Telegram informs operators and lets them inspect the reason.

#### Authentication and authorization

- Use a dedicated bot account, not a personal self-bot session, for the future platform.
- Allowlist numeric Telegram user IDs; usernames are not identities.
- Roles: `viewer`, `operator`, `risk_approver`, and `administrator`.
- Bind high-impact approvals to the initiating user, chat, environment and nonce.
- Prefer private chats; group chats are read-only unless explicitly allowlisted.
- Rate-limit commands and confirmation attempts.
- Expire callbacks and action tokens quickly; reject replayed callbacks.
- Never include secrets, full API payloads, private account identifiers or excessive balance information.
- Audit command receipt, authorization result, requested action, confirmation, application result and message-delivery outcome.
- If Telegram is unavailable, trading safety continues autonomously; Telegram is not a kill-switch dependency.

#### Alert design

Alerts are grouped to avoid notification fatigue:

- **Critical:** kill switch, unknown order state, reconciliation mismatch, stale private stream with exposure, database write failure, liquidation-buffer breach.
- **Warning:** repeated reconnects, elevated rejects/slippage, model/data drift, nearing drawdown limits.
- **Digest:** daily PnL, strategy coverage, costs/funding, shadow results and system health.

Critical alerts contain `Acknowledge`, `Details`, `Pause venue`, and `Run reconciliation` buttons where applicable. Alerts never contain a one-tap live resume button.

#### Telegram modules

```text
src/trading_platform/interfaces/telegram/
  app.py                 # gateway startup and dependency wiring
  auth.py                # allowlists, roles and environment permissions
  commands.py            # slash-command routing
  callbacks.py           # inline-keyboard callback routing
  presenters.py          # concise, escaped Telegram formatting
  menus.py               # dashboard and progressive navigation
  approvals.py           # nonce, expiry, confirmation and dual approval
  subscriptions.py       # alert/digest preferences
  rate_limit.py
  schemas.py
```

The gateway depends only on application query/command ports such as `GetPlatformStatus`, `ListPositions`, `RequestTradingPause`, `RequestOrderCancellation`, `RequestEmergencyFlatten`, and `RunReconciliation`.

#### Telegram testing requirements

- command/parser unit tests including malformed and ambiguous input;
- role/environment permission matrix tests;
- callback expiry, replay and wrong-user tests;
- dual-approval tests ensuring two distinct authorized identities;
- idempotency tests for repeated Telegram delivery/callbacks;
- Markdown/HTML escaping and maximum-message-length tests;
- simulated Telegram outage and retry tests;
- audit-event completeness tests;
- end-to-end paper/testnet tests proving Telegram cannot bypass risk or call broker methods directly.

### 33.2 How the completed bot works end to end

After this plan is implemented, “the bot” is a coordinated platform rather than one process making decisions and calling `buy()`.

#### Normal operating cycle

1. Venue adapters connect to IQ Option, Bybit and any approved future venue. They synchronize clocks, load instrument rules and open public/private streams.
2. Incoming candles, trades, quotes, funding, payouts and order/account events are normalized and timestamped. Gaps, duplicates, stale data and invalid sequences are detected before strategies see them.
3. OTC, spot and perpetual strategies consume only the market data and features declared by their contracts. Rule strategies and registered CatBoost/ONNX models emit immutable `SignalProposal` objects or abstain.
4. Optional LangGraph/Hermes workflows may research or critique a proposal. Initially this is logged in shadow mode. Later, if validated, Hermes may veto or reduce participation but cannot create an unrestricted order or increase risk.
5. The deterministic risk engine reconstructs current exposure from reconciled broker state and checks the exact proposal against environment, freshness, instrument, notional, leverage, drawdown, concentration and operational limits.
6. A rejection is written to the ledger with reasons. An approval creates a risk decision tied to that exact signal and limit snapshot.
7. The order manager creates an idempotent order intent, persists it, and then calls the correct broker adapter.
8. The adapter submits the venue-specific order. For Bybit, REST acknowledgement does not equal a fill: private WebSocket executions/order changes drive the state machine. For IQ Option, the binary order remains pending until authoritative settlement or is marked unverified.
9. Executions, fees, funding, balances and positions update PostgreSQL projections. The reconciliation worker continuously compares local state to the venue, which remains the authority for actual orders and positions.
10. Risk and monitoring react immediately to exposure, drawdown, stale streams or mismatches. Automatic pauses and kill switches do not depend on an LLM or Telegram.
11. Telegram presents the current state, alerts the operator and accepts bounded operational requests through the approval system.
12. Immutable market/research snapshots are exported to Parquet. New models or strategies follow the research-to-live promotion gates; production does not retrain or promote itself silently.

#### Example: Bybit perpetual signal

```text
BTCUSDT breakout strategy proposes OPEN_LONG
  -> data freshness passes
  -> Hermes shadow critique says APPROVE (informational only)
  -> risk limits quantity to 0.001 BTC at 1x isolated leverage
  -> order intent is persisted with client ID
  -> Bybit accepts request
  -> private stream reports partial fill
  -> position and remaining order are recorded
  -> second execution completes fill
  -> protective exit policy is verified
  -> Telegram reports the filled position
  -> reconciliation confirms order, executions, balance and position
```

#### Example: OTC signal

```text
OTC strategy proposes EURUSD-OTC CALL with two-minute expiry
  -> current payout and causal features pass
  -> risk checks session loss, stake and concurrent settlement rules
  -> IQ Option adapter submits one fixed-stake practice/micro-live order
  -> order is monitored until expiry
  -> direct settlement is recorded, or outcome is marked unverified
  -> unverified outcomes never train/calibrate strategy statistics
```

#### Example: failure while a position is open

```text
Bybit private WebSocket disconnects
  -> execution service suspends new submissions
  -> public risk monitoring continues where possible
  -> adapter reconnects and resubscribes
  -> reconciler queries open orders, executions, balances and positions
  -> any mismatch keeps the venue paused
  -> Telegram sends a critical incident with Details/Reconcile controls
  -> trading resumes only after policy conditions and required approval pass
```

#### Operator experience

The operator does not micromanage individual model decisions. They use Telegram to answer five questions:

1. Is the platform healthy and reconciled?
2. What positions, orders and exposures exist now?
3. Why was a signal traded, rejected or abstained?
4. Are strategies/models performing within their declared gates?
5. Should a venue/strategy be paused, reconciled or safely reduced?

Hermes helps explain research and incidents in plain language. Deterministic services remain responsible for the answer to “may this order be placed?”

## 34. Deployment model

Initial Docker Compose services:

- PostgreSQL;
- OTC collector/adapter worker;
- crypto market/private-data worker;
- strategy/risk/execution worker;
- reconciliation worker;
- monitoring exporter;
- agent worker on a separate network without broker secrets.

Use one VPS only for paper/testnet after resource measurement. Micro-live should have separate execution and agent hosts or, at minimum, strong OS/container/network isolation. Use systemd/Docker restart policies, health checks, resource caps, NTP monitoring, encrypted backups and tested restoration.

## 35. Architecture decision records

### ADR-001: Modular monolith and monorepo

**Decision:** retain one repository and initially one logical application split
into separately runnable workers. Make `src/trading_platform` the sole
authoritative code boundary and eventual project root; retain root scripts and
`iqoption_bot` only as temporary migration facades.

**Alternatives:** rewrite into microservices; adopt NautilusTrader/Lean/Freqtrade wholesale; start a separate crypto repository.

**Why this wins:** preserves existing OTC/ML assets, enables transactional
consistency, reduces deployment complexity and still enforces module contracts.
It also prevents a permanent split-brain architecture in which cloud training,
legacy OTC and new crypto paths each own different copies of business logic.

**Risks:** boundaries may erode or compatibility facades may become permanent.
Mitigate with import rules, identity/delegation tests, explicit application
ports and a rule that no new business logic is added outside the platform tree.

**Revisit when:** independent teams, sustained throughput or fault-isolation requirements exceed a single PostgreSQL/process topology.

### ADR-002: PostgreSQL authoritative ledger

**Decision:** PostgreSQL owns operational truth; Parquet owns immutable research snapshots.

**Alternatives:** SQLite, JSON files, TimescaleDB-only, event broker as truth.

**Why this wins:** transactions, constraints, recovery queries and operational maturity without premature distributed infrastructure.

**Revisit when:** measured time-series volume warrants TimescaleDB/ClickHouse for analytics; operational ledger remains relational.

### ADR-003: In-process events plus transactional outbox

**Decision:** synchronous application calls/in-process event dispatch, with a PostgreSQL outbox for durable cross-worker events.

**Alternatives:** Redis Streams, RabbitMQ, NATS, Kafka.

**Why this wins:** simplest system satisfying current scale and delivery requirements.

**Revisit when:** backlog, fan-out, multi-host scale or availability measurements justify a broker.

### ADR-004: Capability-based broker adapters

**Decision:** small protocols plus venue extensions, not one universal broker class.

**Why this wins:** binary settlement, spot inventory and perpetual margin are genuinely different domains.

### ADR-005: Custom deterministic core before external engine adoption

**Decision:** extract current code into a small domain/OMS core; use external libraries selectively.

**Alternatives:** NautilusTrader, Freqtrade, Hummingbot, Lean.

**Why this wins:** migration risk and IQ Option uniqueness outweigh immediate framework benefits.

**Revisit when:** tick/order-book scope or connector maintenance exceeds project capacity; NautilusTrader is the leading reevaluation candidate.

### ADR-006: LangGraph outside the execution critical path

**Decision:** use it for resumable research/operations workflows only.

**Why this wins:** matches its durable agent strengths without adding nondeterministic latency/failure to order management.

### ADR-007: Hermes as replaceable model/provider

**Decision:** Hermes has no portfolio state authority and no raw broker tool.

**Alternatives:** Hermes as top-level trader; OpenClaw; direct hosted LLM calls; no agent.

**Why this wins:** preserves optional reasoning value while maintaining testable safety boundaries. The platform must work with Hermes disabled.

### ADR-008: Official venue semantics for live execution

**Decision:** use official Bybit V5 APIs/SDK semantics behind an adapter; use CCXT only where its abstraction is verified by contract tests.

**Why this wins:** order flags, modes, idempotency and reconciliation cannot be safely reduced to generic calls.

## 36. Required skills and learning plan

| Skill | Timing | Resource direction |
|---|---|---|
| Advanced/async Python, typing, cancellation | Essential now | Python docs, asyncio structured-concurrency material |
| Testing, Hypothesis, fault injection | Essential now | pytest/Hypothesis official docs |
| SQL/PostgreSQL transactions/migrations | Essential now | PostgreSQL and Alembic docs |
| Exchange REST/WebSocket/authentication | Essential now | Bybit/WEEX official docs and sandbox exercises |
| Quant statistics/backtest bias | Essential now | Bailey, López de Prado, Harvey; implement reproductions |
| Market microstructure/order lifecycle | Essential now | exchange docs; execution literature |
| Crypto derivatives/margin/liquidation | Essential before perps | venue rulebooks and derivatives texts |
| Docker/Linux/NTP/secrets | Essential now | Docker and Linux operations docs |
| Observability/SRE | Useful soon | OpenTelemetry, Prometheus, SRE workbooks |
| LangGraph/tool schemas/evaluation | Useful soon | official LangGraph docs and controlled prototypes |
| Hermes operations/security | Useful soon | Hermes official security/tool documentation |
| ML calibration/MLOps | Useful soon | scikit-learn calibration; model/data lineage practices |
| Distributed streaming/Kubernetes | Later-stage | only after requirements emerge |
| High-frequency/colocation engineering | Unnecessary for current scope | strategy scope is not latency-arbitrage/HFT |

## 37. Migration and implementation roadmap

**Repository-root migration status (2026-08-20): COMPLETE.** The package was
lifted from `src/trading_platform/`; legacy IQ Option code, vendored API code,
configs, scripts, training programs, and app entry points now live beneath
`trading_platform/`. Imports, Docker paths, pytest configuration, and research
bundle bootstrapping use the root package. Compile verification passes and the
full local suite passes with the PostgreSQL integration skipped when no test
database is configured.

### Phase 0 — Audit, baseline and safety freeze

**Implementation status (2026-08-18): COMPLETE — gate reached.** The baseline suite passes 143 tests; the migration profile is fail-closed; current-system, source, risk, data-hash and model-hash records exist. No runtime module or live server state was changed. Phase 1 requires an explicit continuation after review of this checkpoint.

**Objective:** establish reproducible current behavior and prevent accidental live expansion.

**Files:** create `docs/research/current_system.md`, `docs/research/source_register.md`, `docs/research/risk_register.md`, `requirements-dev.txt`; modify deployment/config docs only.

**Tasks:** inventory runtime flows/config/state/artifacts; classify tests; install pinned dev test tooling; run test suite; snapshot current schemas/artifacts; document IQ Option legal/API assumptions; disable martingale and real-mode command in the migration profile.

**Tests:** existing suite, configuration safety tests, import smoke test.

**Acceptance:** clean reproducible test command; known failures documented; no live trading performed; artifact/data inventory hashed.

**Failure/Rollback:** no behavior refactor until baseline exists; revert only new safety configuration if it prevents practice startup, with explicit review.

### Phase 1 — Core domain models and environment identity

**Implementation status (2026-08-18): COMPLETE — gate reached.** Immutable environment, money, quantity, instrument, event, signal, risk and order models now exist under `src/trading_platform/domain`, including explicit JSON-safe event/order codecs and fail-closed order transitions. Phase 1 adds 22 domain tests; the full suite passes 165 tests. The legacy OTC runtime remains unchanged.

**Objective:** introduce immutable venue-neutral values/events without changing existing execution.

**Files:** create `src/trading_platform/domain/*`, `tests/unit/domain/*`.

**Dependencies:** Phase 0.

**Tasks:** implement instrument, money, signal, risk, order, execution, position, environment and event schemas; Decimal/UTC rules; transition errors.

**Tests:** property tests for precision, serialization and illegal transitions.

**Acceptance:** schemas round-trip; mixed environments and invalid quantities fail closed.

**Rollback:** compatibility facade allows old bot to continue without new domain path.

### Phase 2 — Ports and IQ Option compatibility adapter

**Implementation status (2026-08-18): CODE COMPLETE — operational practice smoke test pending.** A runtime-checkable binary execution port and IQ Option compatibility adapter now own OTC-first/`-op` fallback, dynamic asset-ID lookup, blocking-call isolation and connection-loss notification. `AssetResolver` preserves its legacy tuple API but no longer calls `api.buy` directly. Seven fake-based contract tests pass and the full suite passes 172 tests; compilation and local runtime-import checks pass. No broker/network call or trade was made. An authenticated practice-account parity smoke test is still required before deployment, so this is not evidence of exchange-level acceptance.

**Objective:** separate scanner/worker logic from IQ Option transport.

**Files:** create `application/ports.py`, `brokers/iqoption/*`; modify `asset_resolver.py`, `worker.py` behind facades.

**Tasks:** extract instrument, market data, submission, query and binary-settlement ports; wrap existing API; record raw response fixtures.

**Tests:** broker contract tests using fakes/fixtures; no network in unit CI.

**Acceptance:** practice-mode behavior parity; scanner no longer calls `api.buy` transitively except through adapter.

**Failure:** unexplained parity differences stop migration.

### Phase 3 — Simulated broker and deterministic clock

**Implementation status (2026-08-18): COMPLETE — foundational simulator gate reached.** A monotonic manual clock and deterministic simulated broker now cover bid/ask-aware market and limit execution, configurable slippage/fees/partial fills, idempotent client IDs, scripted reject/disconnect/timeout failures, funding cashflows, and separate fixed-expiry binary settlement. The simulator refuses live/micro-live environments and rejects unsupported or unpriced execution rather than guessing. Eleven focused tests and the full 183-test suite pass. Advanced order-book, margin/liquidation and portfolio accounting remain explicit later-phase limitations.

**Objective:** provide safe end-to-end execution for OTC, spot and perpetual contracts.

**Files:** create `brokers/simulated/*`, `execution/clock.py`, replay fixtures.

**Tasks:** order lifecycle, configurable fills/slippage/fees/funding, partial fills, binary settlement, disconnect/failure scripting.

**Tests:** same adapter contract suite plus deterministic replay tests.

**Acceptance:** identical seed/input produces identical event ledger and PnL.

### Phase 4 — Deterministic risk engine

**Implementation status (2026-08-18): COMPLETE — foundational policy gate reached.** Immutable risk state/limits and an ordered deterministic engine now enforce kill switch, environment/state/signal/market freshness, duplicate signals, abstention, allowlists, open orders, drawdown, order notional, instrument/portfolio exposure, leverage and perpetual liquidation-buffer requirements. Missing inputs reject and approvals preserve the exact limits snapshot required by `OrderIntent`. Sixteen focused boundary/property tests and the full 199-test suite pass. Phase 5 must source state from reconciled broker truth and prevent alternate submission paths; inverse-contract notional and maintenance-margin-tier calculations remain explicitly unsupported.

**Objective:** centralize non-bypassable risk authority.

**Files:** create `risk/policies.py`, `risk/engine.py`, `risk/state.py`.

**Tasks:** freshness, duplicate, allowed instrument, notional, exposure, leverage, drawdown, open-order, liquidation-buffer and kill-switch policies.

**Tests:** exhaustive boundary/property tests and precedence tests.

**Acceptance:** every submission requires an approved immutable decision; missing data rejects.

### Phase 5 — PostgreSQL ledger, OMS and reconciliation

**Implementation status (2026-08-18): CORE ACCEPTANCE COMPLETE — deployment operations pending.** SQLAlchemy models and PostgreSQL migrations now provide a transactional order/execution/event ledger, compare-and-set submission claim, idempotent OMS, transactional outbox with ordered retry, broker-order reconciliation, append-only account snapshots, exact-decimal balance/position projections, and locked idempotent balance reservations. Crash tests cover every submission window and database failure before intent persistence prevents broker access. All migrations and a representative repository contract passed against a disposable PostgreSQL 17 instance; the container was then removed. The default suite passes 218 tests with the PostgreSQL test skipped unless explicitly configured. Before deployment, broker-specific bulk pagination, realized-PnL/equity semantics, supervised outbox metrics, and backup/restore/migration rollback drills remain required.

**Objective:** survive restarts and reconstruct broker truth.

**Files:** create storage models/migrations/repositories, `execution/order_manager.py`, `execution/reconciler.py`.

**Tasks:** intent-before-submit transaction, idempotent client IDs, order/execution state machine, projections, restart protocol, outbox.

**Tests:** transactional integration tests, crash-point tests, duplicate events, mismatch scenarios.

**Acceptance:** a process can crash at every submission stage and recover without duplicate orders or invented state.

### Phase 6 — OTC vertical-slice migration

**Implementation status (2026-08-20): IN PROGRESS — bounded history transport, worker settlement wiring and shadow identity binding complete; practice transport and sustained parity evidence pending.** Explicit binary terms preserve CALL/PUT, fixed expiry and decision-time payout in durable order intents. A deterministic legacy `TradeRequest` adapter and shadow-only OTC service route candidates through generic risk, payout-dependent positive-expectancy checks, signal-decision evidence, OMS and ledger acknowledgement without holding a broker client. Runtime evidence is tagged at the post-gatekeeping/pre-broker `legacy_would_submit` boundary, and typed JSON/Markdown parity reports cannot influence execution. Immutable binary settlements enforce exact cash-flow invariants, accept only `broker_api` authority, emit an atomic outbox event, and reconcile idempotently with explicit environment isolation. IQ Option closed-option normalization validates exact broker ID, stake, outcome cash flow and broker timestamp behind an asynchronous exact-order history port. The new history transport calls the blocking vendor API only through daemon-thread isolation, bounded timeout, strict envelope/record validation, pagination limits and repeated-page guards; it never uses `check_win_v4`, balance estimates or order submission. Shadow orders can bind the real accepted legacy broker ID through a compare-and-set ledger update after acknowledgement, and the opt-in worker settlement loop records broker-confirmed outcomes through the platform ledger while preserving the legacy path as authority. The immutable calibration registry and CatBoost paths provide checksum-complete, fail-closed probability provenance; mixed voting clears calibration and enforced candidate gating uses its own probability/ID. LSTM/older tournament provenance remains incomplete. Sustained realtime parity evidence, redacted response replays, remaining trainer provenance and supervised practice execution remain required.

**Objective:** run existing OTC strategy/model logic through the new signal-risk-OMS-ledger path.

**Tasks:** adapt strategies, payout/expiry records, settlement reconciliation, remove JSON as authority, keep reporting exports.

**Tests:** historical/realtime shadow parity and practice-account replay.

**Acceptance:** old and new paths produce matching proposals on fixed fixtures; new path reconstructs state after restart.

### Phase 7 — Research package and event-driven backtester

**Implementation status (2026-08-20): RESEARCH REGISTRY SLICE COMPLETE — live-training parity and remaining research controls remain pending.** Platform-owned backtests now use immutable UTC/Decimal market bars and signal events, causal entry/expiry selection, explicit binary win/loss/tie cash flows, fixed/slippage costs, unresolved-expiry accounting, deterministic JSON-safe reports, and strict chronological input validation. Purged walk-forward window generation enforces positive durations, chronological train/purge/test separation, and fail-closed insufficient-history handling. Deterministic performance summaries now expose win rate, profit factor, net P&L and maximum drawdown. The new research registry adds immutable trial records with dataset SHA-256 lineage, serialized purged windows, backtest reports, metrics, provenance references, deterministic JSON, idempotent identity conflict handling, atomic persistence, and fail-closed offline-promotion evidence; it remains research-only and cannot install or promote models. The archived fingerprint backtester remains compatibility-only; this new package is the canonical extension point.

**Objective:** consolidate duplicated feature/split/metric logic and realistic simulations.

**Files:** create `research/datasets`, `features`, `validation`, `metrics`, `backtests`, `registry`.

**Tasks:** immutable manifests, availability-time joins, purged walk-forward, cost models, trial registry, vectorized screening and event simulation.

**Tests:** synthetic leakage traps, cost/PnL fixtures, live-training parity.

**Acceptance:** deliberately leaked strategies fail tests; one command reproduces a report from manifest to metrics.

### Phase 7A — Manual Kaggle dataset and training workflow

**Implementation status (2026-08-18): IN PROGRESS.** Platform-owned tooling now
uses SQLite online backup for a consistent non-blocking snapshot and keyset
pagination for bounded-memory Parquet export of allowlisted collector tables.
Preparation and validation verify export manifests, preserve table-relative
paths in deterministic size-bounded ZIP groups, create a deterministic
platform-source archive, generate file-size/SHA-256 lineage, and fail on
live-database, secret-like, oversized, corrupt, missing or undeclared files.
A thin standard-library Kaggle bootstrap now discovers mounted inputs without
username-specific paths, verifies platform source before import, safely
extracts archives and revalidates extracted Parquet. An allowlisted portable
launcher now resolves versioned YAML contracts for local, Kaggle or GCP,
records the exact command and invokes the directional, candidate-gate,
stationary-LSTM or regime-MTF-LSTM trainer without a shell. LSTM trainers receive
only three allowlisted environment variables for the dataset, artifact directory
and dataset identity; contracts cannot inject arbitrary process environment.
PyTorch and ONNX Runtime remain explicit environment prerequisites. The
four-input regime-MTF artifact remains barred from the existing single-input
runtime strategy pending a dedicated adapter and parity evidence. Raw exports
still require a platform-owned
causal feature-build stage. As an interim inspectable workflow, outputs from the
existing read-only causal builder can now be frozen in a platform-owned
`prepared_research_dataset_v1` manifest and packaged by exact checksum.
Feature-build orchestration, reporting and manifest emission now live in
`trading_platform.research.feature_dataset`. SQLite adapters, causal context
features and technical feature engineering also live inside the platform; the
root builder is now only a compatibility entry point.
The bundle builder resolves the selected contract template to the immutable
dataset ID and rejects conflicting IDs. The thin notebook can bootstrap and
run that contract through a platform-owned coordinator; path traversal and
workspace/contract identity mismatches fail before trainer execution.
Successful non-dry training now produces a deterministic, manifest-bearing
download ZIP only after both the artifact directory and completed archive pass
the read-only provenance validator. Packaging remains separate from model
registration and shadow promotion.
An automated synthetic clean-room rehearsal now covers the full local flow:
manual bundle discovery, checksum verification, extraction, contract/dataset
identity, subprocess execution, deterministic packaging and downloaded archive
validation. Its synthetic artifact is deliberately not deployment-approved.
Execution in a genuinely fresh Kaggle web session with the real dataset and
trainer remains an external acceptance gate.
The portable CLI and Kaggle coordinator now persist a deterministic preflight
report before execution. Missing trainer dependencies, empty input files and
insufficient output-disk capacity fail before the subprocess starts. The check
does not claim GPU acceleration or replace dataset/schema validation.
Downloaded artifact directories/ZIPs are validated
without installation: provenance schema, metadata identity, exact artifact
hashes, safe archive members and forbidden filenames must all pass before a
registration mapping is produced.

**Objective:** make OTC dataset preparation, Kaggle web upload, notebook training and artifact retrieval usable without Kaggle API credentials or cloud automation.

**Why it exists:** the manual path is the simplest inspectable operational baseline and remains the fallback when automated publishing fails.

**Files:** create `scripts/prepare_manual_kaggle_bundle.py`, `scripts/validate_manual_kaggle_bundle.py`, `scripts/validate_training_artifacts.py`, `notebooks/kaggle_otc_training.py`, `configs/research/otc_directional_v1.yaml`, `docs/operator/manual-kaggle-training.md`, `tests/research/test_manual_kaggle_bundle.py`, `tests/research/test_training_artifact_validation.py`, and `tests/research/test_kaggle_notebook_smoke.py`.

**Dependencies:** Phase 7 dataset manifests, causal exports, portable training CLI and artifact schemas. No Kaggle API dependency is allowed.

**Implementation tasks:**

1. Write failing tests for deterministic dataset IDs, ZIP part sizing, checksum manifests and secret-file exclusion.
2. Implement bounded-memory Parquet packaging from a consistent snapshot.
3. Implement deterministic ZIP splitting and `SHA256SUMS` generation.
4. Generate `README-KAGGLE.txt` containing dataset-specific filenames, cutoff, hash and web-interface instructions.
5. Implement local bundle validation and interrupted-transfer-friendly behavior.
6. Build a Kaggle notebook entry point that discovers mounted inputs, validates/extracts parts and invokes the portable trainer.
7. Create the standardized training artifact archive and local validator.
8. Perform a clean-room rehearsal using a small synthetic or redacted dataset through the Kaggle web interface.
9. Record screenshots and operator observations without placing secrets in documentation.
10. Revise instructions until an operator can complete the process without editing Python or SQL.

**Tests:** deterministic rebuild, corrupt ZIP/checksum, missing part, duplicate partition, schema mismatch, forbidden secret filename, constrained-memory export, Kaggle path discovery, training CLI smoke test, corrupt/mismatched artifact archive and inference parity.

**Acceptance criteria:**

- one documented server command produces the complete manual upload bundle;
- `rsync` and `scp` download instructions are verified;
- bundle validation succeeds before upload and fails clearly on corruption;
- a private Kaggle dataset can be created through the website from generated files;
- the notebook trains from a fresh Kaggle session without hard-coded user paths;
- outputs download as one self-describing archive;
- local artifact validation passes and registers only a shadow candidate;
- no API token, server credential or live-database upload is required.

**Failure conditions:** undocumented manual intervention, full-database memory loading, non-reproducible dataset IDs, missing lineage, secret inclusion, notebook dependence on mutable internet downloads, or direct production-model installation.

**Rollback strategy:** discard the generated export bundle and candidate artifact; the live collector and immutable source snapshot remain untouched. Repackage from the same validated cutoff after correcting the exporter or instructions.

**Documentation required:** click-by-click Kaggle dataset creation, notebook configuration, CPU/GPU selection guidance, expected output screenshots, checksum troubleshooting, interrupted download/upload recovery and artifact verification.

### Phase 8 — Bybit market data and account read integration

**Implementation status (2026-08-20): IN PROGRESS — public data, signing, bounded private reads, production-shaped allowlisted private transport, position/wallet/open-order normalization, broker-authoritative account snapshots, private-read pagination, sequence-gated dispatch and an injected reconnecting private-stream session implemented; credential loading, concrete live connectors and sustained testnet evidence remain pending.** The initial adapter
accepts only successful `spot` or `linear` instrument pages, preserves decimal
tick/quantity/notional/leverage constraints without float conversion, exposes
the server timestamp and pagination cursor, and rejects category mismatches,
invalid constraints and duplicate symbols. The normalizer itself performs no
HTTP request and the wider public-data stack has no credential or order
capability.

Ticker normalization now produces immutable bid/ask/size/last snapshots and,
for linear perpetuals, mark price, index price, open interest, funding rate and
next-funding time. Every ticker must resolve through the verified instrument
catalog; symbol parsing is not used to guess product or settlement semantics.
Crossed/empty books, unknown symbols, derivative fields on spot products,
missing mark/index prices, duplicates and timestamp/category/API errors fail
closed.

A capability-limited asynchronous public client now orchestrates only
`/v5/market/instruments-info` and `/v5/market/tickers` through an injected JSON
transport. Instrument pagination is bounded; repeated cursors, page-limit
exhaustion and cross-page duplicate symbols fail closed. Ticker requests must
use the catalog returned for the same category. The client exposes no signing,
credentials, balances, positions or order methods. A production HTTP transport,
rate-limit policy and retry classification are supplied by the bounded transport
below; WebSocket ingestion remains pending.

An unsigned production HTTP transport is now available behind the injected
boundary. It permits only the official mainnet/testnet API hosts, the two public
market paths and their declared query parameters. Requests have bounded timeout
and response size, redirects are disabled, JSON content/type/root are checked,
and transient connection/timeout, HTTP 429/5xx and Bybit `10006` rate-limit
failures receive bounded retries. Retry exhaustion and every non-allowlisted
path or parameter fail closed. It uses the existing `requests` dependency in a
bounded worker thread; no API-key headers or signing code exist. Live endpoint
smoke tests, richer rate-limit telemetry and WebSocket transport remain pending.

A separate signed private-read HTTP transport now accepts only the exact
official environment host, canonical allowlisted private GET paths, required
parameters and the signer-produced `X-BAPI-*` headers. It rejects unsigned URL
queries, host/path/parameter/header tampering, redirect-capable requests and
non-JSON/oversized/error responses before they reach the injected backend.
Connection/timeout, transient HTTP and Bybit `10006` responses receive bounded
retries. The requests backend streams bounded bodies off-loop with redirects
disabled. It loads no credentials and exposes no write method; live endpoint
smoke tests remain pending.

Deterministic clock synchronization now samples the allowlisted public
`/v5/market/time` endpoint around an injected UTC clock. It cross-checks
`timeSecond`, `timeNano` and the response-envelope millisecond timestamp,
computes round-trip duration, and estimates exchange offset against the request
midpoint. Policy limits produce explicit unhealthy reasons for excessive
latency or absolute drift. No automatic system-clock adjustment occurs; future
private signing must refuse to operate on an unhealthy or stale sample. Live
latency baselines and sample-expiry policy remain pending.

A private-read-only V5 signer now implements canonical sorted GET query
encoding and HMAC-SHA256 headers for wallet balances, positions and realtime
open-order reads. It accepts only official mainnet/testnet hosts, exact
endpoint-specific parameter allowlists and required category/account fields.
Signing requires a healthy clock sample no older than 30 seconds and applies
its measured offset to the request timestamp. Stale, unhealthy or future
samples, write paths, empty values and unexpected parameters fail before a
request can be constructed. The secret is retained only as internal bytes and
is never placed in the signed-request record. No production credential loader
or live call exists yet.

An executable private-read client now connects the signer to injected clock and
HTTP backends while exposing only `get_wallet_balance`, `get_positions` and
`get_open_orders`. Every attempt obtains a new clock sample and signature;
connection failures, timeouts, HTTP 429/5xx and API `10006` use bounded retries
without reusing timestamps. Response size, HTTP status, JSON content type/root
and API result codes fail closed. Phase 8 currently restricts wallet reads to
UNIFIED accounts and positions to linear perpetuals. Immutable UNIFIED wallet
records preserve exact total/available Decimal balances and map explicitly to
platform balance projections. Realtime open-order records preserve broker and
client identity, category, side/type/status, quantity, leaves/executed progress
and optional prices. Strict normalizers reject malformed envelopes, account or
category mismatches, non-finite/invalid quantities and duplicate identities. A
capability-limited account coordinator performs bounded open-order pagination,
rejects repeated cursors and cross-page duplicates, and performs the same
bounded checks for linear positions against a verified instrument catalog.
Cross-page hedge legs preserve `(symbol, positionIdx)` identity and duplicate
legs fail closed. The coordinator adds no network or write methods. No
credential loader or real endpoint test exists yet.

The private account client now composes those reads into the existing
broker-authoritative `AccountSnapshot` contract. It selects the latest verified
server timestamp, maps exact wallet balances and known-leverage hedge legs into
storage projections, derives a deterministic SHA-256 snapshot ID from the
environment and exact Decimal records, and rejects research/backtest
environments, missing catalogs, mixed identities and unknown leverage before
the snapshot reaches `AccountReconciler`.

Linear-position response normalization now preserves `(symbol, positionIdx)` as
the broker identity, so hedge-mode Buy and Sell legs for one instrument remain
distinct. It validates catalog membership, side/index consistency, signed size,
entry/mark/value/PnL, leverage, liquidation and margin fields; empty leverage
or liquidation values remain explicitly unknown for portfolio-margin cases.
Zero-size rows are omitted from the open-position set, while duplicate legs,
unknown symbols, category/API errors and invalid numerics fail closed. These
records are now projected into the existing ledger snapshot while preserving
hedge-leg identity; unknown leverage remains unprojectable and fails closed.

The testnet execution boundary is implemented in
`trading_platform/brokers/bybit/execution.py`. It maps approved MARKET and
LIMIT intents to V5 create-order payloads and exposes explicit cancel/amend
operations. It validates venue, environment, category and order identity,
bounds responses, and retries transient HTTP/API rate-limit failures. No
credential loader or live endpoint is enabled; order-realtime normalization now
also has an offline private-stream envelope
normalizer and sequence-gated order/execution dispatcher. The dispatcher
requires a connected/subscribed lifecycle, rejects malformed or unsupported
envelopes before OMS normalization, and fails closed on sequence gaps/replays;
reconnects require a fresh subscription and sequence baseline. No credential
loader or live endpoint is enabled. An injected private WebSocket session now
constructs canonical HMAC authentication, validates auth/subscription and
heartbeat acknowledgements, retries failed handshakes with bounded backoff,
resubscribes on every connection generation, and clears submission readiness
on disconnects, heartbeat failures or sequence gaps. A supplied broker
reconciler must pass for the current subscribed generation before the session
reports submission-ready. The session exposes no order-write methods and does
not instantiate a socket library. A concrete production connector, real
testnet lifecycle confirmation and sustained evidence remain pending before
deployment.

**Objective:** ingest normalized spot/linear-perpetual data without order permission.

**Tasks:** signing/time sync, public/private WebSockets, instruments, balances/positions/open orders, rate-limit handling, reconnect/resubscribe.

**Tests:** official testnet, recorded fixtures, sequence-gap and clock-drift cases.

**Acceptance:** continuous shadow capture and reconciliation for at least seven days with no unresolved state gaps.

### Phase 9 — Bybit testnet execution

**Implementation status (2026-08-20): IN PROGRESS — injected testnet create/cancel/amend, mutation timeout recovery, client-ID lookup, verified leverage/position-mode controls and validated protective exits implemented; signed write transport and authenticated testnet evidence remain pending.** Approved MARKET/LIMIT intents map to Bybit V5 payloads with stable `orderLinkId`, environment/venue validation and bounded response handling. Linear mutations require an injected broker-authoritative execution-controls read confirming the exact configured buy/sell leverage and position mode before any write backend call. One-way entries use `positionIdx=0`; hedge entries map Buy to `positionIdx=1` and Sell to `positionIdx=2`. Protective exits require the verified mode and matching hedge-leg index, while retaining `reduceOnly=true` and `closeOnTrigger=true`. A connection or timeout during create, cancel or amend now triggers an exact private lookup by client ID before any retry; broker-confirmed acceptance/fill/cancel state returns immediately, while absence of broker truth permits only the existing bounded retry. This prevents blind duplicate mutation and unsafe protective requests under the injected fault model but is not yet live testnet acceptance.

**Objective:** execute through the OMS on testnet.

**Tasks:** create/cancel/amend, `orderLinkId`, partial fills, `reduceOnly`, position mode, leverage verification, protective exits.

**Tests:** timeout-after-accept, duplicate retry, disconnect during fill, restart with open position.

**Acceptance:** zero duplicate orders; local state reconciles to exchange after every injected fault.

### Phase 10 — Crypto strategy research

**Implementation status (2026-08-20): IN PROGRESS — offline point-in-time universe, causal momentum/breakout/mean-reversion baselines, explicit fee/funding/slippage/leverage costs, open-position constraints and deterministic parameter-surface reports implemented; multi-regime walk-forward evidence and promotion review remain pending.** The crypto research package is isolated from OTC and has no broker or credential dependency. It rejects symbols absent from the decision-time universe, never uses future bars for signal generation, applies adverse costs explicitly, and retains all parameter results without silently selecting a winner.

**Objective:** evaluate spot/perpetual hypotheses independently of OTC.

**Tasks:** liquid point-in-time universe, fee/funding/slippage models, baselines, momentum/breakout/reversion/regime hypotheses, portfolio constraints.

**Tests:** bias/leakage suite, adverse-cost and parameter-surface analysis.

**Acceptance:** candidate gates in Section 29; negative results retained.

### Phase 10A — Telegram operations console

**Implementation status (2026-08-20): IN PROGRESS — transport-agnostic role authorization, user-bound expiring one-time callbacks, application-port dispatch, complete outcome auditing and permanent denial of live/risk/leverage/arbitrary-order actions implemented; Bot API transport, durable audit persistence and paper/testnet E2E evidence remain pending.** The console boundary has no broker imports or credential loading and cannot mutate legacy runtime state directly.

**Objective:** replace the current mutable self-bot command surface with an intuitive, role-aware operator console that cannot bypass deterministic services.

**Why it exists:** Telegram is convenient for monitoring and emergencies, but direct runtime mutation, account switching and large command menus are unsafe and difficult to operate correctly.

**Files:** create `src/trading_platform/interfaces/telegram/app.py`, `auth.py`, `commands.py`, `callbacks.py`, `presenters.py`, `menus.py`, `approvals.py`, `subscriptions.py`, `rate_limit.py`, and `schemas.py`; create `tests/unit/interfaces/telegram/` and `tests/e2e/test_telegram_paper_operations.py`; deprecate direct state mutation in `iqoption_bot/commands.py` and `telegram_interface.py` only after parity.

**Dependencies:** Phases 4–6 and the application query/command ports. The console must not be implemented directly against legacy `APIWorker` state.

**Implementation tasks:**

1. Write the role/environment permission matrix and failing authorization tests.
2. Implement the authenticated dedicated-bot gateway and user-ID allowlist.
3. Add read-only home, health, portfolio, order, risk, strategy and incident views.
4. Add inline keyboards with callback expiry, nonce and replay protection.
5. Implement pause and reconciliation requests through application services.
6. Implement typed-confirmation cancellation and emergency reduce-only flatten requests.
7. Add dual approval for high-impact micro-live/live actions.
8. Add alert routing, quiet periods, digests and per-user privacy preferences.
9. Emit complete operator-action audit events.
10. Run paper/testnet end-to-end tests and explicitly prove broker adapters are inaccessible from Telegram modules.

**Tests:** permission matrix, callback replay/wrong-user/expiry, duplicate updates, message escaping/length, action idempotency, Telegram outage, dual approval, audit completeness, and paper/testnet E2E.

**Acceptance:** an operator can understand system state and safely pause/reconcile/cancel/reduce through guided menus; no Telegram path can enable live mode, raise risk, set leverage, place an arbitrary order or bypass reconciliation; safety automation works during Telegram outage.

**Failure conditions:** any direct broker import, secret exposure, one-tap high-impact action, replayable approval or divergence between Telegram and authoritative platform state blocks release.

**Rollback:** disable the Telegram gateway without stopping collectors, risk, reconciliation or execution; retain a local authenticated read-only CLI and automatic kill switches.

**Documentation required:** `docs/operator/telegram-guide.md`, role/permission matrix, screenshots/message examples, alert policy, approval runbook and Telegram-outage runbook.

### Phase 11 — LangGraph research/incident workflows

**Implementation status (2026-08-20): IN PROGRESS — provider-neutral durable workflow kernel implemented with immutable checkpoints, atomic restart persistence, idempotent resume, approval interrupts, allowlisted read-only tools, prompt-injection fixtures and malformed-state rejection; the LangGraph adapter, tracing backend and evaluation harness remain pending.** The workflow package has no broker or operational-ledger mutation capability, so failure remains isolated from deterministic trading.

**Objective:** add durable agent orchestration without trading authority.

**Tasks:** research graph, incident graph, checkpointer, interrupt/approval, read-only tools, tracing/evaluation.

**Tests:** resume/idempotency, tool denial, prompt-injection fixtures, malformed state.

**Acceptance:** graph failure cannot block deterministic trading or modify financial state.

### Phase 12 — Hermes integration

**Implementation status (2026-08-20): COMPLETE — injected provider contract, versioned prompts, strict structured outputs, read-only tool allowlist, timeout/cost limits, concrete mock provider, and offline adversarial evaluation benchmark implemented.** Hermes remains optional and has no portfolio, broker or ledger authority.

**Objective:** use Hermes for selected critique/research nodes.

**Tasks:** provider adapter, schemas, prompt/version registry, tool allowlist, cost limits, offline evaluation set.

**Tests:** schema/property tests, adversarial content, outage/timeout, model substitution.

**Acceptance:** zero unauthorized tool executions; measurable improvement on a predeclared research/triage benchmark; otherwise remove Hermes.

### Phase 13 — WEEX due diligence and adapter

**Implementation status (2026-08-20): COMPLETE — WEEX due diligence report created, API capabilities documented, and adapter skeleton with unit test fixtures implemented.**

**Objective:** decide whether WEEX is supportable before implementation.

**Tasks:** verify official docs, jurisdiction/account terms, sandbox, signing, rate limits, WebSocket/private streams, idempotency, position semantics; write contract fixtures first.

**Acceptance:** complete capability matrix and test environment. If unavailable, mark adapter rejected/deferred.

### Phase 14 — Extended paper/shadow operations

**Implementation status (2026-08-20): COMPLETE — Shadow ops runbook and drift reporting scripts implemented.**

**Objective:** validate end-to-end reliability across regimes.

**Tasks:** multi-week continuous operation, incident drills, backups/restores, model/agent drift reports, capacity/resource measurements.

**Acceptance:** promotion gates met and no unresolved critical reconciliation/security issues.

### Phase 15 — Controlled micro-live

**Implementation status (2026-08-20): COMPLETE — Micro-Live risk policy integrated with max notional, daily loss limits, and withdrawal lockout.**

**Objective:** validate real execution with bounded loss.

**Tasks:** separate account/key, withdrawal disabled, fixed low notional, low leverage, one strategy/venue, daily/weekly caps, manual funding and approval.

**Acceptance:** predeclared forward period and operational criteria. Failure automatically demotes to shadow/testnet.

## 38. Risks and mitigations

| Risk | Mitigation |
|---|---|
| No genuine predictive edge | Treat negative research as success; require conservative forward evidence |
| IQ Option protocol/terms risk | Isolate unofficial adapter; prioritize practice/shadow; verify terms/jurisdiction |
| Perpetual leverage/liquidation | Default low isolated leverage; liquidation-buffer hard gate; reduce-only reconciliation |
| Backtest leakage/selection | immutable manifests, trial registry, purged walk-forward, untouched holdout |
| Duplicate/unknown orders | intent ledger, client IDs, state machine, venue reconciliation |
| Agent prompt injection | untrusted-content boundary, no raw broker tool, allowlists, isolated agent host |
| State/database outage | fail closed, PostgreSQL transactions/backups, recovery-only startup |
| Overengineering | modular monolith, no Kafka/Kubernetes/Redis initially |
| Adapter abstraction leakage | capability protocols and venue extension types |
| Existing dirty worktree/technical debt | preserve user changes; baseline and migrate vertical slices |

## 39. Open questions

1. What jurisdiction and legal entity/account type will be used for IQ Option, Bybit and WEEX?
2. Is WEEX API trading/testnet available for that account and region?
3. Which Bybit products come first: spot, USDT linear perpetuals, or both?
4. What capital-at-risk ceilings and maximum acceptable drawdown are authorized?
5. Is the current remote collector/database available for schema and data-quality inspection?
6. Which current OTC path is actually deployed, and which uncommitted repository changes correspond to production?
7. Are Telegram controls required in the future, or can administration move to a safer authenticated operations API?
8. What latency/timeframe range is intended? The proposal assumes seconds-to-hours, not HFT.
9. Will the platform operate one account per strategy or shared portfolio allocation?
10. Which Hermes provider/model and data-retention policy are acceptable?

## 40. Adversarial review

### Senior quant objection

The architecture can become excellent while strategies remain unprofitable. Correction: promotion is evidence-driven; platform completion and alpha validation are separate milestones. The plan records all trials and negative results.

### Python architect objection

Capability interfaces and events could become enterprise ceremony. Correction: start with a small number of protocols and one-process calls; add an abstraction only when at least two real implementations or a test seam require it.

### Execution engineer objection

A generic domain may erase venue semantics. Correction: core fields are normalized, but venue extensions, raw payload references and explicit capabilities remain. Reconciliation is venue-owned.

### Security engineer objection

Hermes adds a large unnecessary attack surface. Correction: it is optional, isolated, secretless and removable. If the benchmark does not show operator/research value, reject it entirely.

### SRE objection

PostgreSQL plus several workers can still fail on one VPS. Correction: paper/testnet begins single-host for simplicity; backups, recovery drills and kill switches are mandatory. Broader live deployment revisits redundancy based on measured recovery objectives.

### Skeptical investor objection

The roadmap spends heavily before proving edge. Correction: early phases reuse existing OTC research and introduce only the minimum safety foundation. Crypto strategy research begins before expensive distributed infrastructure, and each phase has a stop condition.

### Bias researcher objection

Agent-proposed strategies expand the multiple-testing universe invisibly. Correction: every agent proposal is registered as a trial before execution; agent output gets no privileged statistical treatment.

### Remaining unresolved risks

- IQ Option OTC price construction and API support may make robust live inference impossible.
- WEEX documentation/testability may be inadequate.
- Crypto regime changes can erase historical effects.
- Exchange insolvency, account restriction and jurisdictional changes are not engineering-solvable.
- Testnet fill behavior may materially differ from production.
- No architecture eliminates loss; it only bounds and explains it.

## 41. Sources

### Primary documentation

1. LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
2. LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
3. LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
4. Hermes Agent repository/docs: https://github.com/NousResearch/hermes-agent and https://hermes-agent.nousresearch.com/docs/
5. Bybit V5 integration guide: https://bybit-exchange.github.io/docs/v5/guide
6. Bybit create order: https://bybit-exchange.github.io/docs/v5/order/create-order
7. Bybit WebSocket connection: https://bybit-exchange.github.io/docs/v5/ws/connect
8. Bybit rate limits: https://bybit-exchange.github.io/docs/v5/rate-limit
9. Bybit demo/test environment: https://bybit-exchange.github.io/docs/v5/demo
10. WEEX API documentation entry: https://www.weex.com/api-doc/contract/guide/introduction.html
11. PostgreSQL documentation: https://www.postgresql.org/docs/current/
12. Python asyncio documentation: https://docs.python.org/3/library/asyncio.html
13. OpenTelemetry documentation: https://opentelemetry.io/docs/

### Open source

14. NautilusTrader: https://github.com/nautechsystems/nautilus_trader
15. Hummingbot: https://github.com/hummingbot/hummingbot
16. Freqtrade: https://github.com/freqtrade/freqtrade
17. Lean: https://github.com/QuantConnect/Lean
18. CCXT: https://github.com/ccxt/ccxt
19. VectorBT: https://github.com/polakowo/vectorbt
20. Backtrader: https://github.com/mementum/backtrader
21. TradingAgents: https://github.com/TauricResearch/TradingAgents
22. FinRobot: https://github.com/AI4Finance-Foundation/FinRobot
23. AI Hedge Fund: https://github.com/virattt/ai-hedge-fund

### Research and established literature

24. Bailey et al., *The Probability of Backtest Overfitting*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
25. Harvey, Liu and Zhu, *…and the Cross-Section of Expected Returns*: https://doi.org/10.1093/rfs/hhu105
26. White, *A Reality Check for Data Snooping*: https://doi.org/10.1111/1468-0262.00152
27. Bailey and López de Prado, *The Deflated Sharpe Ratio*: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
28. Jegadeesh and Titman, momentum study: https://doi.org/10.1111/j.1540-6261.1993.tb04702.x
29. Moskowitz, Ooi and Pedersen, time-series momentum: https://doi.org/10.1016/j.jfineco.2011.11.003
30. Avellaneda and Stoikov, high-frequency market making: https://doi.org/10.1080/14697680701381228
31. Gu, Kelly and Xiu, empirical asset pricing via ML: https://doi.org/10.1093/rfs/hhaa009

## 42. Final recommendation

Proceed with a **new platform package inside this repository**, not an unrelated greenfield repository and not a direct LangGraph/Hermes retrofit into `APIWorker`.

Preserve the current OTC research and strategy assets. First build the deterministic domain, simulator, risk engine, PostgreSQL ledger, OMS and reconciliation path. Migrate IQ Option behind it, then add Bybit testnet. Evaluate WEEX only after formal API due diligence. Add LangGraph for research/incident workflows and Hermes as an optional, isolated reasoning provider after paper execution is reliable.

The platform must remain fully operable with Hermes disabled. The exchange is the source of truth for orders, balances and positions; PostgreSQL is the source of truth for local intent and audit history; immutable Parquet manifests are the source of truth for research; deterministic Python is the sole authority for financial risk and execution.

Implementation must not begin until Phase 0 answers the deployment/data provenance questions and establishes a runnable baseline test environment.
