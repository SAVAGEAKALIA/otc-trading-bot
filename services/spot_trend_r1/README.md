# D3 spot accounting requirements

This service turns the frozen threshold preview and quote study into a reproducible accounting contract and data inventory. It computes no historical fill, return, profit, capacity, recommended capital, or R2 authorization. It opens only the two saved JSON reports and its own contract/code. It has no network or execution dependency.

The measurable outcome is an inspectable requirement for every component decision, every candidate execution window, every daily valuation point, and the terminal close, with explicit evidence states and blockers. The standard-library implementation reuses the validated report identities rather than introducing an execution/backtest library.

## Run from the repository root

Set `D3_SERVICE` to the service directory:

```bash
D3_SERVICE=services/spot_trend_r1
python3 "$D3_SERVICE/plan.py" \
  --source-dir docs/research/crypto-r1-2026-10-31 \
  > /tmp/d3-accounting-requirements.json
python3 -m unittest discover -s "$D3_SERVICE/tests" -q
python3 "$D3_SERVICE/evals/eval_scenarios.py"
```

Both CLI paths may be absolute, allowing the command to run from any working directory. Tests/evals run from the repository root by default; set `D3_SOURCE_DIR` to the absolute saved-report directory when running elsewhere. No package installation or service restart is required. A nonzero exit with `INPUT_REJECTED` means the source or contract was rejected, and no successful report is printed.

The gate covers the named policy attacks, representative unknown or missing nested fields, numerical/type aliases, exact time bounds, weights, fee conservation, failure semantics, caller output ownership and saved-artifact integrity/provenance. It also rejects a new-file EOF defect and checks the actual regression eval source before staging. The eval lane runs every contract leaf and container mutation, generated integer-oracle trajectories, calendar boundaries, fee currencies, terminal residues, the complete inventory, same-module caller mutations, semantic mutations through the real CLI, subprocess reproducibility and generated delivery whitespace cases. It compares the saved `d3_requirements.json` byte-for-byte with the freshly generated canonical output and checks all service sources, including untracked files. Its frozen threshold is 100% of critical scenarios. Gate timing excludes neither tests nor fixture loading; keep exhaustive sweeps and expensive full-report/CLI checks in the eval lane. The parent repository hook calls the gate command above before a commit.

`delivery.py` uses the existing Git executable to validate a complete proposed patch with `git apply --check --whitespace=error-all` against a temporary baseline. It changes neither files nor a Git index. This catches new-file whitespace before staging; `git diff --check` alone omits untracked files. The shipping helper must also handle an already-staged task, reject unrelated staged paths, and bind both source hashes and Git file modes before publishing its manifest. Every helper and guard Git read uses `git -c diff.autoRefreshIndex=false` with `GIT_OPTIONAL_LOCKS=0`: optional locks alone let an unstaged diff rewrite zero-stat index entries. The shipping fixtures reset an existing blob with `git update-index --cacheinfo` in a disposable repo and require the actual index plus staged/unstaged diff bytes to stay identical. Temporary-baseline `check_patch` controls also cover the `GIT_DIR`, `GIT_INDEX_FILE` and `GIT_WORK_TREE` exported by commit hooks; they preserve the inherited environment and active hooks. Planner/protocol/input/output bytes remain separate from this delivery check.

To save policy and caller-mutation cases as local evidence:

```bash
python3 "$D3_SERVICE/evals/eval_scenarios.py" \
  --policy-evidence /tmp/d3-policy-mutation-cases.json \
  --ownership-evidence /tmp/d3-output-ownership-cases.json
```

## Supported contract and changes

`--contract` selects an alternative serialization of the supported contract. It is not a policy-override mechanism. `validate_contract` checks the complete typed JSON tree against the code-pinned `SUPPORTED_CONTRACT_SEMANTIC_SHA256` before interpreting any policy field or opening a source report. Every policy leaf, metadata field, source identity, array position and key is covered. Added keys are rejected at the top level and inside nested objects. Changed retry, transfer, terminal or B0 rules, invented fees, numerical account facts and additional authorization fields are rejected even when the checked clocks or weights still match.

Object-key order, indentation and JSON escape spelling may differ. Array order and scalar types remain part of the contract: integer `60000`, floating `60000.0`, boolean `true` and string `"60000"` are distinct inputs. Duplicate keys and malformed JSON are rejected. An unsupported contract exits 2 with `INPUT_REJECTED` on stderr and empty stdout; it cannot print an altered policy next to a successful fixed inventory.

Any semantic policy or field change requires an explicitly reviewed protocol/code version and matching implementation, tests and evals. Editing `contracts/protocol.json` alone must fail closed. The semantic fingerprint is fixed in code, independent of the caller-selected file. Raw contract bytes are still recorded as `provenance.contract_sha256`; `provenance.contract_semantic_sha256` identifies the supported policy. Equivalent formatting changes the raw provenance and full body hash while leaving requirements and the semantic fingerprint unchanged. Neither hash authorizes R2 or live execution.

The reusable [ten-step contract and exact-arithmetic workflow](workflows/contract_policy_failure_prevention.md) records the failure class, regression commands, generated eval coverage and review evidence needed for future changes.

## Frozen financial policy

`contracts/protocol.json` carries the policy and input SHA256 identities. The user selected six equal **initial** components: BTCUSDT and ETHUSDT, each with 20/10, 55/20 and 100/50 Donchian lookbacks. Each starts with exactly `C/6` USDT; each symbol totals exactly `C/2`. `C` remains unknown. These are rational subledger partitions, not six rounded transfers or a dollar recommendation. All six begin flat after the common 100-bar warmup. No daily rebalancing, component transfers, recycling another component's idle cash, shorting or leverage is permitted.

Each component keeps its own idle cash, proceeds, dust and holdings. Re-entry uses only its then-available cash. Quantity stays unchanged between actual reconciled fills and explicitly recorded costs. Entry sizing is fee-inclusive and rounded down only using verified instrument filters; total debits cannot exceed owned balances. Sell sizing also reserves any base-denominated fee. Minimum/precision failure produces no fill. Base fees reduce base, quote fees reduce USDT, and third-currency fees require funded owned balances and independent currency valuation. Unresolved third-currency funding blocks the cohort. Fees have unique event identities and are charged once in their actual denomination. Spread already in the execution price is not charged again. All holdings, cash and dust count toward total capital.

The small `Ledger`/`apply_fill` helpers exist only to verify these conservation rules with synthetic inputs. `BASE` is a synthetic base-unit label in those tests, not a proposed fee-report currency. Historical fill outcome data is neither accepted nor simulated by the CLI. `reconcile_components` requires exactly the six component identities and sums cash and symbol quantities without valuing them.

Balances, consideration and actual-currency fees use exact `Fraction` arithmetic. Fully paid means every positive over-cash debit is rejected, however small; every positive base fee reduces net base by precisely that amount. Finite-context decimal rounding can make a debit just above one look equal to one or erase a tiny fee. Increasing a context precision cannot prove conservation for an unrestricted accepted coefficient length. Gate regressions use a `1/10^80` overdraft and fee, and generated evals cover neighboring magnitudes around 28 digits plus much longer coefficients and repeating `1/7` order grids. Expected balances and grid floors come from independent Fraction/integer oracles. These synthetic checks introduce no account budget, instrument precision assumption or actual sizing recommendation.

## Target, intent and outcome

Completed closes strictly above/below the preceding highs/lows change the signal target. The signal bar is excluded; equality retains target. Every component has 90 decisions regardless of whether a threshold is true. Source fingerprints bind the preview to the existing validated 190-bar history; malformed identities, lookbacks, metadata, dates, duplicates, source hashes and quote clocks are rejected. This service does not repeat raw-candle or archive replay and does not turn retrospective retrieval into historical publication evidence.

`conditional_full_fill_schedule` assumes all prior eligible instructions fully filled. Its state and actions are planning projections, with `actual_quantity: null`. They are not actual holdings. The separate candidate inventory retains **every** entry/exit threshold window, including those suppressed by that projection. Thus a failed earlier entry or exit cannot silently prune later required quotes.

Retry policy is an explicit research planning assumption: one instruction per component per decision, cancel the remainder at the +60-second deadline, no intra-window retry or same-decision re-entry. On a fresh entry condition, enter only when actual base is exactly zero. Any positive partial entry or dust suppresses topping up. On a fresh exit condition, sell remaining base. A hold/equality day produces no retry even if target and actual holdings differ. An unknown outcome blocks actual-state reconstruction. A missed/partial exit never erases exposure.

## Clocks, valuations and terminal close

Signal bars remain August 2 through October 30, 2026. Normal decisions are next-day 00:05 UTC, from August 3 through October 31. Both event time and demonstrated `available_at` must be strictly earlier than the decision. These historical availability proofs are still missing.

Submission is 00:10 UTC. The earliest valid executable quote must be in **[00:10:00, 00:11:00]**, both endpoints inclusive. Buy uses ask; sell uses bid, with separately locked impact. The 15 saved observations demonstrate prefix-replayed top-of-book events inside that interval. They do not demonstrate client receipt, fills, depth/capacity, fee/precision eligibility or full-day semantic validity.

The opening cash mark is August 3 at 00:00 UTC. Daily spot-bid and independent USDT/USD requirements continue through November 2 at 00:00 UTC, including all flat/missing-data days. November 1 at 00:00 is the daily ending mark after the final normal decision can execute. Each mark uses the freshest valid observation in **[valuation − 60 seconds, valuation)**, lower inclusive and upper exclusive; demonstrated availability must precede valuation. Midnight marks therefore map to the previous UTC day's archive. A 00:10 execution probe cannot satisfy a midnight mark. The conservative spot-bid convention is a public planning assumption and is not a liquidation guarantee. Missing evidence leaves an invalid point, never a forward-filled value or deleted day.

The user selected a terminal close with exit costs. Its separate decision is November 1 at 00:05, submission 00:10 and inclusive deadline 00:11. All six components get terminal sell requirements, conditional on actual remaining base, with fresh bid/depth/fee/outcome evidence. The closing valuation is November 2 at 00:00, after the terminal deadline. A valid flat ending requires zero actual base, including dust, reconciled outcomes and all costs and marks. Failed/partial closure, unknown outcomes or untradeable dust retain exposure and produce `blocked_unresolved_continuation`. Daily marking then remains an open conditional obligation beyond the planned endpoint until separately authorized resolution. There is no automatic trading retry or silently extended execution window.

USDT-unit and USD-marked accounts remain distinct. Both strategy and B0 require the same independent USDT/USD source and timestamp at opening, each day and closing. A fixed one-dollar token mark is forbidden. Provider/method and all numerical capital, fees, filters, impact, operating costs, tax, custody and live risk budgets remain unresolved. None is replaced with a convenient zero.

## Reading the output

`counts` is generated from the requirements. `boundaries` exposes the final normal decision, terminal clocks and ending valuations. Purpose groups separate signal contents, historical availability, candidate execution, daily spot marks, independent token marks, terminal execution, account facts, actual outcomes and unresolved continuation. Each item records its exact window, source/category, purpose, scenario, evidence state, blockers and whether existing saved evidence can satisfy it.

`local_coverage_unknown` means uninspected coverage, not proof that an archive is absent. The planner records saved archive identities but does not stat, rehash or download raw files. Content provenance, prefix replay, full-day semantics, availability, capacity and fills are distinct claims. A source filename is a reference, not evidence that all purposes are satisfied by it.

Serialization is sorted compact JSON with one final newline. It contains no current timestamp or machine-specific source path. `provenance` hashes raw contract, planner and input bytes; `requirements_sha256` hashes the requirement groups; `deterministic_body_sha256` hashes the complete output before that final field is added. Identical bytes produce identical output. These are reproducibility hashes, **not a final R2 experiment lock**. Any policy or source change requires an explicit version/review before a future return experiment. The carry fee gate and R2 authorization remain unchanged.
