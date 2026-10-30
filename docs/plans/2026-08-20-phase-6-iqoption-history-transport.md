# Phase 6 IQ Option History Transport Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a bounded, paginated, replay-safe IQ Option closed-option history port for authoritative binary settlement lookup without using process-local polling helpers.

**Architecture:** Keep the vendored websocket client behind `trading_platform.brokers.iqoption`. The new adapter will call the blocking history API in a worker thread with a hard timeout, normalize the vendor response envelope into records, paginate with duplicate/cursor guards, and implement the existing `IQOptionClosedOptionsPort`. It will remain read-only and will not be connected to live order submission or mutate legacy result behavior.

**Tech Stack:** Python 3.12, asyncio, standard-library protocols/dataclasses, pytest/pytest-asyncio.

---

### Task 1: Define transport behavior with failing contract tests

**Files:**
- Create: `tests/contract/test_iqoption_history_transport.py`
- Modify: `trading_platform/brokers/iqoption/__init__.py`

**Steps:**
1. Add fake blocking APIs covering tuple/envelope response shapes, multi-page records, duplicate pages, timeout, malformed responses, and missing IDs.
2. Assert lookup returns the exact matching record, stops at the page bound, returns `None` for timeout/missing records, and never loops on a repeated page.
3. Run `PYTHONPATH=. venv/bin/pytest -q tests/contract/test_iqoption_history_transport.py`; expect import failure before implementation.

### Task 2: Implement the bounded history adapter

**Files:**
- Create: `trading_platform/brokers/iqoption/history.py`
- Modify: `trading_platform/brokers/iqoption/__init__.py`

**Steps:**
1. Implement `IQOptionHistoryAPI` protocol and `IQOptionClosedOptionsHistory` with configurable timeout, page size, maximum pages, and instrument types.
2. Execute `get_position_history_v2` through `asyncio.to_thread` plus `asyncio.wait_for`.
3. Unwrap successful vendor envelopes, extract only mapping records from supported history containers, normalize order IDs, and reject malformed success payloads without guessing.
4. Paginate by offset, stop on short/empty pages, repeated record fingerprints, repeated payload fingerprints, or page limit.
5. Return `None` on timeout, connection failure, unsuccessful vendor status, or no match; never call `check_win`, `check_win_v4`, or balance APIs.
6. Run the focused contract tests and make them pass.

### Task 3: Preserve the public broker boundary and document the Phase 6 gate

**Files:**
- Modify: `trading_platform/brokers/iqoption/__init__.py`
- Modify: `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

**Steps:**
1. Export the new protocol/adapter from the broker package.
2. Update Phase 6 status to record bounded history transport completion while keeping supervised practice transport and realtime parity as pending.
3. Run compileall and the complete pytest suite.

### Verification

```bash
venv/bin/python -m compileall -q trading_platform tests
PYTHONPATH=. venv/bin/pytest -q
```

Expected: all current tests pass; PostgreSQL integration may remain skipped without `TEST_POSTGRES_URL`.
