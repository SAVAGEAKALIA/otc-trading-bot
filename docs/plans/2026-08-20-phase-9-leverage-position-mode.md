# Phase 9 Bybit Leverage and Position Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Require verified Bybit linear leverage and position-mode state before injected testnet orders and protective exits are submitted.

**Architecture:** Add an injected read-only execution-controls protocol for current symbol leverage and position mode. Gateway configuration declares the expected mode and exact low validation leverage; the gateway rejects mismatches before any write backend call and maps hedge-mode entry sides to `positionIdx` 1/2 while preserving one-way mode as index 0.

**Tech Stack:** Python standard library, `Decimal`, asyncio protocols, existing Bybit testnet gateway, pytest.

---

### Task 1: Write failing control tests

**Files:** Modify `tests/unit/brokers/test_bybit_execution.py`

Cover matching controls, leverage mismatch, mode mismatch, hedge-side position-index mapping, and control failures before backend access.

### Task 2: Implement verified controls

**Files:** Modify `trading_platform/brokers/bybit/execution.py`

Add the injected control protocol and configuration fields, verify exact Decimal leverage and mode, and include `positionIdx` only after successful verification.

### Task 3: Update blueprint and verify

**Files:** Modify `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

Record leverage/position-mode verification as implemented while retaining signed write transport and authenticated testnet evidence as pending. Run compileall and full pytest.
