# Fresh core comparison, static-source variant

This service reconstructs the registered seven-day cohort with the original dataset and model procedure. It keeps all 10,080 two-asset opportunities, including source gaps, ineligible decisions, unresolved outcomes and ties. Fresh results are development evidence. They do not authorize capital or provide untouched confirmation.

The original research and shared-contract files are byte-identical copies. `original-source-lock.json` records their hashes and the capture time before the live cohort began. The compiler takes only those source bytes and the immutable registration. It writes literal UTC millisecond partition boundaries into a separate trainer. It does not rebind runtime globals or accept dates chosen from label coverage. Its proof checks module constants/imports and the complete original fit, preprocessing, calibration, policy, counting, purging and inference function AST. Only admission guards, streaming SHA compatibility and cohort wording change. Historical files and August scope stay unchanged.

The live registration is `4d15b0e235082b7086b8de1f5b5acb683b73daeaf56996cdb88e64b10a10108f`, with fixed interval 7 November 2026 at 10:08 UTC through 14 November at 10:08 UTC. The original source capture predates that start. Compiler preparation can happen afterward because its inputs are the frozen original procedure and registered dates. Both timestamps are recorded truthfully in the plan and proof; the compiler consumes no source outcomes or metrics.

The exporter reads only a hash-verified immutable collector backup. It fetches complete receipt windows in SQL batches of 256, using at most 20,000 source observations and 16MiB serialized input per window. Exceeding either limit blocks without truncation. The unchanged dataset builder handles each two-asset decision. This avoids loading seven days of quotes or a full lineage dictionary into memory.

Before any SQLite image is admitted, a whole-source streaming census checks every receipt, including empty and quarantined frames, and every observation. SQL dates alone are insufficient. Every canonical envelope hash, frame/session/sequence identity, exact receiver nanosecond clock and millisecond floor must match SQL and the registered interval. Each unique envelope event must have exactly one SQL observation with the same canonical observation and lineage, scope, clock and clock status. The event total must equal the complete SQL observation inventory. Missing, extra, duplicate or orphan observations reject even when they would never be selected by a decision window and every external file hash has been recomputed.

The census parses one envelope at a time and uses an indexed observation identity lookup rather than collecting the source in memory. It caps canonical envelopes at 1MiB, each observation/lineage at 64KiB and each envelope at 4,096 events. SQL checks these byte caps before payload loading. Audit `source_census` records checked sessions, receipts and observations, maximum record sizes, the one-envelope streaming bound and zero violations. A chain aggregates the counts for every archive, including archives without selected decisions. Invalid source records block; they are never filtered away to produce a clean matrix.

Session fields reject SQL NULL, non-text/empty identities or transitions, invalid clocks and malformed canonical detail objects. Each identity must have exactly one open and one close with ordered clocks. The census checks frame IDs and `(session_id, sequence)` uniqueness within every SQLite image. A disk-spooled SQLite identity ledger then enforces unique session, frame, session-sequence and event ownership over the complete disjoint archive chain. Identical duplicates also reject. The ledger sees empty and quarantined frames and events, including archives never selected by replay. Its UNIQUE constraints outlive the receipt tail, so a reused event several days later cannot change meaning unnoticed.

Only identity strings and sequence integers enter that temporary ledger. Key batches hold at most 256 rows and 256KiB of exact UTF-8 text plus 8 bytes per integer, with one pending source key. The SQLite cache is 2MiB, mmap is disabled, database storage is capped at 8GiB and total temporary ledger files at 16GiB+16MiB. SQLite rollback journaling and synchronization remain enabled. Database exhaustion rejects; source records are never truncated. Every source failure and abort closes the ledger and removes its files. Audit `source_census.global_identity_ledger` records key counts, measured batch/disk maxima, caps, violations and cleanup completion.

The cap is sized from an audit-only metadata measurement of the existing immutable live prefix, without labels or fitting. Its 4,870 receipts and 4,206 events over 672,808ms project 4,376,838 receipts and 1,266,347,028 ledger bytes for the fixed seven days. The former 1GiB cap was too small. The 8GiB cap gives 6.78 times that estimate; arrival rates and long identities can still reach the explicit fail-closed cap. The reproducible measurement and untouched source hash are in `evidence/ledger-capacity/measure.py` and `result.json` in the reviewed artifact. Only source files ship; the sampled ledger database and generated trainers remain outside the package.

Fresh v2 nanoseconds are required. Every valid source event must have exact `received_at_ns` matching the floor-millisecond SQLite receipt and envelope. The original dataset builder runs on integer nanosecond ticks, with every clock timestamp and physical duration scaled by the same factor. Its source bytes, feature formulas, selection rules and physical limits stay unchanged. Distinct receipts within one millisecond keep their actual order: entry chooses the earliest exact receipt; terminal chooses the latest exact receipt at or before expiry. External decision/expiry timestamps stay milliseconds. Exported receipt ages use ceiling milliseconds so they cannot understate true age. Integer-millisecond fixture matrices remain byte-identical.

Every feature reference is independently checked against its decision or lookback cutoff in nanoseconds and against the registered physical receipt age. Missing nanosecond evidence blocks. Complete same-asset/kind/source batches at the same exact nanosecond with different values are quarantined and written to `receipt_batch_conflicts.jsonl`. Relevant feature opportunities remain ineligible; relevant outcome opportunities remain unresolved. A conflict received after the decision can make the outcome unknown without changing the decision's features or eligibility. Identical-value exact-nanosecond batches use a stable identity. Distinct nanoseconds are sequential receipts, even when their SQLite millisecond floors match. All source joins are checked against the immutable receipt envelope and hash.

Run from this artifact root. The source compiler/exporter and fast gates require only Python 3.10 stdlib. Full fitting uses the existing Python 3.12 scientific environment with the exact unchanged `services/otc_research/training_requirements.txt` versions. Do not install into the system interpreter.

```bash
python3 -m services.otc_fresh_compare.compiler freeze-plan \
  --output /tmp/fresh-core-compiler-plan.json
python3 -m services.otc_fresh_compare.compiler compile \
  --registration /tmp/binary-training/fresh-live-v2/registration.json \
  --plan /tmp/fresh-core-compiler-plan.json \
  --output /tmp/fresh-core-source/training.py
```

After the registered end, provide the collector's completed immutable backup/export folder. Its `manifest.json` must hash `receipts.sqlite` and all declared boundary files, match the registration and source locks, and show closed collection sessions. A prefix snapshot cannot be exported as a completed cohort. The exporter verifies hashes again after replay.

The approved daily archive workflow passes the explicit `--chain /tmp/fresh-otc-20261107-core-v2/sourcechain.json` path instead. The exact chain fields are `schema: fresh_otc_source_chain_v1`, `registration_sha256`, strict boolean `complete`, and `segments`. Each segment has only an absolute `.sqlite.gz` path in one `segments` directory, `compressed_sha256`, `sqlite_sha256`, positive integer `sqlite_bytes`, and increasing integer `closed_at_ms`. Operational status belongs in a separate file. The chain is complete only after the registered end and graceful final closure.

`export --chain ... --wait-chain` can wait locally for that boundary. `CLOSURE_ARCHIVE_GRACE_MS` is fixed at one hour after the registered global end. Waiting never extends opportunity dates. Before the end, ETA follows the fixed clock. During archive closure, ETA is unknown. An incomplete chain at the deadline raises `BLOCKED`; a completed chain published before the registered end rejects. Each wait lasts at most 60 seconds. State changes and five-minute progress are printed and appended to `/tmp/fresh-otc-chain-wait-<registration-hash-prefix>/progress.log`, with the exact `tail -f` command printed at creation. No waiting occurs unless `--wait-chain` is supplied.

Each archive is decoded into one temporary SQLite file, verified against both compressed and decoded hashes/size, checked for integrity, identical global registration and closed-session evidence, and opened read-only. The actual final session close must be at or before the declared producer closure, which can follow process exit, checkpoint and summary by a few milliseconds. The actual session close controls the cross-shard replay boundary; metadata lag cannot hide a next-shard boundary receipt. Session times must be integer, ordered and at or before producer closure. The final shard's session close must reach the registered cohort end. The previous file is removed before another shard is decoded. Only a bounded receipt tail survives across boundaries. SQL merges complete boundary batches, including exact closure/expiry equality, before calling the original builder. Closed archives remain intact. Source gaps retain their opportunities. Every archive and the chain itself are verified again before successful completion.

Owned physical handoffs must move forward. Every session open and every receipt in the next shard must be at or after the preceding shard's actual session close. Equality in the same millisecond is permitted because session close is measured at millisecond precision; exact receipt nanoseconds still order the complete boundary batch. Backward owned shards reject rather than silently losing earlier decisions. The synthetic chain fixtures use distinct physical sessions whose opens match their handoff boundary.

The automatic workflow compiles the separately generated original trainer before waiting, waits for the immutable fixed end and complete archive chain, exports the entire fixed grid, then runs the original comparison and saved inference parity. A failed wait or export stops before fitting and writes `workflow-status.json` with `BLOCKED`. From the installed source directory, using `python` in the already activated pinned ML venv:

```bash
python -m services.otc_fresh_compare.run \
  --registration /tmp/fresh-otc-20261107-core-v2/registration.json \
  --chain /tmp/fresh-otc-20261107-core-v2/sourcechain.json \
  --output /tmp/fresh-otc-core-comparison-20261107
```

```bash
python3 -m services.otc_fresh_compare.export export \
  --chain /tmp/fresh-otc-20261107-core-v2/sourcechain.json \
  --registration /tmp/binary-training/fresh-live-v2/registration.json \
  --plan /tmp/fresh-core-compiler-plan.json \
  --output /tmp/fresh-core-matrix
/home/saviour/PycharmProjects/I2/IQoption/venv/bin/python \
  -m services.otc_fresh_compare.export compare \
  --trainer /tmp/fresh-core-source/training.py \
  --matrix /tmp/fresh-core-matrix/matrix.csv \
  --manifest /tmp/fresh-core-matrix/manifest.json \
  --output /tmp/fresh-core-comparison
```

Compilation writes `training.py`, `training.proof.json` and `training.plan.json`. Comparison regenerates the entire allowed transformation from the recorded source plan and matrix registration, then requires exact source bytes before executing the supplied trainer. Redeclaring a changed source hash cannot authorize altered thresholds, dates or admission guards. The static trainer revalidates the registration, shared-contract source hashes, full opportunity grid and exact matrix bytes before importing ML libraries. Minimum sample/class support, all six policy variants, train-only preprocessing, early-only stopping, calibration-only temperature, policy-only selection, the global 120-second position rule and worst-case unresolved loss remain the original procedure. Diagnostic label rotation must leave predictions and selections unchanged. Saved reload parity uses the same compiled literal schedule.

```bash
python3 -m unittest discover -s services/otc_fresh_compare/tests -p test_gate.py -q
/home/saviour/PycharmProjects/I2/IQoption/venv/bin/python \
  -m services.otc_fresh_compare.eval_core --output /tmp/fresh-core-eval
python3 -m services.otc_fresh_compare.eval_precision \
  --output /tmp/fresh-core-precision-eval
python3 -m unittest discover -s services/otc_fresh_compare/tests -p test_chain.py -q
python3 -m services.otc_fresh_compare.eval_chain \
  --output /tmp/fresh-core-chain-eval
python3 -m services.otc_fresh_compare.eval_template \
  --output /tmp/fresh-core-template-eval
python3 -m services.otc_fresh_compare.eval_exact_ns \
  --output /tmp/fresh-core-exact-ns-eval
python3 -m unittest discover -s services/otc_fresh_compare/tests \
  -p test_full_census.py -q
python3 -m services.otc_fresh_compare.eval_full_census \
  --output /tmp/fresh-core-full-census-eval
python3 -m services.otc_fresh_compare.eval_workflow
python3 -m unittest services.otc_fresh_compare.tests.test_global_identity -q
python3 -m services.otc_fresh_compare.eval_global_identity \
  --output /tmp/fresh-core-global-identity-eval
```

The core eval requires positive diagnostic log loss below 0.85, null loss above 0.70, exact grid retention, zero checked millisecond/nanosecond future references, finite memory budgets, both-model saved parity, invariant predictions/selections under diagnostic-label rotation, and a blocked report for missing source periods. The precision eval attacks both assets and all three feature kinds with fractional-millisecond future receipts and compares to the old floor-only behavior; it also checks complete multi-event conflicts. The exact-nanosecond eval checks both assets at decision, lookback, entry, expiry and receipt-age boundaries, legitimate sequential receipts, earliest entry, latest terminal and future-conflict feature invariance. Template eval accepts `--positive-matrix /path/to/existing/matrix` to prove successful deterministic reconstruction and both-model saved parity without repeating source replay. Every check must pass. Fixtures are synthetic and explicitly marked `synthetic_training_eval` in the matrices.

The identity eval uses a separate shifted UTC schedule, both assets, all three kinds and four owned shards. It attacks every nullable/empty session field, distant and exact-boundary reused identities, empty/quarantined receipts, complete export paths and bounded cleanup. Positive controls compare boundary replay with a monolithic source and retain all 10,080 unknown-loss opportunities. Admission-only revisions reuse hash-verified saved model eval artifacts and re-export frozen matrices to prove byte parity without repeating ML fits. The original 12 core gates have a separate controlled wall-clock budget below 2 seconds; slower held-out source/chain/clock evals run before shipping.

Before exposing either a snapshot or each decoded archive, the exporter censuses every physical source row. Receiver dates must lie in the fixed start-inclusive/end-exclusive cohort and inside their own actual open/close session. Every observation needs its matching receipt. This includes unselected and quarantined rows. Declared producer closure cannot be later than the evaluator's current clock. A valid hash cannot override these chronology rules. The free periodic scope eval is `python3 -m services.otc_fresh_compare.eval_source_scope`; its snapshot/archive attacks include fully rehashed out-of-scope records. For the fast source regression gate, run `python3 -m unittest services.otc_fresh_compare.tests.test_source_scope.ScopeTests.test_rehashed_prestart_end_or_postclose_receipts_block -q`.

The historical dataset still fails original admission: its early partition contains zero resolved unpurged rows, below the minimum of 50. No historical rows or partition boundaries are changed by this service. No program needs restarting for this offline artifact.
