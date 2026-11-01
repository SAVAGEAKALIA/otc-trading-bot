# R1 experiment specification: bounded universe, one primary claim

Version: `r1-spec-1`, 2026-10-31. **Protocol prepared; final experiment lock is provisional until the manifest, venue/product facts and configuration fields below are populated.** R1 is authorized. This document does not authorize R2 execution, paid services, deposits or live orders. No portfolio backtest or prospective performance result is reported here.

User facts: Nigeria residence; savings reference is USDT; Bybit, WEEX and Binance accounts are user-reported. Account product entitlements and actual fee tiers were not inspected. Capital and loss limits remain configurable and unset. USDT is a token benchmark with issuer/custody risk, not risk-free USD.

## 1. Competing designs and the selection

| Design | Primary experiment | Broader-asset treatment | Trade-off |
|---|---|---|---|
| A: BTC/ETH primary, wider screening | One equal-capital BTC/ETH carry portfolio against unchanged USDT holdings | SOL, XRP, DOGE, ADA, LINK, AVAX, LTC and BCH enter a mechanical current-product/data screen; no return-based selection | Keeps one interpretable claim and limits data work. It cannot claim an optimal universe or establish historical altcoin portfolio returns |
| B: broad point-in-time portfolio | All qualifying assets from a historically reconstructed eligible universe | Membership uses only data/metadata known at each rebalance, including removed assets | More directly tests opportunity breadth, but requires historical listings, delistings, spot availability and liquidity that the current snapshot does not establish |

**Select A for the first lock.** Selection is based on available evidence and validation burden, not observed funding returns. B is deferred until historical membership can be reconstructed. The wider screen is useful now: it determines which assets deserve later separate experiments and identifies liquidity/data failures without pretending today's survivors existed throughout history.

The candidate list is frozen for this R1 screen: BTC, ETH, SOL, XRP, DOGE, ADA, LINK, AVAX, LTC, BCH. It is a bounded engineering sample, not a market-wide ranking. No coin is added because its recent funding or returns look attractive. A failed candidate remains in the results with an exclusion reason; it is not silently replaced. Current spot/perpetual intersections and exclusion fields come from the data collector. If BTC or ETH fails a required input gate, the primary experiment is blocked rather than replaced by the next-best historical performer.

## 2. The trial registry

| ID | Role | Fixed initial definition | Claim permitted |
|---|---|---|---|
| `B0_USDT_HOLD` | Primary benchmark | Hold the starting number of USDT units, no assumed interest, marked to USD using the same independently sourced USDT/USD series as the strategy | Token-relative opportunity cost; does not assume identical custody/default risk |
| `P1_BTC_ETH_CARRY` | Sole confirmatory candidate | Equal starting programme capital in BTC and ETH sleeves; long fully paid spot and short a matched linear USDT perpetual, same verified venue/account model | Mean net daily USD return excess over B0, subject to the inference and safety gates below |
| `D1_ASSET_SCREEN` | Descriptive | All ten named assets: current listings, quotes, volumes, recent settled funding and data coverage | Data/operability inventory only; no alpha, historical universe or selection claim |
| `D2_DATED_BASIS` | Conditional descriptive comparator | BTC/ETH only; exact eligible dated contracts and settlement rules must be registered before any return calculation | Illustrative economics only until a separate complete contract and test is locked |
| `D3_SPOT_TREND` | Conditional descriptive comparator | BTC/ETH long/flat; equal-weight three Donchian components with entry lookbacks 20/55/100 completed daily bars and exit lookbacks 10/20/50 respectively; no shorting, no volatility target, no optimization | Descriptive independent strategy comparator, not another confirmatory winner |

The Donchian rule enters on a completed close strictly above the maximum high of the preceding entry-lookback bars, excluding the signal bar; exits on a completed close strictly below the minimum low of the preceding exit-lookback bars. Equality retains state. Each component begins flat after its full warm-up; missing bars block its signal. Execution timing is the same lagged rule as carry below. Required history exceeds the bounded recent R1 snapshot for some components; unavailable warm-up means `NOT_RUN`, not a shortened lookback.

Kronos, Chronos, FreqAI, Qlib and multi-agent debates are **not included in this lock**. They remain optional later protocols, requiring explicit trial registration before outputs are examined. R1 does not install Freqtrade or AI workbenches. The existing deterministic carry research boundary is the R2 accounting target; Freqtrade is only a possible later implementation of D3.

Every run records all attempted trials and failed variants. “Descriptive” results cannot later be relabeled confirmatory. To promote an altcoin, a second primary, or a selected comparator, start a new preregistered future-data experiment; disclose previous results and selection. If a later cohort contains multiple confirmatory hypotheses, its family and multiplicity correction must be frozen before that cohort starts. This protocol avoids that ambiguity by admitting exactly one primary claim.

## 3. Dates and observable information

At collection start, deterministic UTC code writes `retrieved_at`, `window_start`, `window_end_exclusive`, and requested/actual coverage to the manifest. `window_end_exclusive` is the start of the current UTC day; the most recent complete UTC day is the preceding interval. The client date is a document label, not a substitute for a computed UTC boundary. Incomplete last days and venue settlement delays are recorded, never annualized as complete observations.

All history already inspected, including the old funding file and the new recent screen, is development/descriptive data. Historical train/test partitions do not create an untouched holdout. Retain whole chronological episodes, including losses and failures. If later obtaining older history, record that it predates strategy design and still cannot remove human knowledge of those markets.

For R2's event model:

- Decision time is 00:05:00 UTC each day. Only records with both event time and demonstrated availability time strictly earlier than the decision may influence it. A settlement at the decision instant is excluded.
- Submit the simulated instruction no earlier than five minutes after that decision. Use the earliest valid executable quote at or after submission, with a maximum wait of 60 seconds. Buy at ask and sell at bid plus the locked incremental impact assumption. No quote in that interval means no entry; it does not mean a fill at the last price.
- Daily bars alone cannot support this execution model, spread or legging claim. They are adequate for R1 coverage and signal previews only. Historical execution-grade quotes/market data must be obtained, or the result stays an explicitly hypothetical price/cost sensitivity; it cannot pass the execution/capacity gate.
- Funding is credited/debited only for actual simulated quantity eligible at the venue's settlement timestamp, using the specified contract multiplier and settlement price. A newly filled position never receives the payment that triggered its signal.
- NAV is marked daily at 00:00:00 UTC from the freshest valid preceding valuation observations. Maximum valuation age is 60 seconds. A missing mark invalidates the primary NAV observation; it is not forward-filled silently. Existing exposure during a data outage remains in the ledger as unresolved, never disappears.

The 60-second quote/valuation bounds and five-minute lag are conservative research-policy constants, not measured venue latency or an approved live SLA. If data cannot meet them, record the limitation; do not widen them after seeing returns. Changing them creates a new protocol version.

## 4. Carry signal, sizing and exits

The initial experiment fixes a seven-complete-day trailing settled-funding estimator and a three-complete-day exit estimator. Sum actual settlements over timestamp windows; do not assume every venue settles three times daily. A historical cadence change needs historical evidence. Unknown cadence makes coverage unknown, not zero income.

At a flat sleeve's decision time:

1. Require all market-data, venue/product and cost inputs to pass.
2. Set the prospective matched base quantity from the approved sleeve capital, executable spot price and contract precision. Initial spot allocation is 40% of sleeve capital, initial short collateral 40%, and uncommitted operational reserve 20%. The short starts at at most 1x initial notional/collateral. All percentages are research-scenario assumptions, not the user's risk budget.
3. Estimate next-seven-day funding cash as proposed short notional times the sum of the preceding seven complete days' settled rates. This is a forecast proxy, not a promised payment.
4. Estimate a full round trip on both legs: four actual fee-bearing executions, bid/ask cost and separately modeled incremental market impact; include applicable conversion/borrow/transfer costs without double counting any cost already in the simulated fill.
5. Enter only when estimated seven-day funding exceeds **twice** the estimated round-trip trading cost plus seven days of allocated fixed operating cost and the configured benchmark opportunity cost. For B0's zero-interest USDT-unit baseline the interest component is zero; USD token-price movements remain in total returns. No assumed Earn income on margin or reserves.

While open, quantity stays matched unless a risk reduction or exit changes it; do not implicitly maintain fixed dollar notional without charging rebalances. Evaluate exits at the next daily decision: exit if the preceding three complete days' funding sum is negative, or if the position has been held for 28 complete calendar days. The fixed time exit bounds the holding episode and re-estimates costs before re-entry; no same-decision re-entry is allowed. At dataset end, close both legs using the prescribed next available executable quotes and charge exit costs; inability to close is reported as unresolved exposure with liquidation-value sensitivity, not a successful flat ending.

Risk and margin responses override signal exits. Exact maintenance tiers, intraday marks, collateral haircuts and account behavior are required to claim no liquidation. Initial 1x is not a continuing margin guarantee after a rally. R2 must simulate the approved risk envelope and reserve policy at event frequency; absent those inputs, only a funding/cost diagnostic may run and cannot pass. No automatic top-up from capital outside the registered reserve, no cross-venue transfer rescue, no leverage increase to pass economics.

The max-loss, margin, delta and emergency-response values remain lock-blocking fields below. This draft does not invent an executable risk policy for an uninspected account.

## 5. Capital, costs and benchmark contract

Report USDT-unit accounting and USD-marked programme equity together. Also retain NGN conversion records if conversion occurs; do not mix NGN yields into USD excess returns without the actual FX path and costs. USDT price is not fixed to one dollar by assumption.

Capital includes fully paid spot, separate collateral and all reserved/idle funds. Price P&L on both legs, settled funding, fees, borrowing, transfers, conversions and operating expenses form total P&L. Basis is an attribution of combined leg P&L, not an additional additive return. Deposits/withdrawals are external flows. No cash in two accounts is counted twice. Report fees/rounding in the denomination actually charged.

The following configuration values are **null until explicitly supplied or verified**:

- `capital_budget_usdt`, `max_loss_usdt`, `max_drawdown_pct`, `venue_loss_budget_usdt`, `stablecoin_loss_budget_usdt`;
- `risk_premium_bps`, `minimum_profit_usdt_year`, actual fixed operating costs and tax treatment;
- contracting entity/product permissions, account model, actual fees, maintenance tiers, asset haircuts and permitted recovery actions;
- exact alternate benchmark product, actual redemption/withdrawal costs, custody location and accessibility.

For public R1 cost sensitivity, hypothetical capital scenarios of 1,000, 5,000 and 10,000 USDT may be shown with their assumptions, never treated as a selected user allocation. Compute every value in deterministic code. Current published fee schedules can populate explicitly labeled provisional scenarios; missing or conflicting fees cannot be replaced by an invented VIP rate. Show normal and doubled execution-cost assumptions. The actual promotion report requires account fees and allocated fixed costs.

The USDT-hold benchmark is selected from the user's stated reference currency and assumes no interest product. It is not a recommendation to keep funds at an unverified venue. Strategy and benchmark custody/issuer exposure must be reported side by side; an excess return does not price default risk or make custody losses statistically bounded.

## 6. Exact primary evaluation and stop rules

Primary series: one daily paired observation `r_strategy_usd - r_usdt_hold_usd`, on all allocated capital after all modeled costs. The same USDT/USD valuation source/timestamp applies to both. Primary effect: arithmetic mean daily excess return, also reported in unannualized USDT/USD dollars over the actual period. Annualized values are explanatory only.

At final lock, write a hash over this protocol, full config, code revision, data manifests and eligibility evidence. Start prospective evaluation at the first complete UTC day after this lock and after the necessary collectors are healthy. Choose **180 consecutive UTC days** as the fixed primary evaluation horizon. The 12-week operational review is descriptive only; no early statistical promotion. No optional extension because a confidence interval is almost favorable. At 180 days, an inconclusive result remains inconclusive; a new cohort requires a new preregistration and disclosed prior results.

The inferential procedure to implement/test in R2 is a paired stationary block bootstrap of daily excess returns, 10,000 replicates, PRNG seed `20261031`, expected block length seven days, 95% two-sided percentile interval for the mean. Re-run expected block lengths 14 and 28 days as predeclared sensitivity checks; they are not an opportunity to choose the favorable interval. Paired resampling preserves the cross-series pairing. The [Politis–Romano stationary bootstrap](https://statistics.stanford.edu/technical-reports/stationary-bootstrap) addresses dependent stationary observations; regime changes and a limited sample can make its approximation poor. These constants are policy choices, not evidence that 180 days proves durable alpha.

A statistical pass requires the lower endpoint above zero for the primary interval **and both** block-length sensitivities. It also requires mean excess exceeding the configured economic hurdle, minimum dollar benefit, approved drawdown/stress budgets and all accounting/data gates. Any missing lock-blocking configuration means `NOT_ELIGIBLE_FOR_PROMOTION`, even if a chart looks favorable. Zero-variance/no-trade data cannot establish a positive edge.

No daily p-value monitoring, no selection among alternative fee assumptions, and no retroactive removal of a losing asset/month. Removing or revising a sleeve after observing performance ends the original experiment as stopped; preserve its result, then start a new future cohort if separately approved. Safety incidents may stop an experiment early; they cannot trigger a “pass.” Ordinary failed entry attempts or legitimate flat days stay in the return series. Missing valuation data causes an evidence failure, not deletion of bad days.

## 7. Data and adverse-scenario acceptance

| Case | Required R2 behavior / R1 evidence classification |
|---|---|
| Exact duplicate observation | Deduplicate by venue/product/event identity; retain duplicate count |
| Conflicting duplicate / non-finite rate | Reject the affected dataset and preserve conflicting records |
| Funding gap / changed cadence | Detect using documented applicable schedule; unknown schedule is `UNKNOWN_COVERAGE`, never a synthetic zero |
| Current spot listing but no historical listing evidence | Current operability only; no historical same-venue eligibility claim |
| Partial final day / future timestamp | Exclude from completed windows, retain diagnostic count |
| Missing quote, spread or intraday mark | No claimed executable fill or liquidation test; primary promotion blocked where required |
| Doubled fees/spread/impact | Recompute economics without changing signal parameters; report failure, do not optimize a rescue rule |
| Funding becomes negative, basis widens, rejected hedge leg | Debit actual funding and mark both legs; bounded recovery or unresolved exposure, not “delta neutral” by assumption |
| Price rally with short collateral stress and transfers unavailable | Use actual tier/haircut model; no use of segregated spot gains as instantaneous margin |
| USDT depeg / venue inaccessible / ADL | Independent token marks, issuer/venue loss scenarios and orphan-leg handling; no guaranteed flattening or loss cap |
| Seed/serialization replay | Identical inputs/config/code reproduce identical deterministic results and trial IDs |

Stress magnitudes and incident fixtures must be frozen with the venue-specific risk configuration before R2 promotion work. A scenario suite cannot turn venue-default probability into a bootstrap confidence interval. No historical screen can certify account solvency.

## 8. Required artifacts and status vocabulary

R2's schema must include `protocol_id`, `protocol_hash`, `code_commit`, `config_hash`, `data_manifest_hashes`, `eligibility_state`, `benchmark`, `capital_denominator`, `requested_coverage`, `actual_coverage`, `missingness`, `trial_id`, `all_attempted_trials`, `event_time`, `available_at`, `decision_time`, `order_time`, `fill_time`, `position_quantity`, `fee_currency`, `funding_cashflow`, `nav_usdt`, `nav_usd`, `external_flows`, `attribution_residual`, `cost_assumptions`, `stress_results`, `confidence_intervals`, `stop_reason` and `promotion_state`.

Allowed result states: `NOT_RUN`, `DATA_BLOCKED`, `ACCOUNT_FACTS_PENDING`, `DESCRIPTIVE_ONLY`, `INCONCLUSIVE`, `FAIL`, `PASS_RESEARCH_GATE`. None means live authorization. Every exclusion is inspectable, and a critic must reproduce a sample of records from raw sources.

R1 completion means the public evidence, configuration contract, dataset inventory and this specification are reviewable. It does not mean the final experiment hash is locked, missing account facts are verified, R2 is run, or the primary claim passes. Parent R1 report must list each missing lock field and its owner. Next action is to resolve those fields and approve the frozen R2 run; this document creates no recurring paid jobs or trading authority.
