# Crypto ecosystem review: what to adopt, adapt, defer or reject

Date: 2026-10-30. This answers "have you checked other trading bots, analysis
bots, AI-assisted trading bots and GitHub repos" for the Nigerian-resident
capital-allocation plan
([docs/plans/2026-10-30-crypto-plan.md](../../plans/2026-10-30-crypto-plan.md)).

**Scope and honesty limits.**
- 35 repositories were reviewed, each read at a pinned commit (README, licence
  and selected docs/source; CCXT's Manual is pinned in `trading_bots.md`).
  None was installed, executed or connected to an exchange.
- `hummingbot/dashboard` was also reviewed in `trading_bots.md` (default
  credentials, auth disabled by default) but is not counted in the 35 or in
  the snapshot.
- A capability is not alpha. No repository in this review provides
  independently verified live profitability, and stars measure attention, not
  reliability.
- The frozen acceptance rubric is in
  `/tmp/crypto-ecosystem/critique/rubric.md` (outside Git, as CLAUDE.md requires).

## The recommendation

**Recommended stack (minimal, one execution authority):**

| Role | Choice | Why |
|---|---|---|
| Carry execution, ledger, risk, reconciliation | **Keep `trading_platform`** (OMS, ledger/outbox, simulator, risk engine) | Already built and tested. No reviewed framework was shown, in the source we read, to implement our two-leg failure contract (ADL, partial legs, ambiguous orders). One writer per account. |
| Exchange access | **Adapt [CCXT](https://github.com/ccxt/ccxt)** behind the existing broker contract | Broad, active venue coverage. Its manual leaves ambiguous-timeout reconciliation to the application, which is the part we already own. It is adopted only after it passes our contract and fixture tests. |
| Optional spot-trend sleeve (research + paper) | **Adapt [freqtrade](https://github.com/freqtrade/freqtrade)**, separate account, spot long/flat | Dry-run, bias checks (`lookahead-analysis`, `recursive-analysis`). It never touches the carry account. |
| Research process | **Adapt the [RD-Agent](https://github.com/microsoft/RD-Agent) pattern** on local Claude Code: the agent proposes, a deterministic runner tests, and every trial is registered | Supported by the authors' own historical-market paper ([arXiv 2505.15155](https://arxiv.org/abs/2505.15155)), not independently replicated; we adopt the process, not the runtime |
| Agent tools | **No write-capable MCP or trading tools**; sanitized read-only artifacts only | freqtrade-mcp exposes `place_trade`, and mcp-server-ccxt exposes `place-market-order` when keys are set ([gap_closure.md](gap_closure.md)) |
| Forecasting challenger (optional) | **Defer [Kronos](https://github.com/shiyu-coder/Kronos)-small, zero-shot**, as one pre-registered R2 trial; Chronos-2 as the generic control | An additional forecasting candidate, not an established edge. The skeptical prior applies, and it is counted in the trial budget. |

**Gated research pilots** (outside the stack). Each needs explicit approval and runs on an isolated host with no exchange credentials:
- the Vibe-Trading research workbench, at a pinned revision
- the quant-bench evaluation protocol, as an offline cross-check only

TradingAgents is **deferred** until a local-Claude client for it is tested, because it has no local Claude Code provider: its providers are hosted APIs or local non-Claude models (Ollama), and neither meets the repository's local-Claude-Code rule.

**Runner-up stack:** [Hummingbot](https://github.com/hummingbot/hummingbot)
as the paired executor. It does have a spot-perpetual strategy. The
[hummingbot-api](https://github.com/hummingbot/hummingbot-api) control plane
would be added only for a private-network human console. Condor is rejected as agent authority;
a separately permissioned human console is possible only after review.
- **Choose it only if** an isolated parity experiment shows connector,
  partial-fill, funding-accounting and recovery behavior that is better than
  ours on identical incident fixtures.
- **Cost:** a second execution model, an API + PostgreSQL + EMQX deployment,
  and credential authority to isolate.

**Long-term alternative:** a pinned stable
[NautilusTrader](https://github.com/nautechsystems/nautilus_trader) 1.x
migration, done as a deliberate replacement and never layered beside our OMS.
It is warranted only if measured complexity or latency outgrows the current
event stack.

**Research-tool runner-up:** [Jesse](https://github.com/jesse-ai/jesse),
compared against freqtrade on identical data and costs. Its online docs (unpinned, unverified) say
live/paper needs a separately licensed plugin.

**AI-research runner-up:** Qlib, only when a registered ML/factor hypothesis needs it.

## Ranked shortlist (35 repositories, plus FreqAI as a freqtrade feature)

Decisions apply to *this* project's initial stack. "Reject" is not a
universal quality judgment. The detailed evidence is in the linked reports.

| # | Repository | Category | Decision | Deciding reason | Report |
|---:|---|---|---|---|---|
| 1 | ccxt/ccxt | Exchange library | **Adapt** | Venue coverage behind our contract; recovery stays ours | [trading_bots](trading_bots.md) |
| 2 | freqtrade/freqtrade | Trading framework | **Adapt** | Spot-trend research/paper lane only | [trading_bots](trading_bots.md) |
| 3 | microsoft/RD-Agent | AI research loop | **Adapt (pattern)** | Hypothesis → deterministic test → feedback; runtime needs hosted models and embeddings | [ai_analysis_bots](ai_analysis_bots.md) |
| 4 | HKUDS/Vibe-Trading | AI research | **Gated pilot (approval required)** | Native local Claude CLI provider; its own source warns its tool filters are not a sandbox | [ai_analysis_bots](ai_analysis_bots.md) |
| 5 | Starlien95/Awesome-TradingAI (quant-bench) | AI evaluation | **Gated pilot (offline protocol)** | Separates historical, paper and live modes; offline cross-check, never live | [ai_analysis_bots](ai_analysis_bots.md) |
| 6 | shiyu-coder/Kronos | Candle foundation model | **Defer (1 R2 trial)** | Zero-shot, pinned, counted in the trial budget | [gap_closure](gap_closure.md) |
| 7 | amazon-science/chronos-forecasting | Time-series FM | **Defer (control)** | Generic control for the Kronos trial | [gap_closure](gap_closure.md) |
| 8 | hummingbot/hummingbot | Trading framework | **Defer (runner-up executor)** | Needs a parity experiment first | [trading_bots](trading_bots.md) |
| 9 | jesse-ai/jesse | Trading framework | **Defer (research runner-up)** | Migration cost; live/paper plugin licensing per unpinned docs (unverified) | [trading_bots](trading_bots.md) |
| 10 | nautechsystems/nautilus_trader | Event-driven platform | **Defer (long-term)** | Stable 1.x vs prerelease 2.x; migration, not a layer | [trading_bots](trading_bots.md) |
| 11 | microsoft/qlib | ML research engine | **Defer (AI-research runner-up)** | Preferred engine only if a registered ML/factor hypothesis needs it | [ai_analysis_bots](ai_analysis_bots.md) |
| 2a | freqtrade FreqAI (feature of #2) | Predictive ML | **Defer** | Must beat the fixed non-ML baseline first | [trading_bots](trading_bots.md) |
| 12 | hummingbot/hummingbot-api | Control plane | **Defer** | Only with Hummingbot; 3-container deploy | [gap_closure](gap_closure.md) |
| 13 | nkaz001/hftbacktest | Market-making sim | **Defer** | Market making is out of scope | [gap_closure](gap_closure.md) |
| 14 | QuantConnect/Lean | Engine | **Defer** | Serious engine; migration exceeds a two-symbol need | [research_tools](research_tools.md) |
| 15 | OpenBB-finance/OpenBB | Data platform | **Defer** | Useful for many providers, excessive for two funding streams | [research_tools](research_tools.md) |
| 16 | polakowo/vectorbt | Vectorized backtests | **Defer** | Apache-2.0 + Commons Clause; does not do paired-position accounting | [research_tools](research_tools.md) |
| 17 | kernc/backtesting.py | Backtester | **Defer (cross-check)** | AGPL; simple long/flat check only | [research_tools](research_tools.md) |
| 18 | Lumiwealth/lumibot | Framework + AI agents | **Defer (borrow eval ideas)** | Model calls inside the strategy lifecycle | [research_tools](research_tools.md) |
| 19 | Superalgos/Superalgos | Visual platform | **Defer** | A second execution/data model | [research_tools](research_tools.md) |
| 20 | TauricResearch/TradingAgents | LLM debate agents | **Defer; reject as order authority** | Challenger only after a local-Claude client is tested; no local Claude Code provider (hosted APIs or local Ollama only) | [ai_analysis_bots](ai_analysis_bots.md) |
| 21 | virattt/ai-hedge-fund | LLM paper fund | **Adapt ideas; defer framework** | Hash-chained ledger and mandate ideas; would duplicate our OMS | [ai_analysis_bots](ai_analysis_bots.md) |
| 22 | AI4Finance-Foundation/FinRL | RL framework | **Defer** | Later RL experiment, if ever | [ai_analysis_bots](ai_analysis_bots.md) |
| 23 | AI4Finance-Foundation/FinRL-Trading | Portfolio pipeline | **Defer / reject as crypto executor** | Alpaca equity execution | [ai_analysis_bots](ai_analysis_bots.md) |
| 24 | google-research/timesfm | Time-series FM | **Reject for R2** | One generic control is enough | [gap_closure](gap_closure.md) |
| 25 | AI4Finance-Foundation/FinRobot | Equity research agents | **Reject** | Equity DCF/filings focus | [ai_analysis_bots](ai_analysis_bots.md) |
| 26 | AI4Finance-Foundation/FinGPT | Financial LLM | **Reject** | Equity sentiment; not part of the mechanism | [gap_closure](gap_closure.md) |
| 27 | hummingbot/condor | Agent console | **Reject as agent authority** | Trading and credential capability | [trading_bots](trading_bots.md) |
| 28 | NoFxAiOS/nofx | AI trading platform | **Reject Autopilot** | Model-driven live execution; Frontier is a UX reference only | [ai_analysis_bots](ai_analysis_bots.md) |
| 29 | elizaOS/eliza | Agent framework | **Reject** | Wallet-signing plugins conflict with "agent has no keys" | [gap_closure](gap_closure.md) |
| 30 | kukapay/freqtrade-mcp | MCP server | **Reject** | Exposes `place_trade` | [gap_closure](gap_closure.md) |
| 31 | doggybee/mcp-server-ccxt | MCP server | **Reject keyed; public-only optional** | `place-market-order` with keys | [gap_closure](gap_closure.md) |
| 32 | Drakkar-Software/OctoBot | Retail bot | **Reject for initial stack** | Beta node UI, Bybit restoration pending, LLM-opinion trading | [trading_bots](trading_bots.md) |
| 33 | enarjord/passivbot | Grid/martingale bot | **Reject for mandate** | Default trailing martingale adds into adverse moves | [trading_bots](trading_bots.md) |
| 34 | 50shadesofgwei/funding-rate-arbitrage | Funding-arb template | **Reject** | DEX perp-perp, stale, untested in production per its README, licence unclear | [gap_closure](gap_closure.md) |
| 35 | CryptoSignal/Crypto-Signal | Signal scanner | **Reject (historical reference)** | Latest default-branch commit 2022 | [research_tools](research_tools.md) |

## How the rubric was met

| Rubric item | Where |
|---|---|
| Executable frameworks, backtesting, analysis, LLM research, autonomous AI claims | All five categories in the table above |
| ≥ 15 repos with maintenance/licence evidence | 35 in [github_snapshot.md](github_snapshot.md) (collected 2026-10-30T19:18:51Z) |
| Deep inspection of the leading candidate per category | freqtrade/Hummingbot/Jesse/Nautilus in [trading_bots](trading_bots.md); Vibe-Trading/RD-Agent/TradingAgents/NOFX/FinRL-X in [ai_analysis_bots](ai_analysis_bots.md); Kronos/MCP servers in [gap_closure](gap_closure.md) |
| Issue responsiveness and real-user feedback, with sample limits | [github_snapshot.md](github_snapshot.md) and the user-report sections of each report |
| Alternatives compared against this repo's constraints | "The recommendation" above (stack, runner-up, long-term) |
| Reproducible metadata collection + deterministic tests | `collect_github.py`, `test_collect_github.py` (18 tests, including the no-overwrite-on-failure regressions for repository and issue fetches) |

## What was not done

- **No installs, benchmarks, credential flows or orders.** Memory footprints
  are documentation claims, not measurements.
- **No verified live P&L for any project.** None is claimed.
- **Licence files are pinned** ([licence_pins.md](licence_pins.md) and the per-report manifests). Data-provider terms and
  commercial plugin terms were not reviewed in full.

Before any adoption: pin the release, run our event fixtures through it, and
prove each permitted capability without trading credentials.

## Reproduce

```bash
cd docs/research/crypto-ecosystem-2026-10-30
python3 test_collect_github.py
GITHUB_TOKEN=... python3 collect_github.py --output github_snapshot.json   # optional token; refuses to overwrite on any repository or issue fetch error
```

The pinned source URLs for each read file are in the pin tables of
`trading_bots.md`, `ai_analysis_bots.md`, `research_tools.md` and `gap_closure.md`.
