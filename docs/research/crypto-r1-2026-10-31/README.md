# R1 research delivery

Evidence collected October 31, 2026; integrated November 1, 2026. R1 was explicitly approved. Nigeria residence, USDT reference and Bybit/WEEX/Binance accounts are user-reported. No funds, keys, private accounts, trading orders, paid services or production systems were used.

**Public R1 deliverables are complete. The final experiment lock and R1-to-R2 admission remain conditional.** This package establishes what we can test and exactly what is missing. It does not claim profitability, approve a venue or begin R2.

## Decisions

- **Bybit is the first public-data research venue**, because of the existing account and accessible paired spot/linear data. This is not regulatory clearance or a safety ranking. WEEX is a conditional comparator; Binance allocation remains pending resolution of the documented Nigerian regulatory question.
- **USDT hold is the initial benchmark**, with zero assumed token interest because no Earn product was specified. We also require independent USD marking in the eventual portfolio experiment. USDT is not a risk-free USD asset. If the actual alternative is an interest product, its terms and realized yield must replace this provisional opportunity-cost assumption before the final lock.
- **Broader research is included:** BTC, ETH, SOL, XRP, DOGE, ADA, LINK, AVAX, LTC and BCH. BTC/ETH form the sole initial confirmatory portfolio; the other assets remain descriptive candidates. No coin was selected by its observed return.
- **Use one primary claim.** A BTC/ETH carry portfolio must beat the same USDT holding after all costs and satisfy configurable risk and minimum-dollar-benefit requirements. A point-in-time broad portfolio is deferred until historical listings and liquidity can be reconstructed. Trend and dated basis are descriptive comparators, not extra winners chosen after looking at results.
- **No tool installation is needed for this stage.** Keep current OMS/ledger/risk ownership. Freqtrade, Vibe-Trading and model experiments remain later, separately bounded work.

## What was actually collected

The current instrument scan found 288 Bybit USDT spot/perpetual base-asset intersections. The bounded collection covered the ten predeclared assets over **August 2 through October 30, 2026 inclusive**, with an exclusive cutoff of October 31 at 00:00 UTC.

There are 75 saved public responses, 2,700 settled funding records and 3,600 daily candles (spot, perpetual, mark and index). All ten matched current pairs and passed the declared one-time spread/turnover screen. No whole missing days or duplicate timestamps were found; observed funding spacing is eight hours in this sample. This does not independently verify all historical cadence rules, intraday prices or trading capacity. Read [the complete data audit](market_data.md) and its [manifest](market_data_manifest.json).

The old 121,328-row funding snapshot was copied outside `/tmp` to ignored, content-addressed local storage. The [archive manifest](archive_manifest.json) records its SHA256, bytes and location. Both old and new raw datasets are **locally durable, not off-host replicated**. No raw dataset or binary is committed.

## Deliverables and reproduction

| Artifact | Purpose |
|---|---|
| [Eligibility and benchmark dossier](eligibility_benchmark.md) | Current-source venue/product, fee, USDT benchmark and withdrawal findings; unresolved account fields |
| [Market-data audit](market_data.md) | Universe, filters, coverage, limitations and exact replay commands |
| [Experiment specification](experiment_spec.md) | Selected design, candidate definitions, timing, capital, costs, statistical procedure, stop rules and lock blockers |
| [Example configuration](../../../services/research_r1/config.example.json) | Null capital/loss budgets; no live mode; hypothetical scenario assumptions only |
| [Configuration status](configuration_status.json) | Machine-generated unresolved fields; no final R2 lock or live approval |
| [Economic sensitivity CSV](economics_scenarios.csv) | 54 hypothetical combinations, not historical returns or recommended allocations |
| [Scenario service](../../../services/research_r1/README.md) | Decimal arithmetic, gate tests and adverse scenario evaluation |
| [Collector service](../../../services/market_data_r1/README.md) | Public allowlisted endpoints, checksummed raw snapshots and offline replay |

From the repository root:

```bash
python3 -m unittest discover -s services/market_data_r1/tests -v
python3 services/market_data_r1/evals/eval_scenarios.py
python3 -m unittest discover -s services/research_r1/tests -v
python3 services/research_r1/evals/eval_scenarios.py
python3 services/research_r1/scenarios.py --config services/research_r1/config.example.json --output /tmp/r1-economics-reproduced.csv
cmp docs/research/crypto-r1-2026-10-31/economics_scenarios.csv /tmp/r1-economics-reproduced.csv
```

The versioned `.githooks/pre-commit` runs both local gate suites and the staged whitespace check. It is enabled in this checkout. On a fresh clone, enable it with `git config core.hooksPath .githooks`; scenario evals remain explicit pre-ship checks.

Use the collector README's offline replay command with a fresh output directory to reproduce its report. Raw-response checksums must match the manifest. Collection at a later date produces a new snapshot; do not overwrite or relabel this historical screen as today's data.

## Economics and cost interpretation

The example scenario matches the protocol's 40% spot, 40% separate margin and 20% reserve. Thus one unit of hedged notional requires 2.5 units of programme capital. The starting short leverage is 1x; no cross-margin collateral offset, Earn interest or free use of spot appreciation as margin is assumed.

Capital amounts of 1,000, 5,000 and 10,000 USDT and annual operating costs of 0, 120 and 360 USDT are **hypothetical sensitivities**, not selected budgets. The six rate scenarios are after variable trading costs; deducting the same fee again would double count. This screen omits basis changes, liquidation, venue/issuer losses, FX and taxes, so it cannot establish strategy profit or a loss bound. Its value is showing how capital, reserves and fixed costs change the break-even point.

Published per-side fee schedules in the dossier are provisional research inputs. The actual R2 accounting must charge all four spot/perp entry/exit executions with the authenticated fee tier, spreads and incremental impact. A maker fill is not assumed merely because its fee is lower. The WEEX help-guide rate is explicitly not an authenticated current quote.

## What prevents the final lock

| Missing evidence/decision | Owner / next step | What it blocks |
|---|---|---|
| Bybit contracting entity, Nigerian product entitlement, exact margin/collateral mode and actual fees | User's redacted account information or a separately authorized read-only review; resolve regulatory ambiguity with authoritative evidence | Account-specific investability and venue admission |
| Capital, maximum loss, venue/issuer loss budgets, required excess and minimum dollar benefit | User-controlled configuration; scenario values are not substitutions | Economic/risk pass thresholds |
| Whether the USDT alternative earns interest, and its custody/redemption terms | User confirms actual existing savings product and location | Final benchmark and opportunity-cost choice |
| Historical listing/cadence/collateral changes, execution-grade quote/depth/intraday marks, independent USDT/USD marks | Explicit R2 data scope and feasible sources; current metadata cannot fill missing history | Executable fill, capacity, liquidation and USD-relative portfolio claims |
| Final code/config/data/eligibility hashes and prospective start | Independent review after required fields are resolved | Final preregistration lock and untouched forward evaluation |

Daily history already viewed is development evidence. The prepared primary protocol uses a fixed 180-day prospective horizon after the final lock, with no early statistical promotion. This is a proposed research-policy horizon, not evidence that six months guarantees an edge. All changes and failed trials remain recorded.

Current flags deliberately keep `r2_freeze_ready=false` and `live_enabled=false`. A JSON edit cannot substitute for account evidence or a signed final protocol. Public hypothetical research is possible despite missing account details, but a promoted account-specific result is not.

## Review and operational status

Independent critic artifacts are stored under `/tmp/crypto-r1/critique/`. Deterministic gate tests and offline adverse-case evals apply; no paid LLM eval is relevant to these non-LLM services. Findings are corrected before delivery, with regressions preserving the failure cases.

No service restart is required. Next: resolve the listed account/configuration inputs, then review the final locked R2 experiment before running it. R1 approval does not authorize R2, deposits or live trading.
