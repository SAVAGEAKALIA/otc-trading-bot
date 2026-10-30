# Trading Platform Root Convergence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use workflow-patterns to execute this plan task-by-task.

**Goal:** Make `src/trading_platform` the canonical owner of APIs, market data, strategies, execution, research, and operator interfaces while retaining temporary legacy import compatibility.

**Architecture:** Implementations move inward to the platform package. Legacy `iqoption_bot` and repository-root modules may only re-export platform-owned symbols or host the shrinking runtime composition shell. Architecture tests prevent platform-to-legacy imports.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy, pytest.

---

### Task 1: Move market-data ownership

Move the candle types, completed-candle logic, and provider to `trading_platform.market_data.provider`; replace `iqoption_bot.data_provider` with a re-export shim; verify symbol identity and existing cache tests.

### Task 2: Move OTC strategy ownership

Move base contracts and deterministic/ML strategies to `trading_platform.strategies.otc.implementations`; import platform market-data and research modules; replace legacy strategy modules with re-export shims.

### Task 3: Move API composition ownership

Introduce platform runtime API ports/facades and progressively reduce `APIWorker` to a compatibility composition adapter.

### Task 4: Enforce convergence

Add architecture/import-identity tests, run the complete suite, and update the main blueprint migration status.
