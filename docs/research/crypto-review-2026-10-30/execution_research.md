# Execution and tooling audit

Date: 2026-10-30. Research only; no trading system, credentials, or deployment changed.

## Decision

Keep the existing ledger, order manager, simulator, and reconciliation contracts. Evaluate CCXT as an exchange adapter behind them. Research one venue, BTC/ETH, and one account model before approving implementation. A hedge controller is required, but an estimate of “500 lines” is not evidence of its safety or cost. Do not delete tested infrastructure to make the diagram smaller.

## Corrections supported by primary sources

| Draft claim | Finding | Planning consequence |
|---|---|---|
| No framework handles spot plus perpetual; Hummingbot is perp-only and defaults to 20x | Hummingbot documents `spot_perpetual_arbitrage`, opening opposing spot and derivative orders. Its documented leverage default is 1. The strategy page says maintainer “None”; V1 documentation says Foundation does not maintain V1 strategies. A particular perp-perp script does not establish framework-wide limitations. | Evaluate connector compatibility, recovery behavior, maintenance and migration cost. Reject for measured fit, not a false capability claim. [Strategy](https://hummingbot.org/strategies/v1-strategies/spot-perpetual-arbitrage/), [V1 maintenance](https://hummingbot.org/strategies/v1-strategies/). |
| CCXT replaces the OMS/reconciliation loop | CCXT documents an ambiguous result after `createOrder` times out and tells callers to check exchange orders and balances. Client IDs are exchange-dependent; fee fields can be incomplete. | Preserve persisted intent, idempotency, exchange-specific reconciliation and accounting. Contract-test the exact venue/account/product combinations. [CCXT manual](https://github.com/ccxt/ccxt/wiki/manual). |
| Bybit funding-history limitation is fine for S3 | Freqtrade's exchange page says Bybit live funding calculations also use its dry-run calculation. Long/short perpetual trend P&L depends on funding, even without a carry strategy. | Specify spot-only long/flat trend, or import and independently reconcile actual funding for futures research and live accounting. Do not confuse Freqtrade integration limitations with absence of exchange raw endpoints. [Exchange notes](https://www.freqtrade.io/en/stable/exchanges/). |
| Bias checks prove strategy correctness | `lookahead-analysis` tests changes across sliced backtests; `recursive-analysis` tests indicator dependence on startup history. Neither proves cost realism, point-in-time universe selection or statistical significance. | Require these checks and separate leakage, accounting, execution and selection-bias tests. [Lookahead](https://www.freqtrade.io/en/stable/lookahead-analysis/), [recursive](https://www.freqtrade.io/en/stable/recursive-analysis/). |
| Freqtrade about 2 GB; Hummingbot 4 GB | Published requirements recommend 2 GB and 2 vCPU for Freqtrade, and 4 GB per Hummingbot client instance. These are recommendations, not a workload measurement. | Dedicated executor resource budget plus a measured 72-hour soak. Research/LLM jobs run elsewhere; do not share an unmeasured 1 GB production host. [Freqtrade](https://docs.freqtrade.io/en/latest/), [Hummingbot](https://hummingbot.org/client/installation/). |
| NautilusTrader rejected because 2.x is RC | Official latest installation docs say 2.x is prerelease and not recommended for production, but stable 1.x exists. | Rejection can be migration/complexity cost; prerelease 2.x does not imply the whole project lacks stable releases. [Installation](https://nautilustrader.io/docs/latest/getting_started/installation/). |

GitHub stars are not correctness evidence. This review does not validate the draft's star counts, open-issue status, exact RC number, Telegram limitation, or “backtrader is dead” wording. Remove those assertions unless separately measured. Connector tests and operational ownership outrank popularity for this decision.

## Existing code worth preserving

Inspected directly, without claiming these components already cover carry:

- `trading_platform/execution/order_manager.py`: persisted intent and submission claiming; exchange execution IDs; applying broker snapshots.
- `trading_platform/execution/reconciler.py`: unknown orders remain `UNKNOWN`, without blind resubmission.
- `trading_platform/execution/account_reconciler.py`: replaces account projections from broker snapshots.
- `trading_platform/storage/outbox.py`: at-least-once event publishing with persisted errors.
- `trading_platform/risk/engine.py`: deterministic risk decisions with limit snapshots.
- `tests/contract/test_simulated_broker.py`: partial fills, idempotent client IDs, failure scripts, funding cashflows and deterministic ledgers.
- `tests/integration/test_balance_reservations.py`: balance reservation, idempotency and over-reservation protection.
- `tests/unit/risk/test_risk_engine.py`: stale signals/data, leverage/notional limits and liquidation buffers.

These are reuse candidates, not a certification. Missing carry-specific behavior includes a durable paired-trade state machine, aggregate spot/perp delta and collateral accounting, venue capability negotiation, safety-action authority and independent watchdog fencing. Retain simulated execution for deterministic fault injection even after retiring unused broker adapters. Delete a broker only after import/call-site audit, parity tests and rollback evidence, in a separate approved change.

## Proposed minimum execution design

One executor owns each venue account and its writable ledger. Market data and research publish versioned immutable observations/proposals. Risk is a versioned, independently tested component on the executor's order path, so a network dependency cannot bypass safety. Other services read snapshots or event contracts, never directly mutate that ledger. These are proposed boundaries pending approval.

Persist a `hedge_id` joining all spot/perp orders, fills, reservations and funding cashflows. Contracts include schema version, observation timestamp, receive timestamp, venue/account, contract multiplier, settlement asset, base quantity, quote value, approved limits/config hash and idempotency key.

State machine:

`FLAT -> ENTRY_AUTHORIZED -> ENTERING -> HEDGED -> EXITING -> FLAT`

Any stage may enter `REPAIR_REQUIRED`, `UNKNOWN`, or `HALTED`. `HALTED` blocks new economic exposure but does not prohibit authenticated, bounded safety reductions. A timeout is `UNKNOWN`, never an assumed reject. Recovery starts with exchange balances, open orders, positions and recent fills; no new entries until authoritative reconciliation completes. Handle pagination, duplicate/out-of-order events, delayed fills and a fill racing cancellation. Persist state before dispatch and deduplicate after restart.

No unconditional “spot first” or “perp first” rule is safe. Evaluate executable depth for both legs, enforce a dollar limit and time limit on temporary unmatched delta, and size slices by the weaker leg. Do not size only as “10% of target”: a large target can still create unacceptable exposure. On a partial fill, cancel the outstanding remainder, reconcile, then hedge or unwind the actual filled quantity within the approved safety budget. Use base-asset delta after fees and contract multipliers, not matching quote notionals at different prices. Inverse contracts require a separate tested implementation and stay out of the first release.

For every permitted safety action, record why portfolio risk decreases. Closing only a short is reduce-only at the derivative venue but increases net long delta; exchange `reduceOnly` is not a portfolio safety proof. ADL should cancel opening orders, reconcile and reduce the residual spot when possible. Halting and alerting while leaving naked spot is not adequate handling. Do not blindly reopen a forcibly closed short.

## Approval and watchdog semantics

Human approval binds strategy version, venue/account, instrument set, maximum allocation, expiry and risk configuration. Single-use entry approvals must be authenticated, replay-resistant and checked again against fresh prices/state at execution. A Telegram callback is an input channel, not the authority store. Manual unkill requires reconciliation, incident acknowledgement and a fresh authorization; no chat command directly bypasses risk limits.

Pre-authorize bounded hedge repair and emergency reductions when approving the operating envelope. These actions must not wait for a human reply. Funding receipts, bookkeeping and deterministic exits likewise need no new proposal approval. Increased allocation, new instruments, changed limits, new strategies and resumption after halt do require it.

A dead process cannot flatten itself. An independent off-host watchdog must detect stale heartbeats, alert, and, only with exclusive fenced authority and fresh exchange state, attempt the approved emergency policy. Test split-brain ownership explicitly. Exchange dead-man cancellation, where supported, cancels orders; it does not necessarily close positions. A venue/API outage can make any liquidation action impossible. Record attempted versus confirmed cancellation/closure separately. Never report “flat” from a sent request alone.

Replace “tails capped in code” and “always able to flatten” with: operational controls constrain intended exposure when data and execution remain available; venue insolvency, collateral failure, gaps, ADL and inaccessible markets can exceed the planned loss budget.

## Collateral and accounting requirements

Use exchange maintenance-margin tiers, mark prices and actual account mode, not just configured leverage. A 1x short can still liquidate after a sufficiently large rally, while segregated spot gains cannot automatically rescue its margin account. For each stress path record required collateral, available collateral, transfer availability, liquidation state and executable reduction cost. No automatic top-up beyond the already approved reserve.

Depeg detection needs independent price references, freshness checks and asset-specific actions. Selling spot into the failing settlement asset may worsen loss. “Flatten-only at 0.5%” is a trigger proposal, not a complete policy. Freeze entries, reconcile, evaluate asset conversion/withdrawal availability and act only inside pre-approved rules; withdrawal keys remain outside the executor.

Daily equity identity: opening equity + external flows + spot/perp price P&L + funding + collateral interest - trading/transfer/borrow costs = closing marked equity, with all non-USD assets converted consistently. Separately report strategy net P&L, infrastructure/subscription expenses, taxes if known, basis P&L, collateral FX/depeg P&L and unattributed residual. Match funding against exchange transaction records, not a rate forecast. Financial reporting must include all committed capital, including reserves and idle allocations.

## Claude Code isolation and scheduling

Official CLI documentation distinguishes `--allowedTools` (automatic approval) from `--tools` (built-in tool availability). `--tools` does not remove MCP tools. The dollar budget is a client-side estimate and can overshoot. Pin and record the tested CLI/model versions; assert supported flags before running; validate JSON output independently. [CLI reference](https://code.claude.com/docs/en/cli-reference).

The noninteractive CLI is documented for scripts. Current docs warn that headless mode may load project hooks/MCP configuration without interactive trust prompts; `--bare` skips automatic discovery. Use a controlled working directory and configuration, plus OS-level separation from trading credentials, databases and command sockets. Supply sanitized snapshots through stdin, initially with no tools or MCP servers. Do not assume disabling Edit/Write prevents mutation through shell or network tools. [Programmatic use](https://code.claude.com/docs/en/headless), [sandbox scope](https://code.claude.com/docs/en/sandboxing).

Use a dedicated unprivileged user, explicit environment, wall-clock deadline, concurrency lock, output-size limit and append-only run log. The LLM produces proposals only. Deterministic validators and human promotion keep model output outside the execution authority boundary. Run on demand first; a nightly schedule is justified only when it produces accepted research or saves measured operator time.

Anthropic documents unattended cloud schedules on subscription plans, and its legal page permits users signing into the unmodified CLI with their own subscription while restricting third-party credential intermediation. This supports ordinary individual automation, not an unlimited service entitlement. Confirm the account's plan, current terms and rate limits before deploying a wrapper; do not export or reuse OAuth credentials in a custom inference client. [Schedules](https://code.claude.com/docs/en/routines), [legal and credential terms](https://code.claude.com/docs/en/legal-and-compliance). No paid model runs were made in this review.

## Proposed acceptance evidence before live approval

These are candidate frozen gates for implementation, not results obtained here:

1. Every fault scenario ends in a reconciled position or a persisted unresolved state that blocks entries and alerts. Zero blind retries after ambiguous order submission; zero duplicated fills/funding cashflows after replay.
2. Scenario fixtures include partial fill plus timeout, cancel/fill race, stream gap, stale mark, API 429/5xx storm, restart between send and acknowledgement, disk-full, corrupt local projection, rejected safety order, ADL, contract multiplier change, depeg and unavailable venue.
3. Tests prove safety reductions remain authorized during halt and exposure-increasing orders remain blocked. Pair repairs cannot exceed a signed risk envelope; expired/replayed/forged approvals fail closed.
4. Benchmark detection and repair separately: measure p50/p95/p99 event-to-detection and detection-to-confirmed action; freeze actionable latency and unmatched-dollar limits from the measured venue path and approved loss budget. No universal 60-second or 15-minute promise.
5. Restore an off-host database backup, replay a recorded exchange event stream, and reconcile to the exact exchange state. A daily backup alone is insufficient for in-flight orders; retain durable intent/events and enough exchange history to reconstruct the gap. Test and document recovery point/time objectives.
6. Paper/live comparisons use identical timestamps and actual fills/funding. Compare reconciliation residual and execution shortfall in basis points or dollars, with a frozen absolute tolerance; percentage P&L differences become meaningless near zero. Testnet validates plumbing, not real liquidity or yield.
7. Resource soak includes market burst, reconnect, backup and log rotation; executor survives an LLM/research process failure. Fail closed on clock skew, stale data, or insufficient free storage.
8. Agent eval contains malformed output, prompt injection in logs/source pages, fabricated citations, unavailable tools, budget expiry and attempts to access trading credentials. Require zero successful unauthorized actions; count and review attempts rather than treating an absence of hook log entries as proof of isolation.

Next decision: approve a research-only adapter/hedge-controller specification after the economics and jurisdiction gates pass; retain the current execution infrastructure until replacement behavior is proved.
