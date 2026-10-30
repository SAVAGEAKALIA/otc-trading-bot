# Phase 8 Bybit Private HTTP Transport Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a bounded, allowlisted HTTP executor for already-signed Bybit private-read requests without adding credential loading or order-write capability.

**Architecture:** Reuse the existing raw response and transient status contracts. `BybitPrivateHttpTransport` accepts only `SignedPrivateReadRequest` objects whose official host, path, and parameters match the private-read allowlist. An injected backend enables deterministic tests; the requests backend denies redirects, streams bounded responses, and translates connection failures.

**Tech Stack:** Python standard library, existing `requests` dependency, asyncio worker thread, pytest.

---

### Task 1: Write failing security/transport tests

**Files:** Create `tests/unit/brokers/test_bybit_private_http_transport.py`

Cover exact official host/path acceptance, tampered host/path/parameters rejection, signed headers forwarding without secret exposure, redirect denial, response-size/content-type/status/API retry behavior, and bounded retry delays.

### Task 2: Implement the private HTTP transport

**Files:** Create `trading_platform/brokers/bybit/private_http_transport.py`; modify `trading_platform/brokers/bybit/__init__.py`

Implement injected and requests-backed transports with strict request identity checks, bounded response reads, JSON envelope validation, and transient/10006 retries.

### Task 3: Update blueprint and verify

**Files:** Modify `docs/plans/2026-08-18-multi-market-agentic-trading-platform-blueprint.md`

Record production-shaped private transport completion while retaining live credentials, endpoint smoke tests, and WebSocket deployment evidence as pending. Run compileall and full pytest.
