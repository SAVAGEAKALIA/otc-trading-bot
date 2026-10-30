# Crypto plan (DRAFT, awaiting approval)

Date: 2026-10-30. Status: **proposal**. Nothing in here is built until Saviour approves it.

## 0. The honest starting point

**What the research and our own data say:**

- **BTC/ETH carry (long spot, short perp, collect funding) used to pay well
  and now pays about the risk-free rate.** We pulled the funding history
  ourselves (`docs/research/crypto-evidence-2026-10-30/`):

  | Hedged notional, after fees, regime-gated | 2024 | 2025 | 2026 YTD |
  |---|---:|---:|---:|
  | Bybit BTC | 9.8% | 1.8% | 0.8% |
  | Bybit ETH | 11.3% | 1.0% | -0.1% |
  | Hyperliquid BTC | 23.3% | 9.7% | 3.5% |
  | Hyperliquid ETH | 20.0% | 6.6% | 3.9% |

  - Binance BTC funding fell from 30.6% gross (2021) to 1.1% in H1 2026, when
    38% of 8h prints were negative.
  - Borri et al. (arXiv 2510.14435) find carry's Sharpe turned negative in
    2025, as Ethena and the basis ETFs crowded the trade.
- **The regime gate is what makes carry survivable.** SOL always-on returned
  -36.3% in 2022 (FTX). Gated, it returned +1.2%.
- **Hyperliquid pays about twice what CEXs pay.** It also comes with
  venue-specific risk:
  - On 10 Oct 2025, ADL closed $2.1B in 12 minutes and left "hedged" traders
    holding naked spot.
  - In the March 2025 JELLY incident, validators delisted the market.
  - Spot BTC/ETH on Hyperliquid are bridged assets.
- **Simple trend following on daily bars** is the only directional family
  with decent net-of-cost evidence. Zarattini et al. 2025 report Sharpe about
  1.5 in backtest, net of 10-50 bp. That is a backtest, not live proof. Our
  OTC lesson says it must pass a frozen out-of-sample gate before anyone
  trusts it.
- **LLM agents must not trade.** In Alpha Arena S1, 4 of 6 frontier models
  lost 42-59% in about 2 weeks, mainly through overtrading and leverage. The
  pattern that holds up is RD-Agent style: the agent proposes, deterministic
  code tests, and a human approves.

**What this means:** there is no high-return machine here either. The
realistic target is a **small, durable, measurable yield above the
risk-free rate, with tails capped in code.** A research and agent loop
then hunts for better edges under the same frozen-rubric discipline that
killed the OTC idea.

## 1. Decisions needed before any build (Confusion Protocol)

| # | Decision | Why it matters | Options |
|---|---|---|---|
| D1 | **Country of residence (KYC)** | It decides the venue. No EU CEX offers true perps to retail: Bybit EU is spot only, Binance stopped EU derivatives in Jul 2026, and OKX EU offers 5-year "X-Perps". A Frankfurt VPS does not change this. | EU / Nigeria / Kenya / South Africa / Ghana / other |
| D2 | **Venue** | Yield vs counterparty risk | (a) Bybit global or Binance, if legal for you: lower yield, mature. (b) Hyperliquid: about 2x yield, no KYC, onchain, ADL/governance risk, legally your responsibility. (c) Both, with per-venue caps. |
| D3 | **Capital to commit**, and its alternative yield | Whether carry beats your USDC savings or T-bill rate | Amount, and the hurdle rate you could get risk-free |
| D4 | **VPS** | It has 1 GB RAM and runs an unrelated pm2 site. freqtrade wants about 2 GB. | Upgrade to a 2-4 GB paid shape, or run only the light executor |
| D5 | **Scope of directional trading** | Trend following adds return and drawdown | Carry only / carry plus a trend sleeve (≤ 20% of capital) after it passes the gate |

## 2. Strategy sleeves (each with a measurable outcome)

| Sleeve | What | Outcome metric | Promotion gate (frozen before testing) |
|---|---|---|---|
| **S1 Gated carry** (core) | Spot long + 1x perp short on BTC/ETH. Enter when trailing-7d funding > hurdle; exit when trailing-3d < 0. Optionally rotate across the top-N liquid perps that have a spot leg. | Net APR on capital vs D3's risk-free hurdle; max drawdown; time in market | Walk-forward on 2023-2026, out-of-sample 2025-26. Net APR on capital ≥ hurdle + 2%. Max drawdown < 3%. No single month < -1%. |
| **S2 Idle yield** | When S1 is out of the market, capital sits in the venue's USDC/USDT earn or is withdrawn to a risk-free alternative | Blended yield | Deterministic rule, no gate |
| **S3 Trend sleeve** (optional, D5) | Daily-bar Donchian ensemble on BTC/ETH (+ top liquid), volatility-sized, low turnover. Run in freqtrade. | Sharpe, max drawdown, correlation to S1 | freqtrade `lookahead-analysis` + `recursive-analysis` clean. Purged walk-forward, Sharpe > 1 out of sample net of real fees. Then 8 weeks dry-run within 1σ of backtest. |
| **S4 Research loop** | The agent proposes new hypotheses (cross-venue funding spreads, basis, new perps). The `edge_audit`-style frozen-rubric pipeline judges them. | Hypotheses tested per week; false-positive rate | Any winner goes to paper first, never straight to live |

## 3. Architecture (services-first, per CLAUDE.md)

```
contracts/            pydantic schemas: TradeProposal, PositionSnapshot, RiskLimits, FundingObs, AgentRun
services/
  market-data/        collectors: funding, mark/index, spot+perp klines, fee tiers     -> SQLite/Parquet
  carry-engine/       deterministic S1 signal: gate, rotation, sizing  -> TradeProposal
  executor/           ccxt (async + websocket) two-leg executor: sliced legs, leg-repair, reconciliation
  risk/               hard limits + persisted kill switch; every order passes check() here
  operator-bot/       python-telegram-bot: /status /pnl /kill /unkill, Approve/Reject buttons with TTL
  llm/                claude -p wrapper: --json-schema, read-only tools, budget cap, JSONL run log
  research/           backtests (S1 numpy, S3 freqtrade), walk-forward, frozen rubrics, edge reports
trading_platform/     shared library kept from today: domain models, ledger/outbox, risk engine, walk-forward
```

**Reuse vs build** (from the research):

| Need | Decision | Reason |
|---|---|---|
| Exchange access | **ccxt** (44.6k stars, weekly releases) | It replaces the custom `brokers/bybit/` (about 2.7k lines), which gets deleted once the ccxt adapter passes the same contract tests |
| Two-leg execution | **Build, about 500 lines** | No framework handles spot+perp leg risk. Hummingbot's script is perp-perp only, defaults to 20x, has open funding bugs, and needs 4 GB per instance. |
| Single-leg strategies (S3) | **freqtrade** (56k stars, monthly releases) | Dry-run, Telegram, bias checks included. Bybit funding history is missing in its backtests, which is fine for S3. |
| Telegram | **python-telegram-bot** | Freqtrade's Telegram module has no argument buttons, so the approval flow is ours |
| Agent | **`claude -p`** with flags checked against code.claude.com | `--output-format json --json-schema`, `--allowedTools` read-only, `--disallowedTools Edit,Write`, `--permission-mode dontAsk`, `--strict-mcp-config`, `--max-turns`, `--max-budget-usd`, `--no-session-persistence`. Scheduled by a systemd timer with flock. |
| Market data for the agent | CoinGecko official MCP (keyless) | The agent never holds trading keys |
| Rejected | nautilus_trader (v2 still at RC8), hummingbot (RAM, perp-perp, bugs), dedicated funding-arb repos (stale or under 200 stars), backtrader (dead) | |

**Deterministic vs agent:**

- **Code only:**
  - orders, sizing, limits, kill switch
  - reconciliation, fills (exchange-reported only)
  - funding accounting, tax records
- **Agent proposes only:**
  - research hypotheses
  - nightly journal
  - anomaly triage on `events.jsonl`
  - config-change proposals
  - code review of strategy diffs
- **Human approves:**
  - every proposal, via Telegram with a TTL and a daily quota
  - unkill
  - any limit change

## 4. Hard limits, encoded in `services/risk` (not in prompts)

1. Perp leverage ≤ 1.0x per leg (ceiling 1.5x).
2. Distance to liquidation ≥ 50%; below 35%, top up or reduce automatically.
3. Collateral is USDT/USDC only. A > 0.5% depeg on the venue switches to flatten-only.
4. Delta drift: |spot - perp| > 2% of notional for > 60 s triggers a re-hedge.
   Any position change we didn't order (ADL) triggers a halt and an alert.
5. Entry only when expected funding over 7 days > 2x the round-trip cost.
   Exit when trailing 3d < 0 or two settlements in a row < -0.01%.
6. Per-venue cap of 40% of equity (or 100% if D2 picks a single venue, accepting that risk explicitly).
7. Drawdown: -5% from peak halves positions; -10% flattens and requires a manual restart.
8. Basis guard: perp/spot gap > 1.5% for > 5 min freezes entries.
   Legs execute in slices of ≤ 10%, each confirmed before the next.
9. Keys: trade-only, no withdrawal, IP-whitelisted to the VPS. One subaccount per strategy. Secrets in a root-only env file.
10. Heartbeat: if silent for > 15 min, flatten. Daily off-box backup of the state DB.

## 5. Phases and gates

| Phase | Work | Exit gate (measurable) |
|---|---|---|
| **P0** | Answer D1-D5. Rotate the Kaggle token. | Decisions recorded in this doc |
| **P1 Research** (first build) | `services/market-data` collectors and history backfill for every perp with a spot leg on the chosen venue(s). `services/research` S1 backtester (fees, gate, rotation, capital multiplier) and S3 freqtrade setup. Frozen rubrics written before results. | S1 clears its gate, or we stop and report. A "stop" is a valid outcome. |
| **P2 Paper** | `executor` (ccxt), `risk`, `operator-bot`. Chaos tests: partial fills, disconnects, a simulated ADL, a depeg, a venue 5xx storm. Paper/testnet for 4 weeks. | 0 unreconciled positions. All chaos tests pass. Paper P&L within ±20% of simulated for the same period. |
| **P3 Agent** | `services/llm` and nightly jobs: journal, triage, hypothesis proposals. Telegram approvals. | 14 days of agent runs with valid schema output ≥ 99%, cost within budget, 0 unauthorized tool attempts in the hook logs |
| **P4 Small live** | Smallest meaningful capital on one venue. S1 only. | 8 weeks: realized net APR within 1σ of paper. 0 limit breaches without a handled response. |
| **P5 Scale or stop** | Add S3 if it passed its gate. Raise capital in steps. | Each step needs 4 weeks clean |

Every feature ships with gate tests (deterministic, < 2s) and a periodic eval,
as CLAUDE.md requires. Every unit goes through the fan-out builder/critic loop.

## 6. What gets deleted when

| When | What |
|---|---|
| End of P2, once the ccxt adapter passes the contract tests | `trading_platform/brokers/bybit/` (custom) and `brokers/weex/` |
| P2, if not reused | `trading_platform/brokers/simulated/`; the custom OMS pieces that duplicate the ccxt reconciliation loop |
| Now (already done) | The OTC binary bot, archived at tag `otc-binary-final-2026-10-30` |

## 7. Risks (top 5; full register in the research notes)

1. **Yield ≈ risk-free in the current regime.** Mitigation: the gate, plus idle capital in S2. Honest outcome: the system may mostly sit flat.
2. **Venue failure** (hack, insolvency, licence loss, withdrawal freeze), as with Bybit's $1.5B hack in Feb 2025 and Binance's EU exit in Jul 2026. Mitigation: per-venue cap, weekly profit sweep, always able to flatten.
3. **ADL or liquidation of the short leg** (10 Oct 2025). Mitigation: limits 1, 2 and 4, majors only, halt on unexpected position changes.
4. **Legal/jurisdiction** (D1). Using a venue not licensed for you, Hyperliquid included, is your legal risk.
5. **Ops on a 1 GB box** shared with another site; the Oracle free tier can reclaim idle VMs. Mitigation: D4, plus backups off the box.

## 8. Sources

- **Strategy evidence:**
  - BIS WP 1087 (bis.org/publ/work1087.htm)
  - Borri et al. arXiv 2510.14435
  - Zarattini et al. SFI RP 25-80
  - arXiv 2512.01112 (ADL)
  - zwmjj/funding-rate-arb
  - Arefev SSRN 7404139
  - our own `docs/research/crypto-evidence-2026-10-30/`
- **Frameworks:**
  - github.com/ccxt/ccxt
  - freqtrade.io (leverage, exchanges, lookahead-analysis)
  - hummingbot `scripts/v2_funding_rate_arb.py` and issues #8413 and #7591
  - nautilus_trader v2.0.0rc8 release notes
- **Venues and regulation:**
  - Hyperliquid docs (funding, fees, account modes)
  - Bybit funding docs
  - ESMA perps-as-CFD (Feb 2026)
  - Binance EU limits from Jul 2026
  - OKX X-Perps
  - Kenya VASP regulations 2026
- **Agents:**
  - code.claude.com CLI reference, headless, hooks and sandboxing docs
  - Hummingbot Condor MCP docs
  - RD-Agent arXiv 2505.15155
  - Alpha Arena S1 coverage (Forklog)
- **Unverified items:**
  - all YouTube content (fetches were blocked, so titles only)
  - HLP vault returns
  - Bybit EU MiFID timing
  - Binance futures latency spikes
  - whether the Claude subscription terms allow unattended scheduled `-p` runs

**Reachability, checked 2026-10-30 from the VPS:** Bybit, Binance spot and
futures, OKX and Hyperliquid public APIs all return 200, mostly in about
0.3 s; Binance futures took 5.4 s once.
