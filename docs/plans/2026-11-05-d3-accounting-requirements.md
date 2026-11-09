# D3 accounting and data requirements implementation plan

**Goal:** freeze the user-selected D3 accounting policy and produce a reproducible inventory of conditional orders, valuation windows and missing evidence, before calculating returns or downloading more data.

**Architecture:** one independent, offline `services/spot_trend_r1/` directory owns the versioned accounting contract, requirements planner, tests and evals. It consumes the existing versioned threshold and quote artifacts through explicit JSON boundaries. Root changes are limited to documentation, source visibility and the existing gate hook.

**Tech Stack:** Python standard library, exact rational/decimal arithmetic, UTC datetime, JSON and unittest. Existing services cover acquisition and hypothetical carry economics; neither defines the D3 component accounting contract. Standard data validation and finite-state transitions suffice; no new framework or external service is needed.

The user selected equal initial capital in six independent components, without daily rebalancing, and terminal closing with exit costs. Those are research-policy choices, not a dollar allocation or permission for R2. Actual capital, fees, precision, risk limits and historical information availability remain unset or unverified. User authorization to continue and the repository's parallel critic workflow supersede the planning skill's optional execution-handoff prompt. No separate session or installation is needed.

The independent acceptance reference was written before builders started: `/tmp/r1-d3-accounting/critique/rubric.md`. Its user-choice addendum records both answers. Two competing implementations work in isolated directories under `/tmp/r1-d3-accounting/`; a cold critic selects by correctness and auditability, never by returns.

## Task 1: Define the contract and failing cases

Create `services/spot_trend_r1/contracts/protocol.json`, `services/spot_trend_r1/README.md` and `services/spot_trend_r1/tests/test_plan.py`.

1. Preserve BTC/ETH, the three existing Donchian lookbacks, strict completed-close comparisons, full warm-up and the common development start. Do not retune using observed history.
2. Specify exact initial weights, independent cash and quantity ledgers, idle cash/dust, fee-inclusive entry sizing, actual fee currencies, fixed quantities between fills, no cash recycling and no hidden daily rebalance.
3. Separate the signal target, conditional order, actual fill and unresolved holding. Define bounded retry requirements and failed/partial terminal execution explicitly.
4. Freeze preceding-observation daily marks, the independent USDT/USD requirement, terminal clocks and a post-terminal boundary. October 31 midnight cannot value actions later that morning.
5. Write tests that reject malformed components, dates, policy flags and quote evidence. Test failed/partial orders, repeated signals, allocation conservation and terminal residuals. Run the new gate against an absent or deliberately broken implementation and retain failure evidence under `/tmp/r1-d3-accounting/critique/`.

## Task 2: Build the offline requirements planner

Create `services/spot_trend_r1/plan.py`.

1. Read the contract, `docs/research/crypto-r1-2026-10-31/spot_trend_preview.json` and `spot_quote_checks.json` through validated boundaries. Preserve content hashes and explicit limitations.
2. Generate the conditional full-fill signal trace and the conservative requirements needed when actual fills are unknown. A quoted book is not a fill; a conditional trace cannot prune away unresolved exposure.
3. Generate every daily spot and independent token valuation window, its source archive date and its evidence state. Include flat days and the later ending boundary.
4. Generate terminal execution, reconciliation and residual-exposure requirements. Missing terminal outcomes prevent a flat-ending claim.
5. Serialize deterministically. Report requirements counts and lock blockers, never returns or live readiness.

## Task 3: Evaluate competing variants and reproduce results

Create `services/spot_trend_r1/evals/eval_scenarios.py` and a saved `docs/research/crypto-r1-2026-10-31/d3_requirements.json`.

1. Run each variant's gate and separate generated/adverse eval suite with a 100% critical-pass threshold.
2. Give randomly labeled variants plus the frozen reference to the independent critic. The critic must reproduce the documented command, attack temporal/input/state boundaries and select a concrete winner or reject both.
3. Correct findings and obtain a fresh cold verdict before delivery. Preserve rejected variants and evidence under `/tmp`, not in the repository.
4. Install only the selected implementation. Run its documented CLI twice against unchanged inputs and compare byte-for-byte. Inspect the generated counts and coverage classifications before writing the report.

## Task 4: Integrate and ship

Modify `.gitignore`, `.githooks/pre-commit` and the R1 research index. Add `docs/research/crypto-r1-2026-10-31/d3_accounting_and_requirements.md` and link the detailed contract from the existing experiment specification without changing P1 carry or promoting D3.

1. Ensure service code, tests, evals and its contract remain visible to Git; no raw data, credentials or binaries enter the commit.
2. Add the new local gate to the existing hook. Measure the new unit separately; the inherited full-hook timing concern remains independently documented.
3. Run gates, evals and the documented reproduction. Have the critic review the installed paths and final report.
4. Rate the final artifact after reading the actual diff, commit and push with hooks enabled. Report all remaining evidence blockers and the next smallest useful acquisition/probe. No service restart is needed.

## Installed validation

The cold tournament selected the complete exact-rational implementation. Its contract and planner bytes remained unchanged during integration; its tests, generated evals and linked ten-step workflow were installed together. Added `tests/test_saved_evidence.py` rejects incomplete/stale provenance and permission claims, and `evals/test_full_plan.py` compares the complete saved artifact with fresh canonical output.

All 25 service gate tests passed in 0.81 seconds. All 4,339 critical deterministic eval scenarios passed, including 59 same-module caller mutation cases. Two CLI reproductions matched the saved 892,154-byte requirements file exactly. The full repository hook passed 108 tests in 5.08 seconds; its inherited two-second timing concern remains visible and does not alter the new service's gate budget. Exact evidence is saved under `/tmp/r1-d3-accounting/critique/integration/`.

The [independent installed-deliverable review](/tmp/r1-d3-accounting/critique/integration-final.md) passed on November 7 with 387 independent assertions, 15 controlled-defect cases and unchanged delivery bytes. Its five D3 gate measurements all met the two-second budget. Finish shipping with the fresh-read rating and commit/push verification, keeping hooks enabled. No returns, downloads, R2 run or trading belongs to this step.

The first local shipping run exposed an untracked-file EOF whitespace gap and stopped before commit. The repair adds `delivery.py`, `tests/test_delivery.py` and `evals/delivery_checks.py`, removes only the eval source's extra final blank line, and updates the ten-step workflow. Standard Git now validates all proposed additions before staging, and the helper safely resumes staged task files while preserving the index and refusing unrelated staged paths. It binds both hashes and Git modes. All 27 gate tests and 4,468 eval scenarios pass; gate wall time is 1.88 seconds. Frozen accounting/input/output bytes remain unchanged. Repair evidence and cold review artifacts stay under `/tmp/r1-d3-accounting/critique/shipping-whitespace/`.
