# Phase 8 Private Stream Envelope Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Validate Bybit private WebSocket envelopes and connect their sequence state to normalized order/execution dispatch without implementing a network WebSocket client.

**Architecture:** Add an immutable envelope normalizer that validates topic, message type, non-empty data, creation timestamp, and optional sequence fields. Add a small dispatcher that requires a healthy subscribed lifecycle, rejects sequence gaps before normalization, and routes order/execution payloads through the existing OMS snapshot normalizer.

**Tech Stack:** Python standard library, frozen dataclasses, UTC datetimes, pytest.

---

### Task 1: Write failing envelope/dispatcher tests

**Files:** Create `tests/unit/brokers/test_bybit_private_dispatch.py`

Cover valid snapshot/delta envelopes, malformed timestamps/topics/data, sequence gaps, lifecycle reconnect requirements, and order/execution dispatch.

### Task 2: Implement offline envelope and dispatcher

**Files:** Create `trading_platform/brokers/bybit/private_dispatch.py`; modify `trading_platform/brokers/bybit/__init__.py`

Keep all network behavior injected or absent. Validate before handing payloads to existing normalizers, and preserve the lifecycle's fail-closed health state.

### Task 3: Update blueprint and verify

**Files:** Modify `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

Record the completed envelope/dispatch slice, then run compileall and full pytest.
