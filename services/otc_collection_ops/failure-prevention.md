# Owned collector process boundary

1. Repro: an unrelated Python `-c` process with a collector-looking argument suffix passed ownership admission; a normal exit between liveness and identity checks halted closure.
2. Evidence: independent no-signal probes and the rejected source hash are in `/tmp/binary-training/critique/collection-ops-round1/`.
3. Classification: deterministic interpreter admission and process lifecycle races.
4. Root cause: checking a suffix allowed earlier interpreter actions; a PID liveness check was treated as a stable lifecycle fact.
5. Permanent constraint: admit only the literal collector interpreter, optional unbuffered flag, exact module prefix, executable identity, CLI paths, working directory and start ticks.
6. Regression: `test_python_c_or_other_executable_is_never_owned` and `test_normal_exit_races_still_require_closed_database` reject the old ownership path and exercise identity, pidfd-open and signal-delivery exits.
7. Generalization: the focused eval requires all checks to pass, including wrong executable, alternate interpreter flags, reused PID, unclosed session, archive integrity and exact fixed chronology.
8. Containment: a pidfd pins the process before identity verification; identity failures send no signal, and a vanished process never substitutes for actual session closure.
9. Reusable flow: run `python3 -m services.otc_collection_ops.tests.focused` before changing the owned-process or archive boundaries, then request an independent cold review.
10. Verification: the repaired source must receive a cold PASS before deployment. Gates/eval alone do not grant deployment or prove an OTC edge.

# Operational IO must close verified collection

1. Repro: `status()` raised `OSError(28, 'No space left on device')`; the run handler caught only `OpsFault`, leaving the owned producer active with no recorded failure.
2. Evidence: the cold rejection and original injected result are `/tmp/binary-training/critique/collection-ops-round2/verdict.md` and `independent-probes.json`; repaired repro evidence stays outside the shipped service.
3. Classification: deterministic exception admission, shutdown ordering and asynchronous result observation.
4. Root cause: reporting executed before cleanup, reporting errors were outside the admitted exception type, and failed archive futures were never read.
5. Permanent constraint: classify operational IO and unexpected errors to fixed codes; remember the primary failure in memory before attempting persistence; admit every run/setup error to verified cleanup.
6. Regression: `test_operational_io_and_unexpected_failures_close_despite_repeated_reporting_errors` and `test_opsfault_only_storage_handler_mutant_is_killed` reject the old narrow-handler path. Actual adoption and new-child launch save failures are also injected.
7. Generalization: a 100% focused eval covers closure progress/events, repeated state ENOSPC, archive worker/publication/wait/future errors, post-removal reporting, final reporting, and ownership rejection. Private exception text never enters diagnostics.
8. Containment: best-effort reporting never interrupts verified SIGTERM/session closure; archive publication failures retain raw; post-removal failure preserves verified gzip evidence. Unknown child identity sends no signal, remains explicit, and prevents a false physically-closed claim or automatic resume.
9. Reusable flow: run `python3 -m services.otc_collection_ops.tests.focused`, retain the exact source-map/package hashes and result JSON outside the service, and request a fresh independent cold review against the frozen capacity reference.
10. Verification: all focused gates/eval must pass and the catch-only-`OpsFault` mutant must fail. The repaired original ENOSPC repro must close once, record a fixed failure, and exit 2 without an escaping IO exception. Only the root's cold PASS authorizes deployment; no live collector source or registration changes belong to this repair.

# Closure failure must block new archival

1. Repro: a transient `owned_producer_closed` event write failed at the fixed end or requested stop; physical closure succeeded, then terminal cleanup submitted an archive and removed raw despite the diagnosed failure.
2. Evidence: the rejected exact source hash and both independent repros are frozen under `/tmp/binary-training/critique/collection-ops-round3/`; new regression results remain outside the shipped service.
3. Classification: deterministic transition admission after a best-effort side effect.
4. Root cause: daily handoff checked failure after closure, but terminal branches continued straight from closure into archive submission.
5. Permanent constraint: one `raise_if_failed()` guard governs producer/archive admission; final-end and requested-stop paths invoke it after closure, and handoff/transport paths recheck after each transition.
6. Regression: `test_registered_end_closure_event_failure_never_archives_closed_raw` and `test_requested_stop_closure_event_failure_never_archives_closed_raw` exercise real SQLite closure and a single closure-event ENOSPC. They require zero archive calls, byte-identical raw retention, physical closure, incomplete state and exit 2.
7. Generalization: neighboring checks inject failure after a handoff launch, during transport summary and after transport launch. Queued work and raw-removal entry reject already diagnosed failures; the raw unlink decision rechecks under the state lock.
8. Containment: diagnosed failure retains closed raw and any existing verified gzip. Producer identity/signal rules, collector source, global chronology, public chain schema and successful normal archival stay unchanged.
9. Reusable flow: run the focused suite and retain exact source/package hashes; replay the two terminal regressions against the rejected source using identical clock/liveness mocks. Keep generated comparison output outside `services/` and outside the deployment archive.
10. Verification: all 29 focused gates/eval must pass. Both terminal regressions must reject the prior source with `archive_count=1`, `raw_exists=false`, and `raw_removed=true`; the repaired source must submit zero archives on those failures. Root's fresh cold PASS is still required before deployment.

# Status must preserve database integrity faults

1. Repro: real invalid SQLite bytes and a valid foreign registration raised fixed faults in `database_summary()`, but `status()` caught all `OpsFault` instances and reported temporary unavailability while collection continued.
2. Evidence: the rejected exact source and independent repros are frozen under `/tmp/binary-training/critique/collection-ops-round4/`; new actual-SQLite regression evidence remains outside the shipped service.
3. Classification: deterministic fault propagation across the monitoring boundary, with owned-process startup distinguished from integrity failure.
4. Root cause: a reporting fallback erased permanent storage/registration diagnoses. The earlier regression mocked `status()` itself and could not detect errors swallowed inside it.
5. Permanent constraint: real status and database reads propagate fixed integrity/schema/registration faults. Source/registration files are rechecked; actual missing/exited PID is distinct from unreadable or unavailable process state.
6. Regression: actual corrupt SQLite and a foreign-registration WAL exercise real `status()`, `database_summary()` and `run()`. Both must stop the verified producer, retain raw/WAL bytes, reject new producers/archives, preserve the primary code and record operator-required closure when the database cannot prove session closure.
7. Generalization: a healthy WAL reader sees committed receipts during an open writer transaction; source/registration mutations fail; unknown/missing databases and process-read failures never qualify for unknown retries. Foreign identity is proved read-only before any writable checkpoint.
8. Containment: only a freshly verified child gets 15 seconds of monotonic startup grace for a missing new path, SQLite with no schema objects, or the exact empty five-table schema before registration commit. Pending is explicitly unhealthy. Corrupt bytes, foreign registration, unexpected schema/data, expired grace and restored/unowned startup are faults.
9. Reusable flow: run the full focused suite and replay the two actual-database integrity regressions against the rejected source with identical clock/liveness mocks. Keep generated comparison results outside `services/` and outside the deployment archive; never modify reviewer evidence.
10. Verification: all 36 focused gates/eval must pass. The rejected status implementation must reach the forbidden collection wait and fail both real-database regressions. The repaired implementation must preserve exact diagnostics and raw/WAL SHA, while normal live-WAL and known-startup cases remain valid. Only the root's fresh cold PASS authorizes deployment.

# Mutable-file faults must still contain owned collection

1. Repro: real source and registration file mutations failed `status()`, then `fail_closed()` repeated the same frozen-file check before checking the owned process; both producers remained running after exit 2.
2. Evidence: the cold rejection and independent actual-SQLite probes are `/tmp/binary-training/critique/collection-ops-round5/verdict.md` and `independent-probes.json`; exact rejected source and new replay results remain outside the shipped service.
3. Classification: deterministic separation of continuation admission from safe containment of a previously owned process.
4. Root cause: `close_owned()` required immutable file availability before pidfd/process identity admission, so the failure preventing continuation also prevented shutdown.
5. Permanent constraint: diagnosed failure cleanup bypasses only mutable-file admission. It still captures the pidfd and freshly admits command, cwd, DB/registration path, executable and start ticks before SIGTERM. Normal handoff/launch/archive/raw unlink still require frozen files.
6. Regression: four actual-constructor/`run()` cases cover source mutation, registration mutation, actual source ELOOP and registration EISDIR. Each stops once and rejects collection waits, launches, archives and removal; both recorded-close and missing-close cases prove that process exit cannot invent SQLite session closure.
7. Generalization: six fresh identity attacks after source mutation reject changed interpreter argv, DB path, registration path, cwd, executable and start ticks without any signal. The focused eval also kills a mutant that repeats frozen-file admission during failure cleanup.
8. Containment: the original fixed fault stays primary, original registration/source/date evidence remains unchanged, and raw is retained. Byte equality is required when no close record is written; recorded-close cases require exactly the actual added session-close row and unchanged receipts/observations. An unclosed DB remains operator-required and never physically closed.
9. Reusable flow: run the focused suite; replay these four full-run cases against rejected SHA256 `3043a6e4f6e67466b28e794401f5f8f99d2f37df6d17bf01be7e35944f3584b8`; retain result JSON and exact package hashes outside the service. Do not modify collector source, registration or previous critic evidence.
10. Verification: the independently frozen nine-test precommit lane and all 43 periodic eval checks must pass, both storage/frozen-cleanup mutants must fail, and the rejected source must fail every actual file-fault regression with zero SIGTERM. The precommit selection covers real mutable-file and bad-database shutdown and must be independently measured within its two-second budget; the full eval keeps all generalization cases. Root's fresh cold PASS remains required before deployment/adoption.
