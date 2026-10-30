# Gap closure: second-pass ecosystem review

Research date: 2026-10-30. This pass covers ecosystems the first pass did not:
- crypto AI-agent frameworks
- candle/time-series foundation models
- financial LLMs
- trading MCP servers
- dedicated funding-arbitrage and market-making simulators
- the Hummingbot control plane

Method:
- Static reading of README/docs at the exact commits pinned below. Nothing was
  installed or executed, and no model was downloaded or run.
- Licence files are pinned in [licence_pins.md](licence_pins.md). The funding-arb template has no licence file at its commit.
- Metadata (stars, latest default-branch commit, licence signal) comes from
  `github_snapshot.json`, recollected at 2026-10-30T19:18:51Z with an
  authenticated token and retries.
- An earlier anonymous run that afternoon was rate-limited and overwrote the
  first snapshot with error rows. That copy was untracked and cannot be
  recovered. The collector now refuses to replace an existing snapshot after
  any fetch error, and a regression test covers this.

| Repository | Stars | Latest commit | Licence | What it actually is (from pinned source) | Authority / risk observed | Decision |
|---|---:|---|---|---|---|---|
| [shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos) | 44,122 | 2026-04-13 | MIT | Decoder-only foundation model for OHLCV "K-lines". It has a hierarchical tokenizer and is pre-trained on data from 45+ exchanges. Kronos-mini (4.1M), -small (24.7M) and -base (102.3M) are open weights; -large (499M) is not. AAAI 2026; [arXiv 2508.02739](https://arxiv.org/abs/2508.02739). | Forecasting only, with no execution. Its own finetuning example (A-shares, Qlib) carries a disclaimer: "not a production-ready quantitative trading system". The BTC/USDT 24h demo is a visualization, not a performance record. | **Defer: candidate for one pre-registered forecasting trial in R2.** Zero-shot Kronos-small vs naive and the fixed trend baseline on BTC/ETH daily direction, judged by the same frozen gate. Our OTC work found candle prediction at ln 2. Crypto majors are a different market, but the prior is skeptical. |
| [amazon-science/chronos-forecasting](https://github.com/amazon-science/chronos-forecasting) | 6,211 | 2026-10-05 | Apache-2.0 | General zero-shot time-series foundation models. Chronos-2 (Oct 2025) adds multivariate and covariate support and reports state-of-the-art results on fev-bench / GIFT-Eval. | Benchmarks are generic forecasting suites, not trading P&L | **Defer: comparator only.** If the Kronos trial is registered, Chronos-2 is the generic control model. Otherwise skip it. |
| [google-research/timesfm](https://github.com/google-research/timesfm) | 34,839 | 2026-09-29 | Apache-2.0 | TimesFM zero-shot forecasting with covariates | Same as Chronos | **Reject for R2** (one generic control is enough; adding it inflates the trial count) |
| [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 21,492 | 2026-10-25 | MIT | Financial LLM fine-tunes: sentiment, instruction benchmarks, and FinGPT-Forecaster trained on DOW-30 US equities. Most releases are from 2023. | Equity/news sentiment; would need a hosted or local LLM path that differs from the local Claude Code rule | **Reject for this mandate.** News sentiment is not part of the funding/basis mechanism. |
| [elizaOS/eliza](https://github.com/elizaOS/eliza) | 19,736 | 2026-10-30 | MIT | General agent runtime with a plugin system. Its README lists non-custodial EVM and Solana wallet operations "with approval boundaries". | The agent can hold wallet authority through plugins, which is the opposite of our "agent has no trading keys" rule | **Reject as trading authority and as agent runtime.** It duplicates the local Claude research role and adds a wallet-signing surface. |
| [kukapay/freqtrade-mcp](https://github.com/kukapay/freqtrade-mcp) | 148 | 2025-12-06 | MIT | MCP wrapper over the freqtrade REST API | Exposes `place_trade(pair, side, stake_amount)` and `delete_lock` alongside read tools. Using it would give the model order authority. | **Reject.** If an agent ever reads freqtrade state, use a read-only REST client we write, with no trade endpoints. |
| [doggybee/mcp-server-ccxt](https://github.com/doggybee/mcp-server-ccxt) | 145 | 2025-06-03 | MIT | MCP server over CCXT: public market data, plus private tools when keys are set | `place-market-order` and balance tools activate when exchange keys are in `.env` | **Reject for keyed use. Optional for public-only** market data in research, with no keys in its environment. |
| [50shadesofgwei/funding-rate-arbitrage](https://github.com/50shadesofgwei/funding-rate-arbitrage) | 184 | 2025-07-29 | none detected (README badge says MIT) | Delta-neutral perp-vs-perp template, DEX-DEX (GMX on Arbitrum, Synthetix v3 on Base), with a recommendation to add Bybit | Its README says it "has not yet been ran extensively in production" and recommends testnet first. It is a different structure from spot + perp. | **Reject**: stale, different mechanism, licence unclear |
| [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest) | 5,026 | 2025-12-23 | MIT | Market-making / HFT backtester with L2/L3 order-book replay, feed and order latency, and queue-position fill models. A Rust live bot exists for Binance Futures and Bybit. | Market making is excluded from the plan: Frankfurt latency, a small account, and adverse selection | **Defer**: the reference tool if market making is ever proposed. Not needed for carry or daily trend. |
| [hummingbot/hummingbot-api](https://github.com/hummingbot/hummingbot-api) | 152 | 2026-10-15 | MIT | Control plane for Hummingbot bots and accounts | `make deploy` starts API + PostgreSQL + EMQX containers. Credentials are encrypted with a config password, and Tailscale is suggested for remote access. | **Defer** (same as the first pass): only if Hummingbot becomes the executor |

## Findings that change the plan

1. **The agent gets no write-capable MCP servers.** Two publicly available "AI trading" MCP servers expose live order tools. This confirms the plan's rule as a concrete risk, not a hypothetical one.
2. **Foundation-model forecasting is the one genuinely new research family** since the OTC work. It is cheap to test with the Kaggle GPU account already used for the OTC runs. That account ran on 2 x Tesla T4 per [the direction-reset doc](../../plans/2026-10-30-direction-reset.md), section 1d. It must enter as a single pre-registered trial, counted in the multiple-testing budget. Weights and code must be pinned, and the run must be zero-shot, because tuning on viewed data recreates the OTC trap.
3. **No dedicated open-source spot + perp carry bot is mature enough to adopt.** The reviewed funding-arb repos are perp-perp or stale. Building the narrow two-leg executor on our ledger stands.

## Pinned sources

| Repository | Commit | File | SHA256 |
|---|---|---|---|
| elizaOS/eliza | `215e23ca5a26` | [README.md](https://raw.githubusercontent.com/elizaOS/eliza/215e23ca5a2604997fc9eb6c63fdd67bdd0c6644/README.md) | `ca09ada9f5741e19…` |
| shiyu-coder/Kronos | `67b630e67f6a` | [README.md](https://raw.githubusercontent.com/shiyu-coder/Kronos/67b630e67f6a18c9e9be918d9b4337c960db1e9a/README.md) | `b815b608192afa4b…` |
| AI4Finance-Foundation/FinGPT | `ac5c5443fbee` | [README.md](https://raw.githubusercontent.com/AI4Finance-Foundation/FinGPT/ac5c5443fbeeafad801e7a3c188e4f24cfaad4d8/README.md) | `8f2b9963d39c4a6e…` |
| amazon-science/chronos-forecasting | `1224fafa91e1` | [README.md](https://raw.githubusercontent.com/amazon-science/chronos-forecasting/1224fafa91e1ecd6674f5204066b159e40b5e4a1/README.md) | `7f9e55723daadb20…` |
| google-research/timesfm | `e51928e27119` | [README.md](https://raw.githubusercontent.com/google-research/timesfm/e51928e27119cb17bebc005be2696b75e0a9e688/README.md) | `4312675e2c65ce10…` |
| nkaz001/hftbacktest | `5f3ec40b2afb` | [README.rst](https://raw.githubusercontent.com/nkaz001/hftbacktest/5f3ec40b2afb764e0fea112f941ed85523ef4e88/README.rst) | `b42c9f012bd71d2e…` |
| kukapay/freqtrade-mcp | `6762093f9a29` | [README.md](https://raw.githubusercontent.com/kukapay/freqtrade-mcp/6762093f9a294f770c886edcc1eda1c5a5ddeaf8/README.md) | `d5a65a1917ed00e0…` |
| doggybee/mcp-server-ccxt | `b0b532334a3f` | [README.md](https://raw.githubusercontent.com/doggybee/mcp-server-ccxt/b0b532334a3f37f47d40c439aee505d8853ae3e8/README.md) | `79d6cfe3634a0d81…` |
| 50shadesofgwei/funding-rate-arbitrage | `5adff2585283` | [README.md](https://raw.githubusercontent.com/50shadesofgwei/funding-rate-arbitrage/5adff2585283d27154cff25151b707c5fb16e48a/README.md) | `fe797cc6be5af081…` |
| hummingbot/hummingbot-api | `7ae108f11bf2` | [README.md](https://raw.githubusercontent.com/hummingbot/hummingbot-api/7ae108f11bf20651682dbdff639a8717068c5883/README.md) | `e62338e48cabeace…` |
