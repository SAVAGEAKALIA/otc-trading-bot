# Phase 9 Bybit Execution Controls Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden the injected Bybit testnet execution gateway against timeout ambiguity for cancel/amend operations and provide an explicit validated reduce-only protective-exit request.

**Architecture:** Reuse the gateway's exact client-ID recovery path for every mutating operation. A protective exit is a deterministic MARKET trigger request with `reduceOnly`, `closeOnTrigger`, explicit trigger direction, and optional hedge `positionIdx`; it cannot increase exposure or use live environments.

**Tech Stack:** Python standard library, asyncio protocols, `Decimal`, existing Bybit testnet gateway, pytest.

---

### Task 1: Write failing execution-control tests

**Files:** Modify `tests/unit/brokers/test_bybit_execution.py`

Cover cancel/amend timeout recovery, invalid protective-exit identities/values, correct opposite-side trigger payloads, and client-ID idempotency.

### Task 2: Implement execution controls

**Files:** Modify `trading_platform/brokers/bybit/execution.py`

Recover mutation timeouts by exact client ID before retrying. Add `submit_protective_exit` with strict linear/quantity/trigger/position-index validation and broker snapshot normalization.

### Task 3: Update blueprint and verify

**Files:** Modify `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

Record the controls as implemented while retaining live signed-write and testnet acceptance gates. Run compileall and full pytest.
