# R1 Archive Transfer Implementation Plan

**Goal:** Finish interrupted public depth downloads with verified resumable ranges, then distinguish complete ZIP integrity from full-day book replay.

**Architecture:** Independent `services/archive_transfer_r1/` owns public HTTP range downloads, immutable version identity, per-chunk evidence, final assembly/CRC and progress. It has no account, order or strategy authority. Existing partials remain untouched. Raw payloads live in ignored `data/`.

**Tech Stack:** Python standard library urllib, concurrent futures, hashlib, json, zipfile, unittest. HTTP range/If-Range is the existing standard pattern; no new downloader framework required.

## Implementation sequence

1. Freeze acceptance rubric at `/tmp/r1-archive-transfer/critique/rubric.md`. Produce two independent variants under `/tmp/r1-archive-transfer/variant_a/` and `variant_b/`, each with tests/evals/README. Independent critic compares deliverables against rubric before selection.
2. Chosen unit goes to `services/archive_transfer_r1/transfer.py`, `tests/test_transfer.py`, `evals/eval_scenarios.py`, and README. Inject network transport for offline tests. Add the service's Python source exceptions to `.gitignore` and its fast tests to `.githooks/pre-commit` if budget remains below two seconds locally.
3. Run `python3 -m unittest discover -s services/archive_transfer_r1/tests -q` and `python3 services/archive_transfer_r1/evals/eval_scenarios.py`. Verify reject cases and interruption/resume with local synthetic ZIPs. No model eval applies to deterministic code.
4. Use the four exact URLs/sizes from `data/research/r1-depth-20261102/complete/partial_manifest.json`. New verified-chunk output directory; never overwrite old `.partial` evidence. Bounded transfer workers, measured progress appended to `/tmp/r1-archive-transfer/progress.log`; failed chunks remain retryable and completion is not claimed on failed runs.
5. After full ZIP CRC/hash validation, stream the actual day for schema/time/update-order evidence and bounded numeric replay, clearly label remaining full-day replay/rule-history gaps. Independently review actual outputs. Update R1 research report and commit/push source, tests/evals and compact evidence only.

The existing user instruction to continue authorizes execution of this public R1 work. No R2, paid API, production changes or trade approval is inferred. Local skill handoff prompts are superseded by the user's request to continue here using available tools.
