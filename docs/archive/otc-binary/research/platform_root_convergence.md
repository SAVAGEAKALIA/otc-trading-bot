# Trading-platform root convergence

`src/trading_platform` is the authoritative code boundary and the intended
future project root. New business logic belongs there. The repository root,
`iqoption_bot`, and `iqoptionapi` remain migration inputs or compatibility
surfaces; their continued existence does not grant them ownership of new risk,
execution, research, model, agent, or state-management behavior.

## Enforced dependency direction

```text
legacy/root caller -> trading_platform port or application entry point
trading_platform   -X-> legacy/root implementation
```

The platform may define a protocol implemented by a legacy object and may
receive that implementation through dependency injection. It must not import
`iqoption_bot` or a root shim. `tests/test_platform_package_boundaries.py`
enforces this rule. Compatibility identity tests ensure the migrated root
commands continue to delegate to their platform-owned implementations.

New Bybit work begins exclusively under `src/trading_platform/brokers/bybit`.
The read-only instrument/ticker normalizers and shared immutable instrument and
market-data records have no root or `iqoption_bot` counterpart; future
transport and account-read work must preserve that package boundary.
The new Bybit public client depends on an injected transport protocol and
allowlisted endpoint methods; no generic broker request escape hatch or legacy
root wrapper is permitted.
The unsigned HTTP implementation is likewise platform-only, host/path/parameter
allowlisted and contains no credential or signing capability. It must not be
reused as a generic private-endpoint transport when account reads are added.
Bybit clock-offset measurement also remains platform-owned and advisory only;
it cannot mutate the host clock or authorize private requests.
The new V5 signer is a platform-only, GET-only constructor for three explicit
account-read endpoints. It has no generic POST method or execution endpoint;
future credential loading must remain outside root and legacy modules.
The corresponding private-read client also remains platform-only and exposes
three named queries rather than a generic signed request method. Retries always
resample clock health and re-sign.
Bybit hedge-mode position records remain adapter-owned until the platform ledger
can represent `positionIdx`; they must not be forced through the legacy
one-position-per-instrument projection and silently overwrite a leg.

## Current root-file migration register

| Root file | Current role | Destination/status |
|---|---|---|
| `training_provenance.py` | Compatibility import | Migrated to `trading_platform.research.training_provenance`; remove after callers move |
| `register_calibration_provenance.py` | Compatibility command | Migrated to `trading_platform.apps.register_calibration`; remove after deployment commands move |
| `generate_otc_shadow_parity_report.py` | Compatibility command | Migrated to `trading_platform.apps.otc_parity_report`; remove after deployment commands move |
| `train_catboost_directional.py` | Transitional trainer | Invoked only through the allowlisted portable `trading_platform.research.train` CLI for new workflows; migrate implementation into the package after parity |
| `train_catboost_gate.py` | Transitional trainer | Invoked only through the allowlisted portable `trading_platform.research.train` CLI for new workflows; migrate implementation into the package after parity |
| `train_candidate_meta_model.py` | Research trainer | Preserve as evidence, then migrate or archive after parity tests |
| `train_regime_mtf_lstm_v5.py` | Transitional trainer with independent calibration/policy/test partitions, strict dataset/artifact provenance and deterministic promotion gates | Available through the allowlisted platform research CLI; validate on Kaggle with PyTorch/ONNX Runtime, build a dedicated four-input runtime adapter, then move implementation into the package |
| `train_trading_model_v3.py` | Runtime-compatible LSTM trainer with independent calibration/policy cohorts, strict checksum provenance and calibration-ID propagation | Available through the allowlisted platform research CLI; validate in Kaggle, register the returned manifest, then move implementation into the package |
| `kaggle_candidate_meta_trainer.py` | Kaggle research trainer | Consolidate into the portable research CLI; do not duplicate into notebooks |
| `kaggle_strategy_independent_tournament.py` | Kaggle research tournament | Consolidate into platform research experiments or archive with results |
| `build_ml_feature_dataset.py` | Compatibility command only | Implementation migrated to `trading_platform.apps.build_ml_feature_dataset`; remove after operator/deployment callers move |
| `harvest_market_data.py` | Legacy collector | Replace through a platform-owned collector app and broker/data ports only after capture parity |
| `main.py` | Legacy OTC composition root | Replace with a platform-owned OTC worker after shadow/practice gates |
| `test_conn.py` | Manual connectivity diagnostic | Replace with an authenticated, practice-only adapter smoke command or archive |

## Migration rules

1. Move one tested vertical slice at a time; do not bulk-rewrite proven code.
2. Establish behavior/parity tests before changing the owning module.
3. Put the authoritative implementation in `trading_platform`.
4. Reduce the old file to argument translation and delegation when compatibility
   is still required.
5. Update Kaggle, Docker, systemd and operator commands to call the package.
6. Delete the facade only after repository and deployment searches show no
   remaining callers.

Moving a file is not sufficient by itself. Dataset schemas, feature order,
calibration semantics, artifact hashes and runtime inference must remain
identical or be deliberately versioned with new validation evidence.
