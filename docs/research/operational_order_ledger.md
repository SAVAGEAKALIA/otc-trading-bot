# Phase 5 Operational Order Ledger and Recovery Protocol

## Current implementation boundary

Phase 5 adds a transactional order ledger, lifecycle event log, execution table,
transactional outbox/publisher, crash-aware order manager, broker order
reconciler, broker-authoritative account/position projections, and local balance
reservations under `src/trading_platform`.

The legacy OTC runtime is not wired to this ledger yet. JSON trade history
therefore remains legacy reporting state until the Phase 6 vertical migration;
it must not be treated as the future authority.

## Submission protocol

1. Persist the complete immutable `OrderIntent`, `intent_recorded` event, and
   matching outbox message in one transaction.
2. Atomically compare-and-set `intent_recorded` to `submission_started`. Only
   the process that wins this claim may call the broker.
3. Submit using the unique client order ID.
4. Persist acknowledgement/rejection plus its event/outbox atomically.
5. Persist terminal fill state and deduplicated executions in the same
   transaction. A failed execution insert rolls the status/event/outbox back.

A repeated client ID with the exact same immutable intent is idempotent. The
same ID with a different signal, risk-decision ID, quantity, instrument, or
other authority is rejected.

## Restart and reconciliation protocol

| Local state | Broker query | Safe action |
|---|---|---|
| `intent_recorded` | none required | eligible for an explicit OMS resume/claim |
| `submission_started` | order found | adopt broker state; never resubmit |
| `submission_started` | not found/uncertain | mark `unknown`; never blindly resubmit |
| acknowledged/partial/unknown | order found | move through legal lifecycle and deduplicate executions |
| acknowledged/partial | not found | mark `unknown` and alert |
| terminal | normally not polled | retain immutable history; later audit jobs may verify |

The broker is authoritative for actual order/fill state. “Not found” after a
submission attempt is ambiguity, not proof that no order exists.

## Storage design

- `orders`: current optimistic-versioned projection and immutable intent JSON;
- `order_events`: append-only lifecycle evidence;
- `executions`: unique `(client_order_id, venue_execution_id)` fills;
- `outbox`: events committed with ledger changes and marked published only
  after a downstream sink acknowledges them.
- `account_snapshots`: append-only raw broker account evidence;
- `account_balances` and `positions`: atomically replaced current projections;
- `balance_reservations`: idempotent local holds that prevent concurrent intents
  from spending the same broker-available funds.

SQLite tests use string-backed exact decimals, while PostgreSQL uses native
`NUMERIC(38,18)`. This prevents SQLite's floating conversion from masking
financial precision defects. The authoritative PostgreSQL DDL is in migrations
`0001` through `0003` and uses JSONB, TIMESTAMPTZ, NUMERIC, foreign keys,
uniqueness, row locking for reservations, and partial indexes.

## Verified crash points

- process stops after intent persistence but before claim;
- process stops after claim but before broker certainty;
- broker accepts, then process stops before local acknowledgement;
- fill transition fails while executions are being persisted;
- duplicate submission, snapshot, and execution delivery;
- local/broker mismatch reconciled from broker truth.

## Remaining operational gates

- add broker-specific bulk startup reconciliation and pagination;
- add realized-PnL/account-equity projections after venue account semantics are
  defined; current positions preserve broker unrealized PnL;
- wrap the outbox `run_once` operation in a supervised service with metrics and
  alerting;
- rehearse retention, backup/restore, migration rollback, and prolonged
  database-outage procedures on the deployment host;
- wire no live adapter until those gates and Phase 6 parity tests pass.

## Verification

- focused ledger, projection, reservation, and outbox tests passed;
- disposable PostgreSQL 17 migration/repository integration: 1 passed;
- complete default suite: 218 passed, 1 PostgreSQL test skipped unless
  `TEST_POSTGRES_URL` is supplied;
- only a disposable local PostgreSQL container with synthetic data was used;
  no broker network or trade was used, and the container was removed afterward.
