# Phase 9 Bybit Timeout Recovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent blind duplicate Bybit testnet submissions when the create-order request times out after the exchange accepted the order.

**Architecture:** Extend the injected execution gateway with a recovery lookup by `orderLinkId` after a connection/timeout failure. If private order truth confirms the client ID, return that broker snapshot immediately; only retry create-order when no broker confirmation exists. The gateway remains testnet-only and exposes no live credential or transport behavior.

**Tech Stack:** Python asyncio protocols, existing private-read reader/order normalizer, pytest.

---

### Task 1: Write failing timeout-after-accept tests

**Files:** Modify `tests/unit/brokers/test_bybit_execution.py`

Cover accepted-after-timeout recovery, no-confirmation retry, and recovery identity mismatch.

### Task 2: Implement recovery before retry

**Files:** Modify `trading_platform/brokers/bybit/execution.py`

Query the injected private reader with the exact `orderLinkId` before replaying a timed-out create request. Return confirmed status/executions and preserve existing bounded retries.

### Task 3: Update blueprint and verify

**Files:** Modify `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

Record timeout-after-accept protection as implemented while retaining live testnet acceptance as pending. Run compileall and full pytest.
