# Crypto capital-allocation plan

Date: 2026-10-30. Status: revised proposal, awaiting approval to implement.
Residence: **Nigeria**, confirmed by Saviour. Capital and loss budgets: configurable, deliberately unset.

## 1. Decision in one page

**Do not approve a carry bot on the existing return table. Approve a bounded research stage only if its cost is justified.** The table reproduces, but measures annualized funding less simplified fees per hedged notional. It does not establish investable returns on total capital. There is no verified live edge yet.

The ambitious outcome is a capital-allocation process that earns the right to trade: compare eligible cash, perpetual funding carry, dated-futures basis and simple trend on the same accounting basis; deploy only a passing candidate; return to cash when no candidate qualifies. Building an elaborate trading stack is not itself success.

What changes from the original:

- A stablecoin-margined short at 1x plus separately funded spot requires approximately twice the hedged notional, before reserves. Report returns on that full allocation, including idle buffers and operating costs.
- Nigeria determines the venue investigation. No venue is approved here. Public API access, an offshore VPS and absence from a restricted-country list do not establish product eligibility.
- Cash is the default allocation. Exchange Earn, stablecoin lending, synthetic dollars and vaults are separate credit/market exposures, not a risk-free idle sleeve.
- Previously inspected 2025–2026 data are development data. They cannot become an untouched holdout by changing the label.
- Keep the ledger, order manager, reconciliation and simulator. CCXT is an exchange adapter, not a replacement for those controls.
- Stop-losses, watchdogs and delta limits are response policies, not guaranteed loss caps. Venue failure can lose the entire balance and can make flattening impossible.
- Start with BTC and ETH. No automatic top-N rotation, cross-venue hedges, altcoin expansion or autonomous LLM order placement in the initial implementation.

**Current allocation recommendation: no live allocation under this proposal.** This is an evidence decision, not a prediction that all crypto strategies lose. The completed research and reproducible diagnostic are in [the review directory](../research/crypto-review-2026-10-30/README.md).

## 2. What the evidence establishes

### Local evidence

The audit reproduces the original funding report from the available raw JSON. Retain the numbers as historical screening evidence, not a portfolio backtest. See [carry audit](../research/crypto-review-2026-10-30/carry_audit.md) for exact inputs, hashes, dates, calculations and reproduction commands.

Missing from the old calculation: executable spot and perp prices, mark-to-market basis, changing exposure, rebalances, realistic spread/slippage, capital transfers, liquidation, ADL, unavailable trading, terminal close costs and a complete account ledger. The implemented funding gate also differs from the proposed expected-funding-versus-cost gate. A positive funding curve cannot demonstrate a 3% portfolio drawdown ceiling.

The report's 2026 columns are annualized partial-period observations. Annualization does not turn a short or incomplete sample into a full-year realized return. Do not extrapolate Hyperliquid's historical premium into a persistent “twice the yield” assumption.

### Published evidence and its limits

- [BIS, Crypto carry](https://www.bis.org/publ/work1087.htm): carry reflects market segmentation and limits to arbitrage; high carry is associated with crash risk. It supports investigating the mechanism, not treating it as a deposit substitute.
- [Borri et al., version 4, section 3.6](https://arxiv.org/html/2510.14435v4): their Binance BTC sample ends May 31, 2025 and carry Sharpe turns negative in its 2025 segment. This is not evidence about every venue or all of 2026. Discussion of synthetic-dollar growth does not establish that Ethena or ETFs caused the decline.
- Trend-following literature motivates a candidate, not the claim that it is the only directional family with an edge. Paper backtests do not validate our universe, fees, funding, implementation or future performance. Exact paper and replication limitations are recorded in the carry audit.
- [Chitra, ADL study, version 3](https://arxiv.org/abs/2512.01112): the October 2025 episode demonstrates involuntary position closure and loss allocation. The abstract and empirical introduction label the headline total differently; this plan does not use it as an ADL-specific estimate. A short removed by ADL leaves spot exposure even if the short was profitable.

The draft's Alpha Arena percentages are not needed to justify the design. Remove them as a control premise: a short contest cannot establish all LLM trading performance. Agents are restricted because privileged, nondeterministic decisions are hard to reproduce and constrain. Unverified YouTube titles, HLP returns and anecdotal latency are not evidence of an investable edge.

## 3. Nigeria: venue eligibility before yield ranking

The [Nigerian SEC operator register](https://www.sec.gov.ng/fintech-and-innovation-hub-finport/registered-fintech-operators/) identifies Busha and Quidax within its programme categories. That is not blanket permission for every product, and does not establish API-accessible perpetuals. The [SEC circular index](https://www.sec.gov.ng/for-investors/keep-track-of-circulars/) includes its July 28, 2023 Binance warning. An old warning is not a complete statement of today's legal position, but it prevents us from silently assuming authorization. See the [venue source ledger](../research/crypto-review-2026-10-30/venue_research.md).

For each candidate, record and approve this eligibility dossier before any deposit:

| Required evidence | Pass condition |
|---|---|
| Contracting entity, legal residence, KYC and exact product | Current terms and account confirmation allow this resident and product; unresolved regulatory conflict escalated to qualified local advice |
| SEC status and product scope | Current regulator evidence recorded; spot approval never substituted for derivatives approval |
| Funding and withdrawals | Named bank/off-ramp, currency, fees, settlement time, account-name requirements and withdrawal restrictions documented; no assumed P2P route |
| Trading support | Actual account permissions, fee tier, minimum sizes, API scope, margin mode, funding cadence, ADL/liquidation rules captured |
| Custody and collateral | All entities, stablecoins, bridges, custodians and shared dependencies mapped |
| Exit and records | Legal redemption/withdrawal route, tax/export records and recovery contact documented |

Research candidates, not approved venues:

- **Bybit global:** candidate only after entity/product verification for Nigeria. Account eligibility and stablecoin collateral treatment require authenticated confirmation.
- **Binance:** blocked for allocation pending explicit resolution of the Nigerian regulatory and account/product position. A working API is insufficient.
- **Hyperliquid:** absence of conventional KYC does not establish permission. Include terms, bridge/token identity, wallet/API permissions, validator intervention, ADL, oracle and withdrawal risks. Do not assume CEX key restrictions map to wallet signers.
- **Locally listed operators:** investigate spot/off-ramp capability separately. Do not assume derivatives or suitable APIs exist.
- **Regulated broker/dated futures:** investigate only if the broker accepts Nigerian residents and account size, margin and costs make it practical.

The original universal EU ban and Binance July 2026 exit claims are removed. ESMA's CFD classification rules and OKX's five-year X-Perps require product-level analysis, not a label-based prohibition. They are not the immediate selection criterion for this Nigerian-resident plan.

## 4. Configurable does not mean unrestricted

Use one versioned, validated configuration with research, paper and live modes. Examples below describe a future contract; they are not an implemented risk system.

| Setting | Required meaning and validation |
|---|---|
| `capital_budget_usd` | Positive, explicitly approved amount assigned to the programme; never infer it from wallet balance |
| `base_currency`, `benchmark_id` | USD reporting plus NGN reconciliation; eligible benchmark, yield timestamp, fees, taxes and redemption horizon recorded |
| `max_loss_usd`, `max_drawdown_pct` | Both explicitly set; stricter derived threshold applies. Mark-to-market total equity, including fees and impaired assets |
| `venue_loss_budget_usd` | Maximum balance at risk from total venue failure, including spot, collateral, pending transfers and Earn balances |
| `stablecoin_loss_budget_usd` | Shared issuer exposure aggregated across venues; not independent merely because accounts differ |
| `risk_premium_bps`, `minimum_profit_usd_year` | Required excess over accessible benchmark and minimum absolute benefit after operations costs |
| `max_leg_notional_usd`, `max_unhedged_usd`, `max_unhedged_seconds` | Exposure and legging controls derived from the approved loss/stress budget |
| `margin_mode`, `max_leverage`, `collateral_reserve_usd` | Exact venue model and stress assumptions; no generic liquidation-distance formula |
| `data_stale_seconds`, `order_timeout_seconds`, `slippage_limit_bps` | Venue-measured limits, with tested stale-data and ambiguous-order handling |
| `venue_allowlist`, `instrument_allowlist`, `config_hash` | Explicit eligibility and product versions; BTC/ETH initial universe |
| `live_enabled` | Defaults false; invalid/missing eligibility, budget or risk settings prevent enabling |

Raising capital, widening a loss limit, adding a venue/instrument, changing margin treatment or un-killing requires fresh approval. Reductions may occur automatically under the approved safety policy. Configuration cannot disable ledger reconciliation, idempotency, schema validation or audit logging. A stricter new limit below existing exposure triggers controlled reduction rather than rejection that leaves exposure unmanaged.

Per-venue concentration is a limit on total programme equity, not a loophole that becomes 100% when one venue is chosen. One venue can hold a small sleeve while the rest remains outside it. With a 100% venue-loss stress assumption, balance at that venue must not exceed its approved venue loss budget. Across correlated venues, stablecoins and bridges, aggregate stressed losses must also fit the programme budget. These are exposure constraints, not promises of recoverability.

## 5. Economics: make cash a hard competitor

Define capital `C` as spot purchase `S` plus short margin `M` plus operational reserve `R`, with no double counting of cross-margin collateral. For separately funded stablecoin collateral and a 1x short of notional `N`, `S ≈ N`, `M ≈ N`, so `C ≈ 2N + R`. Unified margin can change this, but introduces collateral haircuts, borrow/interest and wrong-way risk that must be modelled explicitly.

Total P&L includes spot and derivative price P&L, funding actually settled, fees, spread, slippage, borrowing, conversions, transfers and external operating costs. Basis movement is an attribution of the combined spot/derivative price P&L, not a second additive profit or loss. Likewise, costs already embedded in actual fill prices must not be deducted again as modeled slippage. External deposits and withdrawals are flows, not trading profit. Report time-weighted portfolio return, investor cash flows, net dollar profit, drawdown, capital usage and benchmark-relative return. Report NGN translation separately; a higher NGN nominal yield is not directly comparable to a USD strategy without FX exposure and conversion costs.

For a simplified static screen only:

```text
net_strategy_rate = notional_net_rate * (N / C) + eligible_idle_yield - annual_operating_cost / C
excess_dollars = C * (net_strategy_rate - accessible_benchmark_rate)
break_even_capital = annual_operating_cost / pre_fixed_cost_excess_rate
```

Idle yield is weighted by the actual eligible idle balance. Margin and buffers do not earn an assumed yield. If pre-fixed-cost excess is nonpositive, no amount of capital fixes it. If break-even capital exceeds the user's budget or venue risk budget, reject the strategy. Do not increase leverage to manufacture a pass.

No current benchmark yield is inserted: the investable instrument, account access, currency, taxes and withdrawal horizon remain unset. The historical funding audit includes denominator illustrations, not a recommended allocation.

| Candidate | Why test it | Failure condition / current disposition |
|---|---|---|
| External eligible cash or short-duration benchmark | Minimum-complexity opportunity cost and reserve location | Select actual accessible product; do not label any stablecoin balance risk-free |
| Gated BTC/ETH spot + perpetual short | Observable funding mechanism; existing screening data | No net excess after collateral/costs, insufficient margin stress coverage or no eligible venue: reject |
| BTC/ETH spot + dated futures short | Entry basis and maturity are observable; no dependence on forecasting perpetual funding for the locked period | Settlement/index mismatch, variation-margin liquidity, contract size, early exit and broker costs can erase the advantage |
| Unlevered spot trend | Tests directional diversification without initial perpetual funding/liquidation complexity | Must justify drawdown and excess over cash at matched risk; not a defensive yield substitute |
| Cross-venue funding, altcoin rotation, HLP, lending, synthetic dollars | Possible future research only | Excluded from initial deployment; each adds distinct basis, credit, liquidity or governance risk and needs its own approved experiment |

The dated-futures comparator follows the [CME description of cash-settled Micro Bitcoin contracts](https://www.cmegroup.com/education/articles-and-reports/how-to-trade-micro-bitcoin-futures) and [BIS carry mechanism](https://www.bis.org/publ/work1087.htm). Cash settlement does not guarantee an exact hedge against a spot fill at a different time or index. No current yield or Nigerian broker access is claimed.

## 6. Research design and promotion policy

First register a small tournament: cash baseline, gated BTC/ETH carry, dated-basis comparator if eligible, and one fixed unlevered daily trend ensemble. Compare approach variants blind where possible. Do not search every liquid perp until a winner appears.

Before running the portfolio experiment, freeze: data manifest and hash, universe as known at each time, inclusion/exclusion rules, signal timing, trial list, fees, cost model, benchmark, sizing, stress suite and rejection thresholds. Register every failed trial. Source publications and already viewed data belong to development. Revisions restart the forward evaluation for the revised strategy; they do not erase its failed predecessor.

Required data: funding settlement times and actual rates, spot/perp tradeable prices and bid/ask, mark/index, instrument metadata and contract multipliers, fee schedules, delistings, funding-interval changes and collateral rules. Record source, retrieval time, coverage, missing intervals and duplicates. Missing data means unavailable trading or explicit exclusion, never a silent zero funding payment. Where historical order books cannot be recovered, use conservative cost scenarios and label capacity unvalidated.

Use only information available before each order. A trailing gate includes completed settlements only; signals execute after the observation with latency. Predicted funding and settled funding are distinct fields. Funding income follows actual held quantity and settlement notional, not a fixed initial notional shortcut. Do not calculate drawdown from funding cashflows alone.

Proposed experiment policy, to freeze on research approval:

- Carry: require positive net excess after all costs, plus the configured risk premium and minimum annual dollar benefit. The original hurdle +2 percentage points can be a starting policy value, not an empirical fact or hidden default.
- Report daily paired excess returns versus the benchmark with a pre-specified block-bootstrap confidence interval, preserving serial dependence. Record block length, seed, sample length and all trials; adjust multiple comparisons or designate exactly one primary test. A confidence interval including zero means inconclusive, not promoted.
- Evaluate carry under normal, doubled execution-cost and adverse funding/basis scenarios. Require the approved drawdown and stress-loss budgets, including correlated venue/issuer losses, to hold under the specified scenarios. Do not claim historical scenarios bound future loss.
- Trend: compare to cash and a risk-matched BTC/ETH buy-and-hold baseline, with actual next-bar execution costs. Report uncertainty, turnover, drawdown, downside correlation and concentration of profits. A point Sharpe above 1 alone does not pass. If later implemented with perps, historical funding becomes mandatory.
- Rolling chronological evaluation is useful development evidence; no retroactive clean holdout. Use untouched future observations after the exact configuration is signed. Minimum 12 weeks forward observation is an operational floor, not proof of annual profitability; continue or reject when statistical evidence is insufficient.
- Reject dependence on one coin/month, unstable nearby parameters, missing stress data, or an unexplained accounting residual. “No candidate passes” is a successful research outcome.

A past eight-week period “within one sigma” and paper P&L “within ±20%” are removed. Those tests are ill-defined near zero profit and cannot establish execution or future returns. Instead compare identical event streams and inspect each accounting/execution residual.

## 7. Execution and service boundaries

Build only after economic research passes and the next phase is approved. Reuse the existing `trading_platform` ledger, domain models, order manager, reconciliation and simulator behind typed contracts. Move ownership gradually; do not create two competing order writers.

| Boundary | Responsibility |
|---|---|
| `contracts/` | Versioned instrument, funding, proposal, approval, risk decision, order intent, fill, position and account schemas; UTC timestamps, units and correlation IDs |
| `services/market-data/` | Validated collection and immutable manifests; gaps/staleness visible |
| `services/research/` | Portfolio replay, trial registry, stress/eval reports; cannot submit live orders |
| `services/carry-engine/` | Deterministic candidate and target-position proposals; no exchange secrets |
| `services/executor/` | Single writer per account, durable intents/outbox, adapter calls, idempotency and recovery |
| `services/risk/` | Versioned synchronous checks and persisted halt state; unavailable risk service denies new risk, but pre-authorized safe reductions remain possible |
| `services/operator-bot/` | Authenticated approvals and alerts; cannot mutate limits outside the signed configuration path |
| `services/llm/` | Local Claude Code research process only; no trading keys, write path to production or authority to deploy |

SQLite WAL with one owning writer and off-box verified snapshots is a reasonable initial persistence choice. Other services use contracts, not direct shared database writes. Reconcile account identity, orders, fills, funding and balances before allowing new orders after restart. Snapshot restore is followed by exchange reconciliation; a backup can be stale.

**Adapter decision:** evaluate CCXT behind the current broker contract. Keep venue-native behavior for unsupported features. Its [manual](https://github.com/ccxt/ccxt/wiki/Manual) explicitly leaves ambiguous timeout reconciliation to the application. Compare adapter behavior using the existing simulator and recorded venue fixtures before any migration.

**Framework corrections:** Hummingbot documents [spot-perpetual arbitrage](https://hummingbot.org/strategies/v1-strategies/spot-perpetual-arbitrage/), so the draft's claim that no framework handles it is false. That does not prove it fits our recovery and maintenance requirements. Freqtrade is a candidate runner for the optional trend experiment, not a reason to bolt on a second live risk authority. Its funding and exchange limitations must be checked for the exact mode. See [technical review](../research/crypto-review-2026-10-30/execution_research.md). Reject unsupported “500 lines”, star counts and memory claims as selection criteria. Pin versions and run contract tests instead.

### Two-leg state machine

`FLAT -> APPROVED -> OPENING -> HEDGED -> CLOSING -> FLAT`; any stage can enter `RECONCILING`, `HALTED` or `UNRESOLVED_EXPOSURE`.

Persist each intent before sending. Approval binds proposal ID, config hash, instruments, maximum size/slippage and expiry; it is single-use. Re-check freshness and risk immediately before submission. On timeout, query orders/fills using client ID and account state; never blindly resend. Confirm cancels and late fills. Size the next leg from actual filled quantity, rounded with venue contract units. Slices are sized from liquidity and the approved maximum unhedged dollars, not an arbitrary 10%.

Risk-increasing entry needs human approval of a bounded mandate or proposal. Routine hedge maintenance and emergency reductions are pre-authorized within that signed mandate and logged. Telegram downtime must not prevent a safe exit. Un-kill and limit increases always need human action. A hedge repair may increase gross exposure, so it needs an explicit permitted recovery rule; otherwise reduce the surviving leg.

## 8. Failure policies that can actually execute

| Failure | Required behavior and evidence |
|---|---|
| Partial fill / late fill / duplicate event | Reconcile actual quantities, deduplicate by durable IDs, cancel uncertain residuals and repair or reduce within approved bounds |
| ADL or unexplained position change | Halt entries, reconcile fills/positions immediately, cancel stale intents and reduce surviving exposure where executable; alert with remaining delta. Do not merely halt while holding naked spot |
| Funding reversal / basis widening | Compare expected net benefit with exit costs using a frozen rule; adverse exposure/solvency limits override profitability. No universal three-day wait |
| Stale mark / disconnected websocket | Reject new risk, refresh from independent available snapshots; do not size from stale values |
| Margin deterioration | Use venue maintenance tiers and collateral haircuts under price/basis shocks. Reduce exposure first when feasible; transfer only from an approved reserve with explicit bounds. No unlimited automatic top-ups |
| Stablecoin depeg / bridge impairment | Independently value collateral; stop new exposure and assess risk-reducing routes. Do not blindly sell every asset into the impaired stablecoin. Freeze new transfers into the failing dependency |
| API outage / host death | External watchdog alerts and invokes a tested independent recovery path where reachable. If exchange is unreachable, record unresolved exposure; “flatten after 15 minutes” cannot be guaranteed |
| Withdrawal freeze / venue insolvency | No assumed flatten/withdraw capability. Stop new deposits/orders as appropriate, preserve evidence and follow incident procedure. Loss budget comes from pre-event exposure limits |
| Split brain / restart | Single-writer lease/fencing, durable intent IDs and exchange reconciliation; stale writer cannot create new risk |
| Compromised approval / agent output | Sender allowlist, one-time nonce, TTL and config binding; invalid/expired proposals rejected; agent output never executable shell or order instructions |

Monitoring needs a second failure domain. A process on the dead VPS cannot rescue itself. Measure detection, reconciliation and attempted reduction times; separately report cases where venue access prevents action. Depeg, ADL and venue loss tests must include scenarios where both price feeds or all trading endpoints fail.

## 9. Agent scope and operations

Use local Claude Code for hypotheses, source summaries, journals and incident explanations. Deterministic code owns data transformations, calculations, order states, limits and accounting. Do not let the model choose its own test or widen a failed threshold.

Tool flags are not a sandbox. Run under a separate OS identity with no exchange secrets, no production mount and no network path to the trading authority. Restrict built-in tools explicitly, disable unneeded MCP servers and pass only sanitized read-only artifacts. `--allowedTools` is not an exclusive security allowlist. Validate JSON against schema, reject malformed output and cap wall-clock time, concurrency and spending. `flock` prevents overlapping scheduled runs but does not isolate credentials.

Unattended subscription permission and billing behavior remain an account/terms verification gate. Do not assume `--max-budget-usd` controls subscription usage. If unavailable, keep research manual; the trading system must work without an LLM. “Best available model” is an explicit recorded model choice, with no silent downgrade.

Agent eval: held-out prompts containing prompt injection, malformed data, misleading annualization and requests for credentials/orders. Required: zero successful unauthorized actions, all invalid outputs safely rejected, and at least 99% valid outputs over a recorded sample of at least 100 cases. Blocked malicious requests count as successful defenses, not as proof that no attempts occurred. Schema validity is distinct from factual accuracy; every accepted numeric claim needs a reproducible artifact or source.

Keep development/backtests away from the execution host. Decide VPS shape from measured resident memory, CPU, disk and recovery headroom under replay and failure load; do not upgrade based only on a framework estimate. Separate existing unrelated production workloads before a live phase. Secrets stay out of Git, prompt context, logs and ordinary backups. Use dedicated least-privilege service identities; exact API restrictions are venue-specific. Manual withdrawals remain outside the trade-only key. Token rotation is only relevant if the existing credential is still in use or exposed; never paste it into this research.

## 10. Phases, approvals and stop conditions

| Phase | Deliverable | Exit gate |
|---|---|---|
| R0: this review | Reproduced screening audit, corrected proposal, source ledger, failure model | Completed as research; unresolved account facts explicitly listed |
| R1: bounded research, approval required | Nigeria eligibility dossier, chosen benchmark, cost/budget configuration; data-quality manifest and frozen tournament | Eligible products and sufficient data; budget/time ceiling approved before implementation. Otherwise stop before executor work |
| R2: portfolio experiment | Full capital accounting and reproducible candidate reports, adverse-cost/stress tests, trial registry | At least one candidate meets section 6 economic, uncertainty and stress gates; independent critic can reproduce it. Otherwise cash/no-build |
| R3: execution paper and chaos | Adapter/recovery contracts, ledger reconciliation, replay and operational measurement | Minimum 4 weeks operational paper plus all failure cases; zero unexplained position/order/balance differences. Cash residual tolerance fixed in quote-currency units from exchange rounding, never percentage of profit. Unknown orders resolved before new risk |
| R4: forward strategy observation | Frozen strategy/config and independently timestamped shadow decisions | Minimum 12 weeks from freeze, continuing through R3 where possible; economics meet pre-registered uncertainty gates. Too little evidence means extend within budget or stop |
| R5: separately approved micro-live | Minimum practical position under the configured capital and catastrophe budgets; one eligible venue; passing sleeve only | At least 8 weeks execution evidence; all fills/funding accounted for, measured slippage inside tested model, incident responses exercised, no unexplained loss/limit breach. This validates operations, not annual expected return |
| R6: scale or retire | Incremental allocation decision using live evidence | Each increase separately approved, after at least 4 further clean weeks, with liquidity/margin/concentration rechecked. Clock alone never promotes |

No account creation, deposit, trade, production deployment or code deletion is authorized by this document. Research approval does not imply approval for micro-live. If eligibility fails for carry, do not quietly substitute an offshore venue: evaluate an eligible spot candidate or stop.

Each implemented feature must include deterministic gate tests, service evals and documentation in the same change. Fast local checks cover units, timestamp availability, fill replay, conservation of equity and configuration rejection. Periodic evals cover historical replay, stress scenarios, forward monitoring and, only where a model is involved, local Claude quality evaluation. Keep paid evals outside pre-commit. Independent critics review each unit against a frozen reference; preserve verdict artifacts outside Git.

## 11. Deletion and completion policy

Nothing is deleted now. Any adapter retirement requires behavior parity, ambiguous-order recovery, recorded incident replay, documented cutover/rollback and zero active orders/positions owned by the old adapter. Preserve the simulator for regression and chaos tests. Archive obsolete implementations only after dependencies and accounting imports have been proven absent. CCXT adoption alone is never a deletion gate.

Outstanding facts are finite and actionable:

1. Current Nigerian product eligibility and authenticated fees/limits: requires the specific entity/account or qualified clarification. Blocks deposits/live, not public research.
2. Benchmark, capital and loss values: user-configurable; required before cost sizing and live enablement.
3. Historical executable price/depth and collateral series: collect/validate in approved R1; absent series limit what R2 can claim.
4. Prospective edge and live fills: only passage of time and approved experiments can provide them. This review cannot manufacture them.
5. Unattended Claude account permission: verify before scheduling; optional agent work never blocks deterministic strategy research.

Next decision: approve or reject **R1 only**, with a configurable research spending/time ceiling. Keep live disabled. No service restart is required for this documentation and audit change.
