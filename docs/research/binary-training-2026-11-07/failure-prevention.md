# Binary research recovery and failure prevention

1. Trigger: an interrupted session leaves untracked service tests, training inputs or model outputs.
2. Failure: broad `test_*.py`/`*.txt` ignore rules hid service tests and dependency manifests from Git and app archive snapshots.
3. Evidence: snapshot `ef91ea3` retained implementation and omitted ignored tests/requirements; the prior cold review retained an independent test copy.
4. Invariant: source, deterministic gates, periodic eval code and dependencies must all survive the same commit and snapshot.
5. Fix: scoped Python exceptions for contracts/observer/research plus the exact training dependency manifest; preserve data/model ignore rules.
6. Gate: `git check-ignore` must not list any scoped Python test/eval or requirements file. Precommit runs each service's gate suite and checks staged whitespace.
7. Eval: fixed receipt/cash/data/training cases plus negative controls; actual raw provenance remains a separate trusted export boundary.
8. Recovery: inspect app snapshot refs before assuming files are lost. Extract only the affected source paths. Never reset other sessions' work.
9. Evidence storage: raw exports, weights, progress logs, comparison outputs and critic verdicts stay under `/tmp/binary-training/`; no keys, databases or compiled files enter Git.
10. Completion: cold critic PASS, fresh artifact rating, scoped staged-path audit, hooks, commit and push. A blocked approval service is reported; protected writes are never bypassed.

Receipt and accounting recurrence rule: source/receipt joins must have explicit clock identity; compute settlement returns in a fixed Decimal context. `contracts/otc_v1/evals/eval_records.py` includes the old ambient-context mutant. Observer and trainer regression evals cover the historic future-payout and impossible-age paths.
