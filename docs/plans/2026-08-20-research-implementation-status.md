# Research-to-Implementation Status

The blueprint's external projects, papers, and videos are evidence sources and design inputs. They are not treated as copied production dependencies. The current implementation status is:

| Research input | Adopted implementation | Status |
|---|---|---|
| LangGraph persistence/interrupts | Reserved for durable research and incident workflows outside execution authority | Phase 11 pending |
| Hermes Agent | Replaceable OpenAI-compatible reasoning provider with no broker authority | Phase 12 pending |
| NautilusTrader/Lean/Freqtrade/Hummingbot | Patterns informed adapter, simulator, reconciliation, and event-ledger boundaries; no wholesale engine import | Deliberately deferred |
| VectorBT/backtesting systems | Causal event-driven backtester, Decimal cost model, purged windows, metrics, and trial registry | Foundational slice implemented |
| TradingAgents/FinRobot/agentic trading examples | Permission model and deterministic approval boundaries informed the design | Agent workflows pending |
| Quantitative literature on overfitting | Purged walk-forward validation, immutable manifests, untouched-test evidence, promotion gates, and registry lineage | Foundational controls implemented; multiple-testing adjustment pending |
| Strategy research | Existing OTC strategies preserved under `trading_platform/strategies/otc`; no crypto strategy claims made | Phase 10 pending |
| Videos and talks | Used only as supplementary architecture context; no implementation claim is based on video-only evidence | No direct code dependency |

No external project, publication, video, model, or hosted agent is treated as proof of profitability or exchange compatibility. Live/testnet acceptance remains an empirical gate requiring recorded fixtures, fault injection, and reconciliation evidence.
