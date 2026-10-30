# OTC Shadow Vertical Slice

## Implemented path

The Phase 6 foundation translates the current `iqoption_bot.models.TradeRequest`
into a deterministic OTC candidate and routes it through:

`legacy request -> SignalProposal -> generic risk -> OTC expectancy policy ->`
`RiskDecision -> Binary OrderIntent -> OMS -> ledger -> shadow acknowledgement`

The shadow gateway contains no broker client and refuses every environment other
than `shadow`. The worker now has an opt-in, non-blocking mirror after legacy
gatekeeping/sizing and before legacy broker submission. Shadow output cannot
approve, reject, delay, or mutate that legacy submission. Failures are logged
and contained.

## Runtime configuration

The feature is fail-closed and disabled in ordinary defaults, `.env.example`,
and the migration-safety profile:

```text
PLATFORM_SHADOW_ENABLED=false
PLATFORM_DATABASE_URL=
```

To conduct an approved local parity run, an operator may explicitly configure a
dedicated ledger such as:

```text
PLATFORM_SHADOW_ENABLED=true
PLATFORM_DATABASE_URL=sqlite+pysqlite:////app/data/platform-shadow.sqlite
```

SQLite automatically creates the isolated research schema. PostgreSQL must be
migrated using the versioned SQL files first. Enabling the flag without a
database URL logs initialization failure and leaves the legacy path unchanged.

## Preserved binary-option semantics

Binary order intents now durably preserve:

- CALL or PUT direction;
- exact stake;
- fixed UTC expiry;
- decision-time payout ratio;
- venue/product/instrument identity;
- approved limits and exact risk-decision ID.

CALL maps to the domain BUY side and PUT maps to SELL only for lifecycle
compatibility; the explicit binary direction remains authoritative.

## Payout-dependent approval

For payout ratio `r` and calibrated win probability `p`:

- break-even probability is `1 / (1 + r)`;
- expectancy per stake unit is `p*r - (1-p)`.

The migrated path rejects missing calibrated probability, non-positive
expectancy, low payout, stale/missing generic risk state, and every martingale
step. Legacy `ai_confidence` remains descriptive confidence and is not silently
treated as a calibrated probability.

Probabilities with missing, unknown or research-only calibration provenance now
also reject. Registration requires temporally separated train/calibration/test
evidence plus verified model artifact hashes; see
`docs/research/model_calibration_provenance.md`.

## Research and replay evidence

Every evaluated shadow signal—approved or rejected—is written once to the
`signal_decisions` append-only table with proposal data, risk outcome, reasons,
limits, expectancy metadata, and an outbox event. Stable IDs and deterministic
risk-decision IDs make identical fixture replay idempotent.

Runtime mirror records are explicitly tagged `legacy_would_submit`. This tag
means the legacy request had passed the existing gatekeeping, sizing, positive
amount and sufficient-balance checks and reached the pre-broker submission
boundary. It does not claim that IQ Option accepted or settled the trade.

The read-only parity report counts shadow approvals, overlapping rejection
categories and reason frequencies, with breakdowns by asset, source, strategy
and calibration version. Untagged research fixtures are excluded. Generate a
stable Markdown or JSON report without enabling execution:

```bash
PYTHONPATH=src venv/bin/python -m trading_platform.apps.otc_parity_report \
  sqlite+pysqlite:////app/data/platform-shadow.sqlite \
  --format markdown --output otc-shadow-parity.md
```

The root `generate_otc_shadow_parity_report.py` command remains a temporary
compatibility entry point only. The implementation and future changes belong
to `trading_platform.apps`.

For PostgreSQL, replace the URL with the dedicated shadow-ledger URL. The
command reads existing evidence only; it does not create decisions, contact a
broker or affect the worker.

Migration `0004_signal_decisions.sql` was validated as part of the complete
migration chain against a disposable PostgreSQL 17 container. The container
used synthetic data and was removed after the test.

## Authoritative settlement foundation

Binary settlement is now a separate immutable accounting record rather than an
order-status guess. A settlement preserves broker order/settlement IDs, exact
stake, gross return, net PnL, settlement asset, outcome, broker evidence and
the broker-reported UTC settlement time. The domain enforces
`net_pnl = gross_return - stake` and outcome-specific cash-flow invariants.

Only records explicitly sourced from `broker_api` are accepted as
authoritative. Balance comparisons, forced determinations and other estimates
from the legacy result checker must not enter this table or become training
labels. Pending or unavailable broker results remain unsettled and are queried
again on the next reconciliation run.

The restart-safe reconciler:

- requires an explicit environment to prevent shadow/paper/live crossover;
- selects only expired, broker-acknowledged binary orders without settlement;
- validates client order ID, broker order ID, stake, asset and expiry;
- writes the settlement and `binary.settled` outbox event atomically;
- is idempotent across restarts and repeated broker responses.

Migration `0005_binary_settlements.sql` provides the PostgreSQL table and
constraints. Strict IQ Option response normalization now exists behind an
asynchronous exact-order history port, but no legacy-client transport or worker
wiring exists. The missing transport must provide bounded timeouts, pagination,
rate limits and reconnect behavior and be verified against redacted practice
responses. See `docs/research/iqoption_settlement_adapter.md`.

## Remaining Phase 6 gates

- extend strict provenance output and safe runtime propagation beyond the two
  CatBoost paths to any approved tournament trainers. The regime MTF LSTM now
  uses separate calibration, policy and untouched-test partitions and emits a
  strict dataset/artifact manifest, but still needs Kaggle execution evidence
  and a dedicated four-input runtime strategy before it can be considered for
  deployment. The single-input stationary LSTM now emits strict provenance and
  propagates its calibration ID only when its offline gate is approved;
- collect enough sustained realtime evidence to interpret the implemented
  parity report and define acceptable differences;
- implement the bounded/paginated IQ Option history transport, validate it
  against redacted practice responses, then supervise the restart reconciler;
- migrate practice execution only after sustained shadow parity;
- remove JSON as operational authority only after settlement and operational
  reports also read from the ledger.

## Verification

- focused runtime containment, domain, compatibility, and OTC shadow tests pass;
- complete suite verified in component groups: 350 passed, 1
  PostgreSQL test skipped unless enabled; the combined runner was terminated by
  the current sandbox after collection without reporting a test failure;
- PostgreSQL 17 full migration-chain test: 1 passed separately;
- no IQ Option call, live-server change, or trade occurred.
