# Phase 7 Trial Registry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a deterministic, immutable research trial registry that records dataset lineage, validation windows, backtest evidence, and promotion evidence without installing or promoting models.

**Architecture:** `research.registry.models` owns strict immutable `TrialRecord` validation and JSON-safe canonical serialization. `research.registry.store` provides an in-memory registry with optional atomic JSON persistence, idempotent same-record registration, and fail-closed conflict handling. Promotion claims are accepted only when the supplied evidence independently satisfies the existing offline promotion gates.

**Tech Stack:** Python standard library, frozen/slotted dataclasses, `Decimal`, UTC datetimes, JSON, pytest.

---

### Task 1: Write the failing registry contract tests

**Files:**
- Create: `tests/research/test_trial_registry.py`

**Step 1: Write tests**

Cover immutable records, deterministic serialization, strict IDs/SHA-256/UTC validation, positive metrics, same-ID idempotency, conflicting identity rejection, optional disk persistence, and fail-closed deployment-approval evidence.

**Step 2: Run focused tests**

Run: `PYTHONPATH=. venv/bin/pytest -q tests/research/test_trial_registry.py`

Expected: collection or assertion failures because the registry package does not yet exist.

### Task 2: Implement immutable trial records

**Files:**
- Create: `trading_platform/research/registry/__init__.py`
- Create: `trading_platform/research/registry/models.py`

**Step 1: Implement validation**

Use frozen/slotted dataclasses, `require_utc`, SHA-256 validation, immutable mapping proxies, and `PurgedWindow` tuples. Convert nested reports/evidence into deterministic JSON-safe records and reject unsupported values.

**Step 2: Implement round-trip serialization**

Provide `to_record`, `from_record`, and `to_json` with a stable schema version, sorted keys, and compact separators.

**Step 3: Run focused tests**

Run: `PYTHONPATH=. venv/bin/pytest -q tests/research/test_trial_registry.py`

Expected: model tests pass; store tests remain failing until Task 3.

### Task 3: Implement idempotent registry storage

**Files:**
- Create: `trading_platform/research/registry/store.py`
- Modify: `trading_platform/research/registry/__init__.py`

**Step 1: Implement registration**

Register by trial ID, return `False` for an identical existing record, and raise `ValueError` for an identity conflict. List records in trial-ID order.

**Step 2: Add optional atomic JSON persistence**

Load and validate a `trial_registry_v1` document at startup and atomically replace the target file after successful registration. Do not expose installation or promotion side effects.

**Step 3: Run focused tests**

Run: `PYTHONPATH=. venv/bin/pytest -q tests/research/test_trial_registry.py`

Expected: all registry tests pass.

### Task 4: Update blueprint status and verify the repository

**Files:**
- Modify: `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

**Step 1: Record Phase 7 progress**

Mark the trial-registry portion complete while retaining live-training parity and remaining research work as pending.

**Step 2: Run full verification**

Run: `venv/bin/python -m compileall -q trading_platform tests`

Run: `PYTHONPATH=. venv/bin/pytest -q`

Expected: compileall succeeds and the complete suite passes with only the configured PostgreSQL skip.
