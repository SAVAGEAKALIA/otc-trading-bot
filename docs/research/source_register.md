# Research Source Register

## Evidence policy

Sources are ranked: official documentation, exchange documentation, peer-reviewed/established research, reputable engineering documentation, maintained open source, practitioner material, then videos/forums. A source can justify an architecture fact without proving profitability.

| ID | Category | Source | Use | Status |
|---|---|---|---|---|
| SRC-001 | Official | https://docs.langchain.com/oss/python/langgraph/overview | LangGraph scope and deterministic/agentic workflow mixing | Reviewed 2026-08-18 |
| SRC-002 | Official | https://docs.langchain.com/oss/python/langgraph/persistence | Durable workflow/checkpoint design | Pending implementation refresh |
| SRC-003 | Official | https://docs.langchain.com/oss/python/langgraph/interrupts | Approval and human-interrupt design | Pending implementation refresh |
| SRC-004 | Official project | https://github.com/NousResearch/hermes-agent | Hermes tools, memory, runtime and isolation capabilities | Reviewed 2026-08-18 |
| SRC-005 | Exchange | https://bybit-exchange.github.io/docs/v5/guide | Bybit authentication and environments | Reviewed 2026-08-18 |
| SRC-006 | Exchange | https://bybit-exchange.github.io/docs/v5/order/create-order | Asynchronous acknowledgement, client IDs, reduce-only and position index | Reviewed 2026-08-18 |
| SRC-007 | Exchange | https://bybit-exchange.github.io/docs/v5/ws/connect | Public/private/order WebSockets and reconnect expectations | Reviewed 2026-08-18 |
| SRC-008 | Exchange | https://bybit-exchange.github.io/docs/v5/rate-limit | Rate-limit architecture | Reviewed 2026-08-18 |
| SRC-009 | Exchange | https://bybit-exchange.github.io/docs/v5/demo | Demo/test environment limitations | Reviewed 2026-08-18 |
| SRC-010 | Exchange | https://www.weex.com/api-doc/contract/guide/introduction.html | WEEX integration entry point | Insufficient; due diligence open |
| SRC-011 | Official | https://www.postgresql.org/docs/current/ | Operational ledger and transactions | Pending implementation refresh |
| SRC-012 | Official | https://docs.python.org/3/library/asyncio.html | Async cancellation/concurrency semantics | Pending implementation refresh |
| SRC-013 | Official | https://opentelemetry.io/docs/ | Tracing/telemetry design | Pending implementation refresh |
| SRC-014 | Open source | https://github.com/nautechsystems/nautilus_trader | Event-driven domain/adapters/backtest-live parity patterns | Reviewed 2026-08-18 |
| SRC-015 | Open source | https://github.com/hummingbot/hummingbot | Connector and lifecycle-executor patterns | Reviewed 2026-08-18 |
| SRC-016 | Open source | https://github.com/freqtrade/freqtrade | Dry-run, backtesting and look-ahead-analysis patterns | Reviewed 2026-08-18 |
| SRC-017 | Open source | https://github.com/QuantConnect/Lean | Brokerage/event-engine patterns | Reviewed metadata 2026-08-18 |
| SRC-018 | Open source | https://github.com/ccxt/ccxt | Exchange normalization/prototyping | Reviewed metadata 2026-08-18 |
| SRC-019 | Open source | https://github.com/polakowo/vectorbt | Vectorized research/sensitivity testing | Reviewed 2026-08-18 |
| SRC-020 | Paper | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253 | Backtest overfitting | Accepted methodology source |
| SRC-021 | Paper | https://doi.org/10.1093/rfs/hhu105 | Multiple testing in expected-return research | Accepted methodology source |
| SRC-022 | Paper | https://doi.org/10.1111/1468-0262.00152 | Data-snooping reality check | Accepted methodology source |
| SRC-023 | Paper | https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf | Deflated Sharpe ratio | Accepted methodology source |
| SRC-024 | Paper | https://doi.org/10.1016/j.jfineco.2011.11.003 | Time-series momentum evidence | Hypothesis source only |
| SRC-025 | Paper | https://doi.org/10.1080/14697680701381228 | Inventory-aware market-making theory | Hypothesis/architecture source only |

## Source maintenance rules

- Record access date and relevant version before implementation decisions.
- Quote exchange semantics from current official pages in adapter ADRs.
- Mark inaccessible or ambiguous sources rather than inferring missing facts.
- Record every strategy paper/idea before running its experiment to preserve the trial universe.
- Videos may clarify demonstrations but cannot be the sole source for safety, API semantics or profitability.

