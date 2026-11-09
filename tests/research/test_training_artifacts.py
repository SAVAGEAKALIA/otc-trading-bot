from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import zipfile

import pytest

from trading_platform.research.training_artifacts import (
    package_training_artifacts,
    validate_training_artifacts,
)
from trading_platform.research.training_provenance import build_calibration_manifest


def make_artifacts(root: Path, metadata_id: str = "matching") -> Path:
    root.mkdir()
    model = root / "model.cbm"
    calibrator = root / "calibrator.joblib"
    model.write_bytes(b"model")
    calibrator.write_bytes(b"calibrator")
    start = datetime(2025, 1, 1, tzinfo=UTC)
    windows = {
        "train": (start, start + timedelta(days=2), 10),
        "early_stop": (start + timedelta(days=3), start + timedelta(days=4), 5),
        "calibration": (start + timedelta(days=5), start + timedelta(days=6), 5),
        "policy": (start + timedelta(days=7), start + timedelta(days=8), 5),
        "test": (start + timedelta(days=9), start + timedelta(days=10), 5),
    }
    manifest = build_calibration_manifest(
        model_version="model-v1",
        method="platt",
        target_definition="win",
        dataset_id="dataset-v1",
        dataset_sha256="a" * 64,
        split_windows=windows,
        test_metrics={"brier_score": 0.2, "log_loss": 0.6},
        artifact_paths={"model": model, "calibrator": calibrator},
        offline_deployment_approved=False,
        created_at=start + timedelta(days=11),
    )
    (root / "model_calibration_provenance.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    calibration_id = manifest["calibration_id"] if metadata_id == "matching" else metadata_id
    (root / "model_metadata.json").write_text(
        json.dumps({"calibration_id": calibration_id}), encoding="utf-8"
    )
    return root


def test_validates_directory_and_returns_registration_mapping(tmp_path) -> None:
    report = validate_training_artifacts(make_artifacts(tmp_path / "artifacts"))

    assert report["registration_allowed"] is True
    assert report["installation_allowed"] is False
    assert report["artifact_files"] == {
        "model": "model.cbm",
        "calibrator": "calibrator.joblib",
    }


def test_validates_downloaded_zip_without_extracting(tmp_path) -> None:
    directory = make_artifacts(tmp_path / "artifacts")
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in directory.iterdir():
            bundle.write(path, path.name)

    assert validate_training_artifacts(archive)["model_version"] == "model-v1"


def test_changed_artifact_and_mismatched_metadata_are_rejected(tmp_path) -> None:
    directory = make_artifacts(tmp_path / "artifacts", metadata_id="wrong")
    with pytest.raises(ValueError, match="metadata calibration ID"):
        validate_training_artifacts(directory)

    directory = make_artifacts(tmp_path / "other")
    (directory / "model.cbm").write_bytes(b"changed")
    with pytest.raises(ValueError, match="matched 0 files"):
        validate_training_artifacts(directory)


def test_metadata_cannot_omit_calibration_identity(tmp_path) -> None:
    directory = make_artifacts(tmp_path / "artifacts")
    (directory / "model_metadata.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="must declare"):
        validate_training_artifacts(directory)


def test_packages_deterministic_validated_download_archive(tmp_path) -> None:
    directory = make_artifacts(tmp_path / "artifacts")
    first = package_training_artifacts(directory, tmp_path / "first.zip")
    second = package_training_artifacts(directory, tmp_path / "second.zip")

    assert first["sha256"] == second["sha256"]
    assert (tmp_path / "first.zip").read_bytes() == (tmp_path / "second.zip").read_bytes()
    report = validate_training_artifacts(tmp_path / "first.zip")
    assert report["dataset_id"] == "dataset-v1"
    with zipfile.ZipFile(tmp_path / "first.zip") as archive:
        bundle_manifest = json.loads(archive.read("training_bundle_manifest.json"))
    assert bundle_manifest["schema_version"] == "training_artifact_bundle_v1"
    assert bundle_manifest["dataset_id"] == "dataset-v1"


def test_packaging_rejects_invalid_artifacts_without_creating_archive(tmp_path) -> None:
    directory = make_artifacts(tmp_path / "artifacts")
    (directory / "model.cbm").write_bytes(b"changed")
    destination = tmp_path / "invalid.zip"

    with pytest.raises(ValueError, match="matched 0 files"):
        package_training_artifacts(directory, destination)
    assert not destination.exists()


def test_download_manifest_checksum_mismatch_is_rejected(tmp_path) -> None:
    directory = make_artifacts(tmp_path / "artifacts")
    archive = tmp_path / "valid.zip"
    package_training_artifacts(directory, archive)
    changed = tmp_path / "changed.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(changed, "w") as output:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "training_bundle_manifest.json":
                manifest = json.loads(content)
                manifest["files"][0]["sha256"] = "0" * 64
                content = json.dumps(manifest).encode("utf-8")
            output.writestr(info, content)

    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_training_artifacts(changed)
