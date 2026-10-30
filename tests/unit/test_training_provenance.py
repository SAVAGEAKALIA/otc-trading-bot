from datetime import UTC, datetime, timedelta

import pytest

from trading_platform.domain.calibration import CalibrationProvenance
from trading_platform.research.training_provenance import (
    build_calibration_manifest,
    fingerprint_dataset,
    require_unchanged_dataset,
)


def test_portable_manifest_is_accepted_by_platform_registry_schema(tmp_path) -> None:
    dataset = tmp_path / "dataset.parquet"
    model = tmp_path / "model.cbm"
    calibrator = tmp_path / "calibrator.joblib"
    dataset.write_bytes(b"dataset")
    model.write_bytes(b"model")
    calibrator.write_bytes(b"calibrator")
    dataset_fingerprint = fingerprint_dataset(dataset)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    windows = {
        "train": (start, start + timedelta(days=10), 100),
        "early_stop": (start + timedelta(days=11), start + timedelta(days=12), 20),
        "calibration": (start + timedelta(days=13), start + timedelta(days=14), 20),
        "policy": (start + timedelta(days=15), start + timedelta(days=16), 20),
        "test": (start + timedelta(days=17), start + timedelta(days=18), 30),
    }

    manifest = build_calibration_manifest(
        model_version="model-v1",
        method="platt_logistic",
        target_definition="fixed-expiry win",
        dataset_id="dataset-v1",
        dataset_sha256=str(dataset_fingerprint["sha256"]),
        split_windows=windows,
        test_metrics={"brier_score": 0.2, "log_loss": 0.6},
        artifact_paths={"model": model, "calibrator": calibrator},
        offline_deployment_approved=False,
        created_at=start + timedelta(days=19),
    )

    parsed = CalibrationProvenance.from_record(manifest)
    assert parsed.model_version == "model-v1"
    assert parsed.offline_deployment_approved is False
    assert set(parsed.artifact_sha256) == {"model", "calibrator"}


def test_dataset_change_is_detected_after_hashing(tmp_path) -> None:
    dataset = tmp_path / "dataset.parquet"
    dataset.write_bytes(b"before")
    fingerprint = fingerprint_dataset(dataset)
    dataset.write_bytes(b"after-with-different-size")

    try:
        require_unchanged_dataset(dataset, fingerprint)
    except RuntimeError as exc:
        assert "changed during model training" in str(exc)
    else:
        raise AssertionError("changed dataset was accepted")


def test_manifest_refuses_overlapping_final_test(tmp_path) -> None:
    model = tmp_path / "model.cbm"
    model.write_bytes(b"model")
    start = datetime(2025, 1, 1, tzinfo=UTC)
    windows = {
        "train": (start, start + timedelta(days=2), 10),
        "early_stop": (start + timedelta(days=3), start + timedelta(days=4), 5),
        "calibration": (start + timedelta(days=5), start + timedelta(days=6), 5),
        "policy": (start + timedelta(days=7), start + timedelta(days=9), 5),
        "test": (start + timedelta(days=8), start + timedelta(days=10), 5),
    }

    with pytest.raises(ValueError, match="untouched test"):
        build_calibration_manifest(
            model_version="model-v1",
            method="platt_logistic",
            target_definition="target",
            dataset_id="dataset-v1",
            dataset_sha256="a" * 64,
            split_windows=windows,
            test_metrics={"brier_score": 0.2, "log_loss": 0.6},
            artifact_paths={"model": model},
            offline_deployment_approved=False,
            created_at=start + timedelta(days=11),
        )
