# Whole-source cohort admission

1. Repro: a fully rehashed closed source archive carried a quote before the fixed cohort start, or a receipt after its own session closed, and passed admission.
2. Evidence: cold artifacts are under `/tmp/binary-training/critique/core-comparison-round1/`, including `candidate-1-verdict-v3.md`.
3. Classification: deterministic whole-source chronology admission gap.
4. Root cause: selected receipt-window checks did not census records outside those windows, and closure metadata could be later than the evaluator's clock.
5. Permanent constraint: census every receipt and observation against the fixed start-inclusive/end-exclusive interval and its actual open/close session before exposing each immutable SQLite source. Reject declared closure after the current clock.
6. Regression: `tests/test_source_scope.py` uses fully rehashed snapshots and archives with pre-start, exact-end, post-session-close and future-closure records.
7. Generalization: `eval_source_scope.py` requires all snapshot/archive source cases to pass without fitting; existing chain, exact-nanosecond, precision and positive/null model evals remain separate.
8. Containment: rejection preserves source files and yields no fitted model. No filtering, timestamp shifting or new registration repairs the invalid source.
9. Reusable flow: run the source-scope gate plus periodic scope/chain evals before changing admission, then give the exact source bytes to an independent cold critic.
10. Verification: a cold PASS and unchanged original model AST are required before the automatic fixed-end comparison is deployed.

# Raw receipt inventory and physical handoff admission

1. Reproduce: a fully rehashed empty-events receipt indexed inside the cohort carried pre-start canonical envelope clocks. A later shard also carried earlier receipts; full whole-source replay resolved two rows while the chain silently lost them.
2. Preserve evidence: `/tmp/binary-training/critique/core-comparison-round2/verdict.md`, `attack.py`, `attack_chain_backward.py`, `attack-unknown-receipt-export.json` and `chain-whole-source-comparison.csv` are the frozen failures. B-r2 remains unchanged.
3. Classify: both defects are deterministic boundary failures. A model prompt, filtered replay or adjusted registration cannot repair them.
4. Find the cause: SQL-only scope census trusted unexamined envelope clocks. Shard admission checked each file globally but failed to prove its producer started after the prior physical close.
5. Constrain permanently: `census.py` parses every raw envelope with byte/event caps, verifies canonical hash/identity/exact receiver clock, checks every envelope event against a unique SQL observation and requires complete inventory equality. `SourceChain` requires incoming opens and receipts at or after the preceding actual close, allowing same-ms boundary batches.
6. Kill the regressions: `tests/test_full_census.py` places fully rehashed malformed records outside selected windows and compares the new guard with a literal old SQL-only mutant. It checks raw identity, canonical clocks, missing/extra/duplicate inventory, byte caps, backward handoffs and legitimate boundary/producer-lag controls.
7. Generalize independently of fitting: `eval_full_census.py` uses shifted chronology, both assets, all three observation kinds, varied unselected frames and a valid streamed census. Existing six comparison eval lanes remain intact; model and matrix parity must remain unchanged.
8. Trace the outcome: each successful export audit reports `source_census` checked receipt/observation/session counts, record limits and zero violations. All physical shards contribute, even when their rows are unselected. A rejection produces no successful matrix manifest or fitted model.
9. Make the flow reusable: run the full-census gate/eval and chain/source-scope lanes whenever admission or archive ownership changes. Use the narrow `run.py` workflow to stop automatically on wait/export failure and preserve `BLOCKED` evidence.
10. Gate deployment: freeze exact source/file hashes, verify unchanged original research source and model AST plus preserved eval/parity evidence, then obtain a fresh independent cold verdict. No builder self-review or changing the rubric can substitute for that PASS.

# SQL NULL and global archive identity ownership

1. Reproduce: an orphan session with SQL NULL transition passed the SQL-only guard; disjoint archives reused a closed session or contradictory event identity after the replay tail expired.
2. Freeze the failure: `/tmp/binary-training/critique/core-comparison-round3/verdict.md`, `chain/probes.py` and `chain/full-export-results.json` remain unchanged. B-r3 is the frozen failing reference.
3. Classify: deterministic SQL three-valued logic and global identity ownership failures. No fitting or model judgment is involved.
4. Explain the cause: `NOT IN` does not select NULL. A replay-tail identity dictionary proves uniqueness only while records coexist, so it cannot prove ownership across seven days.
5. Constrain: explicit NULL/type/empty guards and exact open/close cardinality census every physical session. A bounded temporary SQLite ledger uses UNIQUE constraints for every session/frame/session-sequence/event in each whole, already-censused shard. Identical duplicates reject too.
6. Kill regressions: `tests/test_global_identity.py` checks orphan/owned NULL fields, malformed details, duplicate/missing/reversed pairs, distant reuse, empty/quarantined records, direct session-sequence constraints, byte/row/database caps and cleanup after abort/late failure.
7. Generalize: `eval_global_identity.py` uses a held-out UTC schedule, both assets, all 3 kinds and 4 shards; full exports reject invalid identities and valid boundary controls retain all 10,080 unknown-loss opportunities. The literal old SQL mutant still admits the NULL orphan.
8. Trace: successful audits record `source_census.global_identity_ledger` with all checked identity counts and bounded batch/disk maxima. Rejections produce no successful matrix manifest, comparison or model fit; a late export can retain partial CSV evidence.
9. Codify capacity: `evidence/ledger-capacity/measure.py` reads only an immutable audit prefix, hashes it before/after and estimates seven-day metadata using measured SQLite page allocation. Its 1.27GB projection invalidated the former 1GiB cap; the 8GiB cap has measured headroom while remaining fail-closed. No payload/label fit occurs.
10. Gate completion: verify exact original-source bytes and full original model/data AST, re-export unchanged matrix/lineage fixtures, hash-check the preserved 64 saved model artifacts, measure the 12 core gates without competing jobs, freeze a source-only package, then request a fresh cold critic. The builder cannot award the review PASS.
