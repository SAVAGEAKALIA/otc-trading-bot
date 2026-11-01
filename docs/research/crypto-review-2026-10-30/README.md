# Crypto proposal review, 2026-10-30

Read [the revised plan](../../plans/2026-10-30-crypto-plan.md) first. This package completes a public-source and existing-data review, not a strategy implementation or authorization to trade. Nigeria residence is confirmed. Capital, loss limits and the benchmark remain user-configurable and unset.

## Findings and artifacts

| Artifact | Purpose |
|---|---|
| [carry_audit.md](carry_audit.md) | Raw-data provenance, replicated returns, capital denominator, signal/cost defects and literature |
| [carry_audit.py](carry_audit.py) | Standard-library reproduction and coverage diagnostic; not a trading simulator |
| [carry_audit_results.json](carry_audit_results.json) | Reproducible computed evidence for the recovered 121,328-row snapshot |
| [carry_audit_test.py](carry_audit_test.py) | Five deterministic gate tests plus three scenario evals |
| [venue_research.md](venue_research.md) | Claim-by-claim primary-source ledger, Nigeria and product eligibility, custody failure modes |
| [execution_research.md](execution_research.md) | Framework corrections, inspected code, recovery contract and agent isolation |
| [ambition.md](ambition.md) | Goal, research method and rewritten ambitious brief |

The central result: the old table reproduces but cannot establish portfolio profitability. Its funding-only annualized rates use hedged notional, omit several economic costs and do not model liquidation or venue loss. Both the original report and the new JSON diagnostic reproduced byte-for-byte in this review. All eight gate/scenario tests passed. These checks validate diagnostic arithmetic and timing, not future returns.

## Reproduce

Run from the repository root. The new diagnostic and tests require Python's standard library only. The old report uses the existing `venv` dependencies.

```bash
python3 docs/research/crypto-review-2026-10-30/carry_audit_test.py

CRYPTO_FUNDING_INPUT='data/research/archive/1969cf4f62d913527383ac66875d9f23efd4fddcf9b7d7bb7a8994a46e137a1a.json'
python3 docs/research/crypto-review-2026-10-30/carry_audit.py "$CRYPTO_FUNDING_INPUT" > /tmp/crypto-carry-audit.json
cmp docs/research/crypto-review-2026-10-30/carry_audit_results.json /tmp/crypto-carry-audit.json
venv/bin/python docs/research/crypto-evidence-2026-10-30/realized_carry.py "$CRYPTO_FUNDING_INPUT" 0.08
```

`cmp` exits zero without output when the snapshot reproduction matches. The input SHA256 must be `1969cf4f62d913527383ac66875d9f23efd4fddcf9b7d7bb7a8994a46e137a1a`. The script reports its actual hash. Raw market data is not committed. R1 follow-up preserved the exact snapshot in content-addressed local storage outside `/tmp`; see [archive manifest](../crypto-r1-2026-10-31/archive_manifest.json). This is local-only, not an off-host backup. If unavailable, the original public collector can fetch a **new** snapshot, but it will not reproduce this exact hash or end date. Preserve an off-host copy through an approved storage route before long-term reliance; this task did not upload the data. No credentials are required for this diagnostic.

The original report's byte comparison also used the local, untracked `docs/research/crypto-evidence-2026-10-30/realized_carry_report.txt`. The new committed JSON provides the portable computed reference; the original local text file is not required for the commands above.

## Research evaluation and limits

Acceptance reference: `/tmp/crypto-plan-review/critique/rubric.md`. Independent review evidence belongs in `/tmp/crypto-plan-review/critique/`, not the repository. The rubric checks source support, all-capital economics, honest holdouts, Nigeria eligibility, recoverable execution, cash competition and explicit approvals.

This task ran deterministic diagnostic tests and scenario evals. It did not run paid Claude evals, full portfolio backtests, live orders, account entitlement checks or prospective trials. Those are not silently claimed as complete. The public sources are linked in each report; missing account permissions, current fee tiers and bank/benchmark access remain admission gates. Conflicting ADL headline wording in the paper is explicitly retained as a source limitation rather than resolved by assertion.

## Reusable failure-prevention checklist

Apply this to subsequent strategy proposals before reporting an APR or selecting a venue:

1. Preserve the exact raw-data hash, coverage and retrieval date.
2. Identify whether the claim measures funding, trade P&L or total investor return.
3. State the capital denominator and model reserve/idle capital.
4. Match the proposed signal and cost rule to the code actually run.
5. Prove decision timestamps precede execution and eligible settlement events.
6. Mark previously inspected periods as development data.
7. Reconcile every material source claim, including contradictions within a source.
8. Treat access, account entitlement and regulatory permission as separate checks.
9. Run arithmetic/timing tests plus adverse scenario evals; record failures.
10. Obtain a cold critic verdict and preserve the evidence before promotion.

No service restart is needed. Next decision: whether to authorize the bounded R1 research implementation in the revised plan.
