# Binary OTC training continuation

Goal: finish the interrupted causal data repair and fixed logistic/CatBoost comparison, then reproduce it in a private free Kaggle CPU job. No accepted-trade or live-capital claim can follow from received price proxies.

Architecture: `contracts/otc_v1` provides immutable source/cash records; `services/otc_observer` audits and exports received observations; `services/otc_research` creates labels, fits fixed models and evaluates fixed selection policies. Kaggle tooling only packages admitted CSV, manifest and trainer.

Stack: Python stdlib SQLite/Decimal/dataclasses plus the already-installed pandas, scikit-learn and CatBoost.

Frozen acceptance reference: `/tmp/binary-training/critique/reference.md`. The existing A/B dataset tournament has artifact-level attacker checks in `/tmp/binary-training/critique/dataset-adversarial-results.json`. No builder grades its own output.

1. Recover nonignored source from the app's archive snapshot `ef91ea3`; restore ignored tests from review artifacts and add scoped ignore exceptions.
2. Repair the winning causal dataset implementation and re-run the exact adversarial cases, including same-receipt batches, bounded values, future payout and other-asset labels.
3. Export two fixed assets on a UTC 120-second decision grid. Keep every gap, unresolved outcome and tie. Record raw hash, quarantine counts, config, lineage and unsafe legacy payout joins.
4. Repair impossible feature ages, retain training/early-stop/calibration/policy/diagnostic separation, and verify saved-model prediction/selection parity. Compare two models at three predeclared thresholds each.
5. Obtain a fresh independent cold critic verdict for contracts, source construction, training, documentation and private upload controls. Rework named failures before real-data fitting or upload.
6. Attempt admission of the historical data locally. If coverage fails, record BLOCKED before fitting/upload and preserve the frozen scope. Run the minimal private Kaggle CPU package only for a separately registered admitted cohort; monitor server states, download and hash-verify outputs. All numerical outcomes remain exploratory.
7. Save a plain-language report with both models' trade counts, win/loss/tie/unresolved counts and per-stake return. Select development preference only from the policy partition. Existing final-period labels are spent diagnostic evidence.
8. Rate the final artifact, commit all source/tests/evals/docs with hooks, push a dedicated `codex/` branch, report restart requirements.

Fixed import settings: EURUSD-OTC and GBPUSD-OTC, explicit assumed turbo-option product, receiver UTC, 120-second hypothetical expiry, full-refund tie scenario, zero modeled acceptance delay, 2000ms entry wait/cutoff, quote age 5000ms, mood age60000ms, payout age600000ms, lookback60000ms, absolute clock-offset/source-age quarantine15000ms. Terminal is last received quote at or before expiry, never source settlement evidence or interpolation.

Approval service: the protected-worktree copy encountered a 503 review-service outage. Continue authorized research in `/tmp` while that is unresolved; do not bypass the protected-path approval. Git saving remains an explicit final task.

Actual outcome: historical admission failed on early=0; no fit or Kaggle upload occurred. Saviour selected continuous fresh quote collection. Protected worktree writes succeeded through the approval tool on retry. The original crypto checkout remains untouched.
