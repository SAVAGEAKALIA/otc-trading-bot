# D3 allocation, accounting and data requirements

November 5, 2026. D3 now has a versioned accounting contract and a deterministic requirements planner. The user selected six equal initial component budgets, no daily rebalancing, and terminal closing with exit costs. The signal parameters and historical timing remain those of `r1-spec-1`. This is descriptive development research; capital remains unspecified and the final R2 experiment lock remains blocked.

The [contract](../../../services/spot_trend_r1/contracts/protocol.json), [service README](../../../services/spot_trend_r1/README.md) and [generated requirements](d3_requirements.json) define the complete policy. The planner consumes only the two frozen [signal](spot_trend_preview.json) and [quote](spot_quote_checks.json) reports. Their exact bytes, the contract and planner code are hashed in its provenance. The requirements hash identifies this inventory; it is not an R2 experiment lock.

## Allocation and actual ownership

BTCUSDT and ETHUSDT each have 20/10, 55/20 and 100/50 Donchian components. Every component starts flat with exactly one sixth of unknown initial USDT capital; each symbol starts with one half. Rational ownership claims sum exactly. These are normalized accounting partitions, not a dollar recommendation or six rounded funding transfers.

Each component retains its own cash, sale proceeds, dust and holdings. Re-entry spends only its available cash. There are no component transfers, daily weight restoration, external rescue funds, shorting or leverage. Held base quantity changes only through actual reconciled fills or actual-currency cost postings.

Entry sizing includes all debits and verified instrument rounding; an order cannot spend more than the component owns. A base fee reduces base; a quote fee reduces USDT. Any third-currency fee requires an owned, attributed balance and independent currency valuation. Fees are charged once, spread already in the execution price is not charged again, and unsellable dust stays owned. Unknown capital, precision, fee rounding and cost facts cannot be replaced by zero.

The supported semantic contract is pinned in code. Added fields and changed allocation, execution, accounting or permission rules fail closed before a successful report is produced. Whitespace/key ordering can change the raw provenance hash without changing the semantic policy. Any policy revision requires an explicit version and code review.

## Targets, instructions and fills

Strict completed-close entry/exit conditions change the signal target. Equality retains it. The signal bar is excluded from its lookbacks; warm-up does not reconstruct earlier holdings.

The full-fill projection contains 540 component decisions over 90 normal decision days. Assuming every eligible prior instruction fills completely, it produces 17 ordinary instructions: 9 buys and 8 sells. Its only open terminal component is `BTCUSDT:100/50`. Actual quantity remains null in this trace, so these are conditional instructions rather than executed trades.

The conservative inventory retains all 30 threshold candidates, including those suppressed by the full-fill projection. They reuse the 15 observed symbol/date quote windows. Repeated entry while holding any positive base, including a partial entry, does not top up. A failed entry remains flat. A failed or partial exit preserves remaining base.

The retry rule is a disclosed public planning assumption: at most one instruction per component per decision, cancel the remainder at the 60-second deadline, and retry only on a subsequent true entry/exit condition with the eligible actual holding. Hold/equality days do not create a retry. No same-decision re-entry is permitted. Unknown outcomes block actual-state reconstruction; an observed quote cannot create or erase holdings.

## Exact UTC boundaries

| Boundary | UTC |
|---|---|
| First signal bar | 2026-08-02 |
| Last signal bar | 2026-10-30 |
| Opening cash valuation | 2026-08-03T00:00:00.000Z |
| First normal decision | 2026-08-03T00:05:00.000Z |
| Last normal decision | 2026-10-31T00:05:00.000Z |
| Daily mark after final normal execution | 2026-11-01T00:00:00.000Z |
| Terminal decision | 2026-11-01T00:05:00.000Z |
| Terminal submission | 2026-11-01T00:10:00.000Z |
| Terminal deadline, inclusive | 2026-11-01T00:11:00.000Z |
| Closing valuation | 2026-11-02T00:00:00.000Z |

Normal decisions remain at 00:05 UTC, submissions at 00:10, and executable quotes in [00:10:00, 00:11:00], inclusive. Buy uses ask; sell uses bid, with separately locked incremental impact. Signal event time and demonstrated historical availability must both precede the decision. Retrospective candle acquisition proves contents, not historical publication timing.

The public spot-mark assumption uses the freshest valid preceding bid in [valuation minus 60 seconds, valuation), including the lower bound and excluding the valuation instant. Demonstrated availability must precede valuation. Midnight marks therefore need the preceding UTC day's archive. A 00:10 observation cannot satisfy them. Every daily point remains present, including flat and missing-data days; missing evidence leaves an invalid point.

There are 92 daily points through the closing valuation. Both spot symbols and an independent USDT/USD mark are required at each point, irrespective of projected holdings. Strategy and B0 use the same token source and clock; fixed USDT/USD parity is forbidden. The existing hourly independent-token feasibility dataset does not demonstrate these 60-second preceding marks.

The terminal schedule is a disclosed public planning clock after the final normal decision. All 6 components have a conditional sell requirement because actual residuals are unknown. Successful closing requires zero actual base, including dust, and reconciled fills, costs and marks. A failed or partial sale stays unresolved and requires continuing daily marks until separately authorized resolution. Neither automatic trading retries nor an assumed flat endpoint are allowed.

## Generated inventory

The planner emits 710 requirements, grouped by purpose:

| Purpose | Requirements |
|---|---:|
| actual fill outcomes and reconciliation | 36 |
| conditional order execution | 30 |
| daily independent token valuation | 92 |
| daily spot valuation | 184 |
| historical availability | 180 |
| signal history | 180 |
| sizing fees precision | 1 |
| terminal execution | 6 |
| unresolved continuation | 1 |

Every row carries a source/category, exact window where applicable, reason, scenario, evidence state, blockers and whether existing evidence can satisfy it. Signal contents, historical availability, quotes, full-day replay, depth/capacity, actual outcomes and account facts remain separate evidence claims.

All supplied quote observations passed the earlier prefix replay study. This planner verifies the saved report identity and schema; it does not reopen or rehash archive payloads. The local metadata inventory records 4 saved spot full-day reports and 17 present archives that can inform later probes. Exact preceding-midnight prices verified by that inventory: 0. Terminal sell windows verified: 0. Uninspected coverage remains unknown.

## What still blocks a return experiment

| Missing input or evidence | Consequence / next step |
|---|---|
| Historical candle publication/receipt before 00:05 | Contents alone cannot establish information eligibility; obtain historical availability evidence or retain a hypothetical classification |
| Daily preceding spot bids and their availability | Probe existing local archives first; preserve missing points and residual exposure |
| Independent USDT/USD marks within the same 60-second preceding windows | Select and verify an independent source/method; hourly feasibility is insufficient |
| Actual outcomes, depth, impact, fees, precision and minimums | A quote does not prove a fill or capacity; resolve before execution accounting |
| Capital, account/product eligibility, costs, custody, taxes and loss budgets | Values remain null/pending; no account-specific economic or risk claim |
| Terminal outcomes and residual reconciliation | Missing or incomplete closure prevents a successful flat ending |

Carry remains subject to its separate [account-fee decision](fee_ladder_decision.md). D3 is not another confirmatory winner. None of this evidence begins R2.

## Reproduce and review

Run from the repository root:

```bash
python3 services/spot_trend_r1/plan.py \
  --source-dir docs/research/crypto-r1-2026-10-31 \
  > /tmp/d3-requirements-reproduced.json
cmp docs/research/crypto-r1-2026-10-31/d3_requirements.json \
  /tmp/d3-requirements-reproduced.json
python3 -m unittest discover -s services/spot_trend_r1/tests -q
python3 services/spot_trend_r1/evals/eval_scenarios.py
```

The new gate is wired into `.githooks/pre-commit`; deterministic evals remain a separate pre-ship lane with every critical scenario required to pass. The competing originals were independently rejected for incomplete policy freezing and inexact Decimal postings. The selected exact-rational implementation retains regressions and generated evals for both failures, plus same-module caller mutation checks and saved-artifact integrity/reproduction checks. Its README codifies the reusable failure-prevention workflow.

Installed validation on November 5 passed all 25 D3 gate tests in 0.81 seconds and all 4,339 critical eval scenarios with zero failures. Coverage includes 1,337 policy mutations, 840 exact-arithmetic cases, 59 caller-mutation cases and 7 whole-report checks. Two CLI runs matched the saved 892,154-byte artifact exactly. The requirements SHA256 is `c1e8a38d930b8f8bb02f5d80d72df1fc74bb7052f63833d34a1dc70e6fd41195`.

The complete repository hook passed all 108 tests in 5.08 seconds. **P2 timing concern:** the full hook remains above its two-second target; the unchanged baseline took 6.39 seconds before D3 integration. The new service meets its own budget. Profile the existing gate suites separately before changing the hook. Exact command outputs, timings, hashes and per-case eval evidence are in [installed validation](/tmp/r1-d3-accounting/critique/integration/validation.json).

The [cold tournament verdict](/tmp/r1-d3-accounting/critique/tournament-round-2.md) accepted the selected implementation against the frozen reference. The [installed cold review](/tmp/r1-d3-accounting/critique/integration-final.md) passed on November 7: 387 independent assertions and 15 controlled-defect cases verified the inventory and safeguards. All five independently timed D3 gates stayed below two seconds. The [review evidence](/tmp/r1-d3-accounting/critique/integration-review/final-preservation-and-evidence.json) records unchanged delivery bytes, exact reproduction and named regression failures. The [local evidence report](/tmp/r1-d3-accounting/critique/local-evidence/report.md) maps reusable files without opening archive bytes.

The first local shipping attempt stopped before commit because the newly added eval source ended with an extra blank line. Earlier unstaged checks had omitted that new file. The November 7 repair removes the extra line and validates the complete proposed patch with Git's strict whitespace check before staging. The helper now accepts the task's already-staged subset, takes baseline files and modes from HEAD, preserves the live index, and binds source hashes plus Git file modes. Planner, protocol, frozen inputs and generated requirements remain byte-identical.

Repair validation passed 27 service gate tests in 1.88 seconds and all 4,468 critical eval scenarios, including 129 delivery whitespace/source cases. The [repair gate and eval evidence](/tmp/r1-d3-accounting/critique/shipping-whitespace/) includes the original red EOF regression. The full source sweep remains in the periodic lane; the gate checks the actual regression eval source and the new-file rejection rule. Saved-evidence negative fixtures now copy only changed containers, retaining every assertion while reducing gate work. Local commit/push uses the refreshed `/tmp/r1-d3-accounting/finish-d3.sh`; hooks remain enabled.

No service restart is needed. Next, inspect member/checkpoint metadata for the existing August 2 ETH spot archive, then probe its final minute for the August 3 midnight bid. Obtain independent token and historical availability evidence before expanding acquisition.
