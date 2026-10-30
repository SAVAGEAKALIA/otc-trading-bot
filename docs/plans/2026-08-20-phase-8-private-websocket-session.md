# Phase 8 Bybit Private WebSocket Session Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an injected Bybit private WebSocket session that authenticates, subscribes, heartbeats, reconnects, and requires broker reconciliation before becoming submission-ready.

**Architecture:** A capability-limited session owns no concrete network library. Injected connector/socket protocols provide JSON send/receive and close operations. The session constructs canonical Bybit private-stream authentication, drives the existing lifecycle and dispatcher, marks submissions suspended on disconnect/gap/handshake failure, and permits readiness only after a supplied reconciler succeeds for the current connection generation.

**Tech Stack:** Python standard library, HMAC-SHA256, asyncio protocols, existing clock/lifecycle/dispatcher, pytest fakes.

---

### Task 1: Write failing session tests

**Files:** Create `tests/unit/brokers/test_bybit_private_websocket_session.py`

Cover canonical authentication, strict auth/subscription acknowledgements, required reconciliation, heartbeat, disconnect/reconnect/resubscribe, bounded connection retry, and sequence-gap suspension.

### Task 2: Implement injected private WebSocket session

**Files:** Create `trading_platform/brokers/bybit/private_websocket.py`; modify `trading_platform/brokers/bybit/__init__.py`

Expose no order-write methods and instantiate no live socket library. Validate official environment URLs, keep secrets out of records/repr, and fail closed whenever connection generation is not reconciled.

### Task 3: Update blueprint and verify

**Files:** Modify `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

Record the injected session completion while retaining real testnet connection and sustained evidence as external gates. Run compileall and full pytest.
