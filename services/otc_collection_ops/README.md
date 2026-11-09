# Immutable collector capacity supervisor

Outcome: keep the seven-day cohort losslessly within scratch-disk capacity by rotating closed SQLite databases daily and retaining verified gzip archives. This service uses Python 3.10 standard library only and lives outside the immutable collector source. It reads no credential values and adds no broker operation.

The global registration stays at 2026-11-07T10:08:00Z through 2026-11-14T10:08:00Z. Every segment uses that same registration and collector source hash. Database segmentation never changes model settings, dates, clocks, opportunity grids, or admission rules. Original failed pilots and the separate compression-prefix review are outside the owned segment list and remain untouched.

## Essential offline verification

Before each commit, run the nine precommit gates from this package root:

```bash
python3 -m services.otc_collection_ops.tests.gate
```

The cold reviewer froze this selection before the gate runner was written. It reuses unchanged full-suite regressions for exact/unknown ownership, fixed dates, gzip/provenance, actual corrupt-database and mutable-source-read-fault shutdown, and failure guards for queued archives, launches and removal. It reports measured runtime against the two-second budget separately from deterministic assertion results; machine scheduling does not introduce a flaky regression assertion. The final independent combined selection run took 0.763 seconds; the whole Python process took 1.005 seconds. Runtime remains separately measured under machine contention.

Before shipping, and for periodic/nightly evaluation, run all 43 checks:

```bash
python3 -m services.otc_collection_ops.tests.focused
```

The full periodic deterministic eval covers PID/database/registration/start-time and executable identity, rejected Python interpreter prefixes, normal-exit races, no signals on failed ownership, exact UTC dates and handoffs, close/launch/compress order, streamed gzip SHA equality, corrupt/unclosed/unowned retention, exact public chain fields, and transport-only restart classification. It has a 100% pass threshold and kills both catch-only-`OpsFault` storage-failure and repeated-frozen-file-cleanup mutants. It injects status, state/event, adoption, launch, archive publication, archive wait/future and final-reporting failures, plus archive admission after final-end, requested-stop, handoff, transport and queued-work failures. Actual SQLite cases cover corrupt bytes, foreign registration in a live WAL, healthy committed WAL reads during an open writer transaction and bounded startup. Source/registration mutation and actual source ELOOP/registration EISDIR read faults use the real constructor, fake `/proc`, real `status()`, `database_summary()` and `run()`. Each file fault exercises both actual recorded session closure and missing session closure. Six subsequent process identity attacks must send no signal. There is no network, SSH, credential read, real process signal, framework install, or toolkit test suite. This service has no LLM behavior to grade, so both lanes are deterministic and make no paid model calls.

## Deploy separately and adopt the existing producer

Copy this package to `/home/ubuntu/otc-edge-research/collection-ops`, leaving `/home/ubuntu/otc-edge-research/20261107-core-v2/src` unchanged. Run this command on the server after deployment:

```bash
PYTHONPATH=/home/ubuntu/otc-edge-research/collection-ops /usr/bin/python3 -m services.otc_collection_ops.ops supervise --source /home/ubuntu/otc-edge-research/20261107-core-v2/src --registration /tmp/fresh-otc-20261107-core-v2/registration.json --namespace /tmp/fresh-otc-20261107-core-v2 --adopt-pid 2970501 --initial-db /tmp/fresh-otc-20261107-core-v2/receipts.sqlite --progress-log /tmp/fresh-otc-20261107-core-v2/ops-progress.log
```

The initial adoption verifies `/usr/bin/python3` with only an optional `-u` before the exact `-m services.otc_collector.runner live` command, the resolved `/proc/<pid>/exe`, absolute `--db` and `--registration` paths, source working directory, explicit account-read acknowledgement, and Linux PID start ticks. It never reads `/proc/.../environ` or an env file. An identity mismatch exits before signaling anything. SIGTERM uses a Linux pidfd captured before identity verification, so subsequent PID reuse cannot redirect a signal. Normal exits racing verification or signal delivery still require actual owned database/session closure. Python 3.10 on Linux with pidfd support is required. No SIGKILL, global process kill, sudo, installation, cron, or app heartbeat is used.

The supervisor reuses the verified producer's existing interpreter and CLI in memory and in private operational state. The external env-file argument remains a path; no value is read. New producers run the same immutable source and registration with only their new database and progress-log paths. Subprocess output is suppressed; persisted safe collector health is used to diagnose exits.

Child imports are pinned to the immutable source directory through their working directory and `PYTHONPATH`. The supervisor's own module path and ambient environment are not inherited; the existing absolute interpreter and explicit external env-file argument remain unchanged.

For a persistent foreground session, use the server terminal/session manager already in use. The supervisor handles SIGINT/SIGTERM by gracefully closing only its verified producer and archiving closed segments. Run the same command again to resume owned `ops-state.json`; the recorded current PID/database are reverified rather than blindly reusing initial PID 2970501. A completed chain exits without reconnecting.

## Handoff and retention

Daily handoffs occur at the registered start plus N UTC days plus 90 seconds: first 2026-11-08T10:09:30Z, then the same offset for days two through six. These are 90 seconds away from the 120-second decision grid. The final producer closes at the exact registered end, 2026-11-14T10:08:00Z, with no extra 90-second extension.

For each handoff: reverify ownership, send SIGTERM, wait up to 45 seconds for process exit and SQLite/session closure, checkpoint the closed owned database, launch the next producer, then compress the old database in a separate worker. Actual restart gaps stay visible in original receipt/session timestamps. The new producer starts before old compression begins.

The initial canonical `/tmp/fresh-otc-20261107-core-v2/receipts.sqlite` is segment zero in `ops-state.json`. Its first archive is `/tmp/fresh-otc-20261107-core-v2/segments/day-001.sqlite.gz`; subsequent producers write `segments/day-002.sqlite`, etc. Original canonical identity remains manifested after owned scratch raw data is removed.

Compression streams gzip level 6 with bounded one-megabyte buffers and deterministic gzip headers. It hashes the full checkpointed SQLite bytes, decompresses and hashes the gzip, requires exact raw SHA256 and byte-count equality, fsyncs the gzip and directory, and atomically publishes provenance before removing raw. It rechecks retained gzip and raw bytes before unlinking only that manifested, owned, closed scratch database. Other files, failed pilots, compression probes, and credentials are never removed. Corruption or changed raw data leaves raw intact and halts.

## Public chain and operational evidence

`sourcechain.json` has exactly this contract:

```json
{"schema":"fresh_otc_source_chain_v1","registration_sha256":"<same global registration>","complete":false,"segments":[{"path":"/tmp/fresh-otc-20261107-core-v2/segments/day-001.sqlite.gz","compressed_sha256":"<gzip SHA256>","sqlite_sha256":"<full raw SHA256>","sqlite_bytes":1,"closed_at_ms":1}]}
```

The example numbers are shape examples; actual positive byte counts and receiver-clock closure times are measured. Segments publish chronologically without jumping past an earlier pending archive. `complete` becomes true only after the global end, all producer closures and all verified archives. Exporters can decode one shard at a time and validate its exact SQLite hash and unchanged registration.

`ops-state.json` holds original canonical path, PID/start ticks, source and registration file hashes, session/receipt/observation counts, raw/gzip sizes, timestamps, failures, and ownership history. No operational fields or env-file path enter the public chain. A transport crash with an unclosed session stays explicit in operational evidence; no session close or missing row is invented.

```bash
tail -f /tmp/fresh-otc-20261107-core-v2/ops-progress.log
```

Progress prints and appends JSON every 30 seconds, and more often during graceful close/archive waits. Percent/ETA use the original global chronology. Raw growth, next-handoff disk need, free disk, receipt counts, quote recency, and measured gzip ratio use persisted state. A compressed forecast is absent until there is a verified actual archive. A 512 MiB reserve violation gracefully stops the owned producer and reports an incomplete chain.

Automatic supervisor restarts are limited to three positively identified transport exits across the cohort. Auth, clock, storage, ownership, unknown, and archive failures halt with concrete JSON codes. The original collector's own reconnect policy stays unchanged. Resolve a reported failure before resuming; the supervisor never edits source/registration to make resume pass.

Operational `OSError` and SQLite failures become `supervisor_operational_io_failed`; other unexpected exceptions become `supervisor_unexpected_failure`. The original failure stays primary, and secondary fixed codes stay in private `failure_diagnostics`. Diagnostics print to stdout even when progress-file writes fail. During failure cleanup, state/event/progress writes are best-effort and cannot prevent SIGTERM of a freshly verified owned producer or subsequent database/session closure checks. An adoption save error is handled inside construction, before the supervisor can disappear without closing its verified producer. An identity rejection still sends no signal and requires operator investigation.

Frozen source and registration checks admit normal handoffs, producer launches, archive submission/worker entry and raw removal, including the final unlink decision. A diagnosed failure uses `close_owned(..., failure_cleanup=True)` to contain the previously owned producer without rereading those mutable files. This requires an already recorded failure and still freshly verifies the exact process command, source working directory, database/registration paths, executable and start ticks after capturing its pidfd. Source/registration mutation or unreadability remains the primary failure; cleanup cannot authorize a new producer, archive or raw removal. Process exit alone is insufficient: actual owned database/session closure must succeed before `physically_closed` can become true. Otherwise raw remains retained and `owned_stop_requires_operator` remains explicit.

Every archive future is consumed. Worker errors and failed error-event persistence remain visible, stop current verified collection, and keep the chain incomplete. Failed archive publication retains both the raw database and any verified gzip. A reporting failure after already-authorized raw removal records `archive_io_failed_post_removal` and the true `raw_removed` state; the verified gzip and its earlier durable hashes remain the retained source. Cleanup does not start new archives after a supervisor failure. A new child whose identity cannot be admitted is explicitly recorded as `unverified_launched_child`, is never claimed physically closed, and prevents automatic resume.

A closure-event failure at the fixed end or a requested stop still proves physical closure but retains the closed raw database without submitting an archive. The same failure admission guard applies before new producers, after handoff/transport transitions, when queued archive work starts, and immediately before raw unlink. Already verified gzip remains available; diagnosed failures never authorize raw removal or new collection.

Status rechecks the immutable source and registration file and never converts database integrity, schema, registration or read faults into temporary availability. `segment_database_read_failed`, `segment_database_schema_mismatch`, `segment_registration_mismatch` and `segment_database_missing` preserve the diagnosis through owned cleanup. The five collector tables and required read columns must be present with no views. Registration is verified through a read-only connection before opening a writable checkpoint connection. When corruption or a foreign registration prevents proving session closure, the verified process is stopped and raw remains retained with `owned_stop_requires_operator`; physical closure is not fabricated. An unreadable or unavailable `/proc` is `owned_process_liveness_read_failed`, rather than evidence for transport restart.

A freshly launched child has a 15-second monotonic startup grace for only the immutable collector's known initialization states: its new path is absent, SQLite has no schema objects, or the exact five tables are empty before registration commit. Each startup check revalidates child PID/start ticks, command and source identity. These states report `awaiting_owned_database_startup` and `database_ready:false`. Corruption, unexpected schema/data or any present foreign registration fails immediately, including during grace. Grace expiry triggers a status check before the next normal 30-second report. A restored/unowned child receives no startup grace. No diagnosed error is retried, and these operational deadlines never change the global registration or receiver timestamps.

Persistent disk failure can prevent the latest failure state from reaching disk. Fixed stdout diagnostics and the nonzero exit remain available when stdout works; recovery still rechecks process identity and archive bytes. A persisted complete state whose public chain differs is rejected. Repair disk capacity/permissions and inspect the owned process/session evidence before restarting the supervisor.

No existing collector restart is needed to adopt PID 2970501. Start this supervisor after deploying the separate package; it performs subsequent owned daily handoffs.
