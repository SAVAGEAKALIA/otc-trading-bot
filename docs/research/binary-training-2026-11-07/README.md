# Binary OTC training, 7 November 2026

This continuation repairs causal source admission and produces one fixed logistic/CatBoost comparison. All August labels are spent historical evidence. A receiver-clock price outcome cannot establish an accepted binary win rate or broker cash return.

The historical source units are `contracts/otc_v1`, `services/otc_observer` and `services/otc_research`. Each contains deterministic gates and separate eval commands. Fresh collection, safe daily archives and the fixed server comparison use `services/otc_collector`, `services/otc_collection_ops` and `services/otc_fresh_compare`. The original source lock also retains frozen external-adapter reference bytes because they were part of the pre-collection source inventory. External Kaggle review and execution are deferred; the core run does not invoke that adapter.

Source recovery used app snapshot `ef91ea3`; ignored service gates and requirements were restored from review artifacts. Scoped ignore exceptions and precommit gates now keep them in the same commit. The approved plan allows CatBoost to compete directly after causal repair, without requiring a prior profitable linear model.

Frozen experiment and commands are documented in `docs/plans/2026-11-07-binary-training-resume.md`, `docs/plans/2026-11-07-fresh-otc-collection.md`, `services/otc_observer/README.md`, `services/otc_research/DATASET.md` and the fresh services' READMEs.

Evidence stays outside Git:

- `/tmp/binary-training/resume-data/source_snapshot.sqlite.manifest.json`: read-only consistent backup, integrity verdict and raw source hash.
- `/tmp/binary-training/resume-data/observations/`: canonical observations and event lineage.
- `/tmp/binary-training/resume-data/matrix/`: all registered opportunities, their outcome status, observed payout, features, source lineage and audit.
- `/tmp/binary-training/resume-training-eval-r2/eval_report.json`: positive/null/corrupted-data model eval and inference parity.
- `/tmp/binary-training/critique/`: separate cold critic verdicts with hostile probes and hashes.
- `/tmp/binary-training/real-data-admission/report.json`: actual matrix rejected before fitting.
- Kaggle delivery is tested using fabricated fixtures. No real dataset was uploaded and no training job was launched.

No raw database, model weights, binary outputs, account keys or generated bulk records belong in the commit. Historical research is offline. The fresh server workflow is a separate authorized read-only collection process; its independent supervisor owns only its daily producer handoffs.

## Actual data verdict

The fixed historical comparison is **BLOCKED by source coverage**. The matrix preserves 29,632 opportunities: 1,233 resolved (including 4 ties), 3,348 unresolved and 25,051 ineligible. Every resolved example is in the training partition. There are no quote records at all in the registered early-stopping period. Later canonical quotes typically arrive about every 40–50 seconds, outside the 5-second freshness and 2-second entry windows.

The trainer rejects this matrix before fitting: `early needs at least 50 resolved unpurged rows; got 0`. Calibration, policy and diagnostic partitions also have zero resolved rows. Do not relax caps, move the partitions or fill missing prices to manufacture a run. Synthetic positive/null evals verify the software; they do not establish an OTC edge.

On the same fixed decision grid, the audit finds 11,338 old payout joins using future receipts; the repaired joins and all measured feature references use zero future events. Actual broker accepted strikes, binding expiry offers and cash settlements are absent, so actual trading win rate remains unavailable.

Saviour selected fresh continuous quote collection, followed by the original logistic/CatBoost comparison. The fresh recorder is a separate service and registration; the historical result stays blocked. Its schedule and source hashes must be frozen before account connection. Offline implementation requires no service restart.

## Independent review evidence

The final dataset/source boundary passed cold round 3 with 52 gates, 93 independent malformed-manifest probes, four prior-defect regressions and exact parity across all 29,632 historical grid rows: `/tmp/binary-training/critique/resume-dataset-round3/verdict.md`. A separate raw-snapshot review verified all 396,352 raw lineage hashes and reconstructed all opportunities with no future feature references: `/tmp/binary-training/critique/resume-dataset-round2/actual-snapshot-probes.json`. The sole rejected round-2 receipt-bound defect was repaired and retested.

Training passed cold round 2: `/tmp/binary-training/critique/resume-training-round2/verdict.md`. Synthetic positive/null and diagnostic-label rotation checks validate separation and saved inference parity; these are software checks. They supply no measured broker edge.
