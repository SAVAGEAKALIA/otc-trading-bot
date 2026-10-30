# Phase 8 Bybit Account Snapshot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Compose normalized Bybit private wallet and linear-position pages into the existing broker-authoritative `AccountSnapshot` contract.

**Architecture:** Extend the injected private account client with a snapshot method that retains page timestamps, maps wallet balances and known-leverage hedge legs into storage projections, and derives a stable SHA-256 snapshot ID from environment, timestamp, and exact Decimal records. Unknown leverage and invalid environment/catalog inputs fail closed before persistence.

**Tech Stack:** Python standard library, SHA-256, `Decimal`, UTC datetimes, existing storage projections, pytest.

---

### Task 1: Write failing account snapshot tests

**Files:** Modify `tests/unit/brokers/test_bybit_account.py`

Cover deterministic IDs, exact balance/position projection, server-time selection, environment identity, unknown-leverage rejection, and snapshot compatibility with `AccountReconciler`.

### Task 2: Implement account snapshot composition

**Files:** Modify `trading_platform/brokers/bybit/account.py`; modify `trading_platform/brokers/bybit/__init__.py`

Retain normalized page metadata internally, construct immutable storage projections, and expose only read/reconciliation methods.

### Task 3: Update blueprint and verify

**Files:** Modify `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

Record broker-authoritative snapshot composition as complete, then run compileall and full pytest.
