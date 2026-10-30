# Phase 8 Bybit Account Normalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize Bybit private wallet and open-order responses into immutable platform records and provide bounded, repeated-cursor-safe pagination over private reads.

**Architecture:** `brokers.bybit.account` contains adapter-owned wallet/open-order records and strict response normalizers. `BybitPrivateAccountClient` composes the existing capability-limited private reader, normalizes every page, and enforces category/account identity, page limits, duplicate identities, and cursor progress. No credential loading, model promotion, or live transport is added.

**Tech Stack:** Python standard library, frozen/slotted dataclasses, `Decimal`, UTC datetimes, pytest.

---

### Task 1: Write failing normalization and pagination tests

**Files:** Create `tests/unit/brokers/test_bybit_account.py`

Cover valid wallet/open-order records, exact Decimal preservation, malformed API/category/time/numeric responses, duplicate identities, successful pagination, repeated cursors, and page-limit exhaustion.

### Task 2: Implement strict account models and normalizers

**Files:** Create `trading_platform/brokers/bybit/account.py`

Implement immutable records, response envelope validation, UTC server timestamps, positive/non-negative numeric checks, and identity checks. Normalize only UNIFIED wallet and SPOT/LINEAR open orders.

### Task 3: Implement bounded private pagination coordinator

**Files:** Modify `trading_platform/brokers/bybit/account.py`, `trading_platform/brokers/bybit/__init__.py`

Compose the existing raw private reader, bound page count, reject repeated cursors and duplicate account/order identities, and return deterministic tuples.

### Task 4: Update blueprint and verify

**Files:** Modify `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

Record the completed normalization/pagination slice, then run compileall and the full suite.
