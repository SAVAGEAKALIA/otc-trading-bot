from datetime import UTC, datetime, timedelta

from trading_platform.domain.calibration import CalibrationProvenance


START = datetime(2025, 1, 1, tzinfo=UTC)


def calibration_provenance(**overrides) -> CalibrationProvenance:
    values = {
        "calibration_id": "catboost-gate-cal-v1",
        "model_version": "catboost-gate-v1",
        "method": "platt_logistic",
        "target_definition": "candidate_wins_at_fixed_expiry",
        "dataset_id": "otc-candidates-2025q1",
        "dataset_sha256": "a" * 64,
        "training_start": START,
        "training_end": START + timedelta(days=30),
        "calibration_start": START + timedelta(days=31),
        "calibration_end": START + timedelta(days=40),
        "test_start": START + timedelta(days=41),
        "test_end": START + timedelta(days=50),
        "sample_counts": {"training": 1000, "calibration": 200, "test": 200},
        "test_metrics": {"brier_score": 0.22, "log_loss": 0.64},
        "artifact_sha256": {"model": "b" * 64, "calibrator": "c" * 64},
        "offline_deployment_approved": True,
        "created_at": START + timedelta(days=51),
    }
    values.update(overrides)
    return CalibrationProvenance(**values)
