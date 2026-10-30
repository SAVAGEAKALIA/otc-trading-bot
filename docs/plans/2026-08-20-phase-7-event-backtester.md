# Phase 7 Event Backtester Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Establish the platform-owned event-driven backtesting and chronological-validation foundation required by Phase 7.

**Architecture:** Immutable market observations and binary signals are processed strictly by availability time. The engine derives entries only from data available at decision time, settles only from later available observations, applies explicit per-trade costs, and emits a deterministic JSON-safe report. Purged walk-forward windows are generated separately and reject overlaps or insufficient history.

**Tech Stack:** Python 3.12 standard library, Decimal, dataclasses, pytest.

---

### Task 1: Specify leakage-safe event simulation

**Files:**
- Create: `tests/research/test_event_backtester.py`
- Create: `tests/research/test_purged_walk_forward.py`

Write failing tests covering immutable input validation, availability-time ordering, CALL/PUT win/loss/tie cash flows, explicit costs, unresolved expiries, deterministic output, and purged non-overlapping windows.

### Task 2: Implement event backtest models, metrics, and engine

**Files:**
- Create: `trading_platform/research/backtests/__init__.py`
- Create: `trading_platform/research/backtests/models.py`
- Create: `trading_platform/research/backtests/engine.py`
- Create: `trading_platform/research/metrics/__init__.py`
- Create: `trading_platform/research/metrics/performance.py`

Implement strict UTC/Decimal validation, event-time processing, pending settlement, cost-aware P&L, equity/drawdown metrics, and JSON-safe deterministic reports.

### Task 3: Implement purged walk-forward validation

**Files:**
- Create: `trading_platform/research/validation/__init__.py`
- Create: `trading_platform/research/validation/walk_forward.py`

Generate chronological train/test windows with an explicit purge gap and reject impossible or overlapping configurations.

### Task 4: Verify and update blueprint status

**Files:**
- Modify: `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

Run focused tests, compileall, and the full suite. Record only the implemented Phase 7 foundation; dataset command/registry/live-training parity remain pending.
