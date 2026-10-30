# Model Calibration Provenance

## Safety rule

An OTC probability may pass the new risk path only when its
`calibration_version` resolves to an immutable registered provenance record and
that record has `offline_deployment_approved=true`. A model-reported confidence,
an unregistered version string, or a research-only artifact cannot authorize an
order.

Registration records:

- calibration and model identifiers;
- calibration method and exact target definition;
- dataset identity and SHA-256 digest;
- non-overlapping training, calibration and untouched-test periods;
- sample counts for all three periods;
- untouched-test Brier score and log loss;
- SHA-256 digest for every model/calibrator artifact;
- offline deployment approval and creation time.

The registry does not infer that a model is profitable. Approval only states
that an external research gate accepted the recorded artifact. Expectancy,
payout, exposure and other deterministic risk checks still apply independently.

## Manual registration workflow

1. Train and evaluate without inspecting or retuning against the final test.
2. Produce a provenance JSON matching `CalibrationProvenance.to_record()`.
3. Calculate each artifact hash from the final immutable files.
4. Migrate the target ledger through `0006_calibration_provenance.sql`.
5. Verify and register every named artifact:

```bash
PYTHONPATH=.:src venv/bin/python register_calibration_provenance.py \
  postgresql+psycopg://USER:PASSWORD@HOST/DATABASE \
  calibration-provenance.json \
  --artifact model=catboost_gate.cbm \
  --artifact calibrator=catboost_calibrator.joblib
```

The command hashes files in bounded chunks before opening the database. Missing,
extra or changed artifacts fail registration. Re-registering identical evidence
is idempotent; reusing an identifier for different evidence is rejected.

## Current limitation

The directional and candidate-gate CatBoost trainers now emit this strict
manifest and embed its generated ID into their ordinary metadata. Runtime
propagation is explicit:

- a sole directional CatBoost decision carries its predicted-direction
  probability and calibration ID through the scanner into `TradeRequest`;
- a multi-strategy vote clears directional calibration because agreement
  changes the selected population relative to the model's test cohort;
- when the candidate meta-gate is enforced, its candidate-win probability and
  calibration ID replace the directional probability;
- missing metadata always clears both fields together, causing the new OTC
  risk path to reject rather than substitute generic confidence.

The LSTM and older tournament trainers do not yet emit strict provenance and
are not automatically trusted by the registry. Runtime propagation does not
enable trading by itself: the exact manifest must still be checksum-verified
and registered in the environment-specific ledger.
