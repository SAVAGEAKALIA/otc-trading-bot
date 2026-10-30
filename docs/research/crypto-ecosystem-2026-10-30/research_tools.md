# Additional tool source inspection

2026-10-30. Static README/license and selected documentation inspection only. No third-party package was installed or executed. Source blobs were fetched at exact git HEAD SHAs; the URLs below remain reproducible independently of temporary local copies.

| Repository | Pinned files inspected | SHA256 of downloaded content |
|---|---|---|
| polakowo/vectorbt | [README.md](https://raw.githubusercontent.com/polakowo/vectorbt/70da8fe7c2a57948ca065ac362fc416bcf31458c/README.md) | `f28357c134eaf63bcb32c5f67cb66553ecfba9663a8d0b27c016057828bccecf` |
| polakowo/vectorbt | [LICENSE.md](https://raw.githubusercontent.com/polakowo/vectorbt/70da8fe7c2a57948ca065ac362fc416bcf31458c/LICENSE.md) | `a914859a115b70e80956a3cbd613139ad74c04e5d1bd38da8bcc16725822ec84` |
| kernc/backtesting.py | [README.md](https://raw.githubusercontent.com/kernc/backtesting.py/ca2e2611621e472542ba90f7243a1fa06a7d7108/README.md) | `849a6a8ee692f47dee16bdf72bf37eb23e2a2358fed722aae077ff9014ffa304` |
| kernc/backtesting.py | [LICENSE.md](https://raw.githubusercontent.com/kernc/backtesting.py/ca2e2611621e472542ba90f7243a1fa06a7d7108/LICENSE.md) | `ad858d53cae05eed9531ecd4c467440803acffe34c69de7b88e03affc5b6a1bd` |
| OpenBB-finance/OpenBB | [README.md](https://raw.githubusercontent.com/OpenBB-finance/OpenBB/7df7d0c5592bf25be88e87e130a05c71e243d2d8/README.md) | `e16d366a7c2db035918231b9a6051c2a203f8e9991ab7853005218e8549bdaba` |
| OpenBB-finance/OpenBB | [LICENSE](https://raw.githubusercontent.com/OpenBB-finance/OpenBB/7df7d0c5592bf25be88e87e130a05c71e243d2d8/LICENSE) | `2c40e795cd5d3179d45c57b534e953e3fa2f1fb499602e2b314f57aeec813885` |
| QuantConnect/Lean | [readme.md](https://raw.githubusercontent.com/QuantConnect/Lean/6f30bf4995deeb5d8a9189e304dbf00bd246e37f/readme.md) | `c93d2d649740ffdbfeca35ee5035eff668dc1f0a6b97873756addb70f4f4b91e` |
| QuantConnect/Lean | [LICENSE](https://raw.githubusercontent.com/QuantConnect/Lean/6f30bf4995deeb5d8a9189e304dbf00bd246e37f/LICENSE) | `522cf0a716ce03f67d46f8fceb5bf78c5b84400ec5cd8d14bf9f02cddc1cb6ba` |
| Lumiwealth/lumibot | [README.md](https://raw.githubusercontent.com/Lumiwealth/lumibot/a5f0ee6d80e22d81f491611535b9eff6408fe159/README.md) | `1006eca7f2a9d59c8ebe747ff16063369da131303a9be2f31271c80e9e1b068e` |
| Lumiwealth/lumibot | [LICENSE](https://raw.githubusercontent.com/Lumiwealth/lumibot/a5f0ee6d80e22d81f491611535b9eff6408fe159/LICENSE) | `7d8846232c63c8d5c00a0a4d412df1c69c4339a54e59157164c0916ec0eff24d` |
| Lumiwealth/lumibot | [AI_TRADING_AGENTS.md](https://raw.githubusercontent.com/Lumiwealth/lumibot/a5f0ee6d80e22d81f491611535b9eff6408fe159/docs/AI_TRADING_AGENTS.md) | `31c23bb8484822fd0e8d8885a57c6446a1bb491d85dc6ca448efb0f1f50f6331` |
| CryptoSignal/Crypto-Signal | [README.md](https://raw.githubusercontent.com/CryptoSignal/Crypto-Signal/7cb9c5c6cd226c6fe2d345e4bda3bec8156cefec/README.md) | `069e4fcaab370ad7470e6fdae9bc149cfd5e8a45e1bf5511143e939ce3bbcc8c` |
| CryptoSignal/Crypto-Signal | [LICENSE](https://raw.githubusercontent.com/CryptoSignal/Crypto-Signal/7cb9c5c6cd226c6fe2d345e4bda3bec8156cefec/LICENSE) | `c27ec5a18701fbcf269aa254e1db1df1e127398cc80668d76998f97b02e79aee` |
| Superalgos/Superalgos | [README.md](https://raw.githubusercontent.com/Superalgos/Superalgos/9f0fb59edd4bae7afa08d06c366e0bcb48103aec/README.md) | `ad97787c63595aecd8330a81c0c59d04f393fe5dae3d7dbc3a01e4469e329a1f` |
| Superalgos/Superalgos | [LICENSE](https://raw.githubusercontent.com/Superalgos/Superalgos/9f0fb59edd4bae7afa08d06c366e0bcb48103aec/LICENSE) | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |

## Decisions

**OpenBB: defer as a data integration option, not a trading engine.** Its current README describes normalized data access for Python, REST, MCP and research applications. Useful if we need several macro/news/fundamental providers; excessive for two exchange funding streams. Provider entitlements, point-in-time availability and data fees remain separate from the software license. The pinned current LICENSE says Apache-2.0 even though GitHub metadata returns NOASSERTION; older V4 AGPL documentation is not the current source license. The GitHub repository redirects to `openbq-org/OpenBB`; preserve both requested and resolved names. No universal “all data free” or execution capability is inferred.

**vectorbt: defer, optional fast screening only.** Useful for vectorized parameter experiments and comparing simple signals. It does not remove the need for settlement, collateral and paired-position accounting. Many trials make selection bias worse unless registered. The pinned license is Apache-2.0 with Commons Clause, not plain Apache-2.0; product/service redistribution needs an exact license review. Do not add it solely to avoid writing the small carry accounting logic already required by our contract.

**backtesting.py: defer; optional independent simple-strategy cross-check only, not the carry ledger.** The README demonstrates OHLC strategy evaluation with commissions, optimization and trade reports. Good for checking a fixed long/flat trend example. That example is not proof of exchange-specific multi-leg funding or margin handling. AGPL-3.0 is relevant if modifying or serving it; keep the chosen use and distribution model explicit.

**QuantConnect LEAN: defer, serious whole-engine alternative.** The source describes an event-driven modular engine with backtest/live support. Apache-2.0 core and Python/C# interfaces make it a legitimate candidate, not something to dismiss as closed cloud software. Our assessment: changing the existing Python execution model plus data and brokerage integrations costs more than the current two-symbol programme needs. A broad multi-asset mandate could reverse the decision. Exact Nigerian broker access and any CLI/cloud/data fees must be checked separately from the core license.

**LumiBot: defer; borrow evaluation ideas.** Its AI-agent guide documents strategy-clock context, FRED/ALFRED vintage-aware tools and cached decisions. It also places model calls and order tools inside the strategy lifecycle, with a paid-provider example and separate broker setup. The guide explicitly distinguishes source-branch examples from published packages and says fresh real-model proof for its new example is pending. Good model-evaluation patterns; not a demonstrated profitable crypto carry engine or an established local Claude CLI integration. Prefer deterministic trade authority for this project. GPL-3.0 metadata applies to the inspected core.

**CryptoSignal: reject as an operational dependency; historical reference only.** It is primarily technical-indicator scanning and alerts, despite the trading-bot name. The default-branch commit in the API snapshot is August 2022 and its README lists old integrations. This is evidence of old default-branch maintenance, not proof that every fork or related project is abandoned. Porting an alert pattern is cheaper than adopting this stack; an RSI alert is not validated alpha.

**Superalgos: defer.** Its visual strategy, data-mining, backtest/paper and multi-server workflow is real documented scope, under Apache-2.0. That breadth suits users who want the visual platform; it adds another execution/data model for our service-based repository. The default-branch commit snapshot is May 2026, distinct from possible newer pushes to other branches. No runtime benchmark or claim that it is inherently unsafe is made.

## User feedback triangulation

The execution and AI reports link primary user issue reports and maintainer responses, which are stronger evidence for concrete defects than promotional comparison posts. As an additional first-person data-access check, the [OpenBB community licensing discussion](https://www.reddit.com/r/openBB/comments/1egu0mr/) describes provider redistribution limits and separate subscriber licenses. It is anecdotal and older than the current source version; use it as a question to verify against current provider contracts, not as a current price or license ruling. No user profit screenshot, affiliate ranking or undisclosed promotional claim is counted as performance proof.

## What this review did not test

No install, dependency resolution, replay benchmark, credential flow, actual broker order or load measurement was performed for these tools. Recommendations are selection decisions for a bounded implementation spike. Before adoption: pin the release and dependencies, inspect its exact license and provider terms, prove the same event fixture produces the expected accounting, and test all permitted capabilities without trading credentials.
