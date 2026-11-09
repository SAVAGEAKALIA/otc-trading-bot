# Fresh OTC Collection Implementation Plan

**Goal:** collect true continuous receiver-clock quotes and run the fixed logistic regression/CatBoost comparison only after a frozen seven-day development cohort passes source admission.

**Architecture:** `services/otc_collector/` owns read-only broker transport, append-only receipts, immutable registration, clock/connection health and monitoring. `contracts/otc_v1/` defines the fresh schedule boundary. `services/otc_research/` exports all fixed-grid opportunities and passes immutable chronology through fitting and inference parity. The existing historical source loader and its August cutoff stay fixed.

**Tech Stack:** Python stdlib SQLite/Decimal/threading/queue plus requests, websocket-client and the pinned sklearn/CatBoost stack already used by this project.

## References and measurable outcome

Recorder frozen criteria: `/tmp/binary-training/critique/fresh-collector-reference.md`. Fresh comparison integration criteria: `/tmp/binary-training/critique/fresh-comparison-reference.md`. Competing builders use isolated A/B directories and an independent attacker selects the artifact. Each final unit needs cold PASS before account connection.

Before writing the adapter, archived wire handlers in tag `otc-binary-final-2026-10-30` were inspected. GitHub candidates were checked: `Lu-Yi-Hsun/iqoptionapi` (391 stars, last pushed 1 July 2026) and `iqoptionapi/iqoptionapi` (275 stars, last pushed 12 August 2024). The standard requests/websocket-client transport wins: this observer needs a small allowlist and direct callbacks; restoring the full unofficial trading SDK would add unused order/account methods and cached state. This records the reason for the narrow domain adapter.

1. Write failure-first tests for true incoming quote receipts, finite midpoint/asset/product validation, privacy filtering, duplicate/conflicting identity, clock jumps, reconnect/restart, bounded queue overflow and storage error. Build the two recorder variants independently.
2. Build append-only store and receipt metadata, register a seven-day UTC interval before connection, freeze collector/research hashes, and prove a dry run cannot connect. Periods are training three days, early stopping one, calibration one, policy one and diagnostic one. They never move to follow resolved labels.
3. Derive per-asset gap/coverage, percent, rate and ETA from persisted receipt state. Print and append progress under the dedicated `/tmp/` run directory. Stop at the fixed end; keep failures and missing periods.
4. Cold tournament the variants against the archived wire semantics and frozen rubric. Repair concrete defects and obtain a fresh critic PASS.
5. Add fresh source export and immutable schedule support without changing historical admission. Compete integration variants, test shifted replay, strict registration/source hashes, exact grid and purge boundaries, diagnostic-label rotation and saved-model parity. Validate the minimal private Kaggle package in an isolated process.
6. Copy source/tests/evals/docs to the isolated worktree. Run hooks, source/secret/binary audit, inspect the final diff, rate against the references, commit and push a dedicated `codex/` branch.
7. Prepare the exact register/start/monitor/stop commands. The repository AGENTS instructions require confirmation before production/account actions; present the concrete read-only account connection after the implementation is reviewable. No connection, order, balance change or production restart is part of the offline build.
8. After confirmation, register a future UTC grid start and launch only the read-only recorder. Run health monitoring. Once the registered interval ends, snapshot/export/admit, compare locally and reproduce privately on Kaggle only if admission passes. Source failure produces a preserved blocked result rather than a rescheduled or relaxed comparison.

The fresh comparison is exploratory development evidence. It does not supply accepted strikes, binding expiry/settlement terms or an untouched profitability confirmation. No trading service needs restarting for the offline source change.
