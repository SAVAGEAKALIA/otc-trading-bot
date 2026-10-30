# Trading engines, bot platforms and AI-assisted execution

Research date: 2026-10-30. Static source/documentation review, not an installation, performance benchmark, security certification or live-account test. No downloaded bot code was executed. Repository HEADs were resolved with `git ls-remote`; selected raw files were read at the immutable commits below. Changing `latest` documentation was checked separately and is not treated as proof about every released version. Current repository maintenance metrics belong in the ecosystem inventory; the decisions below concern fit and observed behavior.

## Recommendation

**Use Freqtrade for the optional spot-trend research/paper lane, retain our existing execution ledger and OMS for carry, and evaluate CCXT behind that contract.** FreqAI is an optional ML challenger after deterministic baselines, not a reason to start with an opaque model. A local Claude Code researcher may inspect sanitized research artifacts but has no trading authority.

**Runner-up for research: Jesse**, particularly its local MCP, batch backtests, rule-significance tests and Monte Carlo workflow. Its online docs (unpinned, unverified) say paper/live uses a separately licensed, prebuilt plugin. That possible commercial and runtime split, plus migration of our strategy/accounting contracts, makes it a second choice rather than a default replacement.

**Runner-up for a paired execution platform: Hummingbot**, if a later isolated experiment proves connector, partial-fill, funding-accounting and recovery parity. It genuinely has a spot/perpetual strategy. Its existence does not establish that it meets this project's failure contract. NautilusTrader is the stronger long-term event-driven platform candidate if measured complexity or latency requirements justify a migration; it is not rejected merely because its newest major version is prerelease.

These are tooling decisions, not claims that any default strategy earns money. Nigeria-specific venue eligibility, costs, capital and loss limits remain gates in the main plan.

## Ranked decisions by role

| Role / repository | Useful capability | Constraint that matters here | Decision |
|---|---|---|---|
| Exchange library: [ccxt/ccxt](https://github.com/ccxt/ccxt) | Unified REST + WebSocket API. The pinned README's certified section lists 12 "CCXT Certified" exchanges (including Binance, Bybit, OKX, Gate, KuCoin, Bitget, Hyperliquid and MEXC) with "CCXT Pro" | The pinned [Manual](https://raw.githubusercontent.com/ccxt/ccxt/a1bd1dd550c67db735107447b698a34a34c2efa6/wiki/Manual.md) (§RequestTimeout, line 9366) says: on `RequestTimeout` "the user doesn't know the outcome of a request". For `createOrder()` the user must reconcile through `fetchOrders`/`fetchOpenOrders`/`fetchClosedOrders` and then `fetchBalance`. The README's exchange table carries exchange referral links. | **Adapt** behind our broker contract; ambiguous-order recovery stays in our ledger/OMS |
| Directional research and paper: [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | Crypto strategy backtesting, dry-run, live execution, UI/Telegram, bias checks; FreqAI lives in the same repository | A single-instrument trade lifecycle does not by itself implement our durable spot/perp hedge contract. Futures accounting remains venue/version-specific | **Adapt first** for isolated spot long/flat experiments; do not make it a second writer on the carry account |
| ML challenger: [FreqAI](https://www.freqtrade.io/en/stable/freqai/) | Feature pipelines, supervised models, retraining and historical training windows; RL interface available | This is predictive ML/RL, not an LLM analyst. Retraining, feature leakage and model selection require their own frozen evals | **Defer** until it beats the fixed non-ML baseline net of costs on untouched observations |
| Paired-trade alternative: [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | Connectors, market-making/arbitrage framework, executors, spot/perpetual strategy | V1 strategy and V2 funding sample are different implementations; recovery/maintenance and exact account support must be tested | **Defer (runner-up executor)**: adopt only after an isolated parity experiment; borrow contract ideas, do not blindly run samples |
| Hummingbot control plane: [hummingbot/hummingbot-api](https://github.com/hummingbot/hummingbot-api) | Bot/account/order management through an API and assistant integration | Controls real trading and credentials; documented deployment adds API, PostgreSQL and EMQX. It is not a lightweight read-only analysis API | **Defer** unless selecting Hummingbot as the executor, with private network and isolated authority |
| Hummingbot UI: [hummingbot/dashboard](https://github.com/hummingbot/dashboard) | Backtest/optimization and bot orchestration | The inspected README states authentication is disabled by default and supplies default credentials. Review actual deployed config before access | **Do not deploy unchanged**; optional private operator UI only after platform selection |
| AI/Telegram orchestration: [hummingbot/condor](https://github.com/hummingbot/condor) | Interactive portfolio, bots, executors, trading, routines and optional agent/MCP integration | Trading and credential-management capabilities exceed our research-agent mandate. Provider options do not automatically satisfy the local-Claude-only contract | **Reject as default agent authority**; inspect UI/routine ideas or use a separately permissioned human console only after review |
| Research runner-up: [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | Python strategies, local MCP, data/backtest/Monte Carlo and rule-significance workflow | The pinned README advertises live and paper trading (README lines 21, 94-95). That live/paper operation needs a separately licensed, prebuilt plugin comes only from Jesse's unpinned online docs ([livetrade](https://docs.jesse.trade/docs/livetrade), read 2026-10-30), so treat it as **unverified** | **Defer (research runner-up)**: challenge Freqtrade on identical data and costs only if research UX saves measurable time |
| Retail automation: [Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot) | Grid, DCA, TradingView, paper/backtest workflows and AI connectors | Inspected README calls the new node interface beta, notes Bybit API restoration pending, and describes LLM-opinion-driven trading | **Reject for initial stack**: unnecessary migration and unsuitable default AI authority; reconsider only for a separately defined retail automation use case |
| Contrarian grid: [enarjord/passivbot](https://github.com/enarjord/passivbot) | Python/Rust perpetual bot with shared order planning for live/backtest and optimization | Default `trailing_martingale` adds into adverse moves; that is not delta-neutral funding carry and is not the chosen low-turnover trend family | **Reject for this mandate**, not because its implementation is necessarily poor |
| Event-driven platform: [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | Backtest/live event architecture, adapters, risk/execution and explicit reconciliation concepts | Stable 1.x and prerelease 2.x have different APIs. Migration introduces a new execution model and testing burden | **Defer migration**; preferred platform challenger if our existing event stack becomes the bottleneck |

“Reject” here means reject as a component of this project's initial stack, not a universal judgment of quality. No strategy pack or marketplace return chart was accepted as alpha evidence.

## Deep inspection: what the code actually does

### Freqtrade: check versioned accounting, not issue headlines

At commit `7fea5ea24b3c3193cfdd4143b243f7baab66d661`, [`Exchange._get_funding_fees_from_exchange`](https://github.com/freqtrade/freqtrade/blob/7fea5ea24b3c3193cfdd4143b243f7baab66d661/freqtrade/exchange/exchange.py#L3768) loops over funding-history pages, deduplicates by timestamp and advances past the newest entry. Thus the earlier no-pagination complaint is not an accurate description of this inspected revision. The timestamp identity assumption still needs venue-specific contract tests; source reading is not a proof of all exchange semantics.

[`FreqtradeBot.update_funding_fees`](https://github.com/freqtrade/freqtrade/blob/7fea5ea24b3c3193cfdd4143b243f7baab66d661/freqtrade/freqtradebot.py#L548) delegates to exchange funding retrieval and persists updates for open trades. Our independent account ledger should compare exchange-settled cashflows rather than take a UI P&L figure as authority. [Release 2026.9](https://github.com/freqtrade/freqtrade/releases/tag/2026.9) (release notes read live on 2026-10-30, not pinned) includes fixes for funding being reset during repeated filled-order processing and cross-margin wallet handling. Pin tested versions; do not call a release immune to adjacent accounting defects.

The [FreqAI RL documentation](https://www.freqtrade.io/en/stable/freqai-reinforcement-learning/) ("stable" docs read live on 2026-10-30, not pinned) states that its simplified training environment omits strategy callbacks such as custom stops/exits and leverage controls. Training reward can therefore differ materially from deployable economics. Supervised FreqAI is the more natural first ML experiment for a research challenger; neither variant removes the need for forward validation. Local numerical ML training does not conflict with the repository's rule that LLM access must use local Claude Code.

### Hummingbot: two distinct strategies, neither an atomic exchange primitive

At commit `9af100d6822da7d2d0291a906c730ef172284ee2`, [`spot_perpetual_arbitrage.execute_arb_proposal`](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/strategy/spot_perpetual_arbitrage/spot_perpetual_arbitrage.py#L381) submits spot and perpetual taker orders without waiting for the first leg's confirmed fill. Its state update checks two completed-order IDs plus perpetual position state. This is concrete evidence of paired execution, but not of atomic settlement or full orphan-leg recovery. Partial-fill, late-fill and venue-failure fixtures are required before adopting it. The [V1 strategy documentation](https://hummingbot.org/strategies/v1-strategies/spot-perpetual-arbitrage/) (read live on 2026-10-30, not pinned) reported no assigned maintainer; maintenance responsibility cannot be assumed from a busy main repository.

The separate [`v2_funding_rate_arb.py`](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/scripts/v2_funding_rate_arb.py#L18) sets sample leverage to 20 and compares funding across derivative connectors. Its funding interval normalization uses a connector interval map and an eight-hour fallback. These are sample-specific facts, not a framework-wide 20x default or proof that all Hummingbot arbitrage is perp/perp. They are reasons to replace sample defaults with a verified instrument/account contract.

The [API README](https://github.com/hummingbot/hummingbot-api/blob/7ae108f11bf20651682dbdff639a8717068c5883/README.md) and [Condor README](https://github.com/hummingbot/condor/blob/f825393daa8f98c89ffe9e5708f1b7cefcd37dfc/README.md) explicitly warn that their control surfaces reach real orders and stored exchange credentials. Telegram confirmations and a private network are useful layers, not a substitute for the project’s deterministic risk service and credential isolation. Do not expose the API or dashboard as an unrestricted model tool.

### Jesse: a serious analysis alternative, with a possible commercial boundary

The [pinned README](https://github.com/jesse-ai/jesse/blob/aded4b9d51d432d411a8f7fbf45e47572dff6629/README.md) and [MCP documentation](https://docs.jesse.trade/docs/mcp/) (unpinned, read live on 2026-10-30) describe assistant-accessible strategy/data research, backtests and uncertainty checks. This fits AI-assisted research better than giving an assistant order endpoints. However, agent rules are not a sandbox: isolate credentials and allow only the intended research tools. A Monte Carlo or random-entry test is a diagnostic, not a substitute for holdout evidence after repeated strategy searches.

[Live installation documentation](https://docs.jesse.trade/docs/livetrade) (unpinned, read live 2026-10-30) states both live and paper operation use the official plugin, distributed prebuilt to active license holders. Verify against a pinned copy before relying on it. The MIT core and plugin entitlement are different procurement questions. No price is quoted because a current offer and account terms would need verification before purchase.

### NautilusTrader: judge the release line correctly

[Installation guidance](https://nautilustrader.io/docs/latest/getting_started/installation/) explicitly distinguishes stable 1.x from prerelease 2.x and advises against live capital on release candidates. The [reconciliation concepts](https://nautilustrader.io/docs/latest/concepts/execution/reconciliation/) and [adapter guide](https://nautilustrader.io/docs/latest/developer_guide/adapters/) are useful references for uncertain order outcomes, complete account snapshots and consistent fill identities. Those latest docs are not a guarantee that a chosen stable 1.x adapter exposes identical behavior. A migration decision must select one release line and run the same incident fixtures against it.

## Real user reports and maintenance response sample

> Issue dates, labels and comment states in this section were read from live GitHub pages on 2026-10-30. They are not pinned, so later edits may change them.

This is a purposive sample of problems relevant to our funding/accounting/restart requirements, not a representative reliability survey. User reports establish reported symptoms; fixes and inspected code provide stronger evidence. No claim of median maintainer response time is made from this sample.

| Primary report | Observed response / state at review | What it changes |
|---|---|---|
| [Freqtrade #13707](https://github.com/freqtrade/freqtrade/issues/13707), funding-history truncation, opened October 25, 2026 | Maintainer interaction and completed closure are dated October 25; the issue links commit `ba9f6de`. The pinned source now contains pagination | Positive evidence of a specific maintenance response, and a mandatory long-held-position funding regression case. Not a claim every issue is fixed that day |
| [Hummingbot #8413](https://github.com/hummingbot/hummingbot/issues/8413), Hyperliquid funding display/calculation report, opened August 7, 2026 | A contributor commented August 15 proposing a parser fix; issue page remains open. No merged fix was verified in this review | Require raw funding payload-to-rate/interval fixtures. Do not treat a volunteer's diagnosis as a confirmed root cause or completed repair |
| [Hummingbot #7591](https://github.com/hummingbot/hummingbot/issues/7591), Bybit P&L/funding report, opened May 2, 2025 | June 20 label/title triage is visible; page remains open. Report concerns version 2.5 | Supports independent funding/cashflow reconciliation. It does not prove the same defect persists on the inspected HEAD |
| [Passivbot #980](https://github.com/enarjord/passivbot/issues/980), duplicate entry after delayed fill ingestion | Reporter describes a demo/paper account, not proven live monetary loss. Visible later comment asks about reconstruction, not a demonstrated fix | The event-ordering failure is a valuable chaos-test scenario regardless of bot choice. Do not market it as audited current live loss |

## Licensing and pinned inspection record

License files were fetched at these commits and checked. File, first line and SHA256 per repository are in [licence_pins.md](licence_pins.md). These labels are a software selection inventory, not legal advice about combining or redistributing code. Extensions, hosted services and data feeds can have separate terms. Preserve notices and obtain a distribution-specific license review before copying code across incompatible license boundaries.

| Repository | Inspected HEAD | Core license |
|---|---|---|
| freqtrade/freqtrade | `7fea5ea24b3c3193cfdd4143b243f7baab66d661` | GPL-3.0 license file |
| hummingbot/hummingbot | `9af100d6822da7d2d0291a906c730ef172284ee2` | Apache-2.0 |
| hummingbot/hummingbot-api | `7ae108f11bf20651682dbdff639a8717068c5883` | MIT |
| hummingbot/dashboard | `ee42595bec85518eda0b9fe1a56046d09a3e36c6` | Apache-2.0 |
| hummingbot/condor | `f825393daa8f98c89ffe9e5708f1b7cefcd37dfc` | MIT |
| jesse-ai/jesse | `aded4b9d51d432d411a8f7fbf45e47572dff6629` | MIT core (live plugin terms unverified, see above) |
| ccxt/ccxt | `a1bd1dd550c67db735107447b698a34a34c2efa6` | MIT (LICENSE.txt); Manual/README/LICENSE hashes in `/tmp/crypto-ecosystem/ccxt-sources/manifest.json` |
| Drakkar-Software/OctoBot | `c45fdc2c95c5bd3d649251fa90c327e2e8f86b00` | GPL-3.0 file; README says v3 or later |
| enarjord/passivbot | `f6ffee98c3abe22b321a9b14641bc3133d7855cd` | Unlicense |
| nautechsystems/nautilus_trader | `6dc35da8be6582c9ea71a21e5f6d19f7e9164533` | LGPL-3.0 license file |

The immutable source URLs make the inspected behavior retrievable even after HEAD changes. Local read copies and file hashes are recorded at `/tmp/crypto-ecosystem/trading-sources/manifest.json`; they are inspection evidence, not a vendored dependency or installed runtime.

## Architecture variant A: preserve execution, compete on research

1. Keep the existing OMS, ledger, simulator and risk authority. Add exchange coverage through a contract-tested CCXT adapter only when the approved research gate calls for it.
2. Run Freqtrade as a separate spot-trend research/paper service. Import/export immutable datasets and reports through versioned contracts; it owns no carry account and cannot bypass the programme budget.
3. Test one fixed non-ML trend baseline first. FreqAI supervised learning or Jesse research tooling may challenge it on identical data, fees and a registered trial budget. Research convenience is measured by operator time and reproducibility, not a better-looking backtest chart.
4. Local Claude reads sanitized reports, proposes a hypothesis and explains anomalies. A deterministic runner validates parameters, runs the experiment and records every trial. No unrestricted Hummingbot/Condor/MCP trading tools are attached.
5. Only if economic evidence passes, compare the existing carry executor against Hummingbot's relevant connector/paired-trade behavior with identical failure fixtures. If existing contracts cannot meet measured requirements without substantial replacement, evaluate a pinned stable Nautilus release as a deliberate migration rather than layering a second OMS beside ours.

Pass for this variant means a minimal number of execution authorities, reproducible strategy experiments, no new hosted LLM dependency, and explicit rejection when economics or operational proof is absent. No bot from this survey receives live trading approval.
