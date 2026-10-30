import json

import pytest

from trading_platform.apps.register_calibration import load_and_verify
from tests.calibration_fixtures import calibration_provenance


def test_manifest_registration_verifies_artifact_bytes(tmp_path) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(b"verified-model")
    import hashlib

    item = calibration_provenance(
        artifact_sha256={"model": hashlib.sha256(model.read_bytes()).hexdigest()}
    )
    manifest = tmp_path / "calibration.json"
    manifest.write_text(json.dumps(item.to_record()), encoding="utf-8")

    loaded = load_and_verify(manifest, {"model": model})

    assert loaded == item


def test_changed_artifact_is_rejected_before_database_access(tmp_path) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(b"changed-model")
    item = calibration_provenance(artifact_sha256={"model": "b" * 64})
    manifest = tmp_path / "calibration.json"
    manifest.write_text(json.dumps(item.to_record()), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_and_verify(manifest, {"model": model})


def test_every_manifest_artifact_must_be_supplied(tmp_path) -> None:
    item = calibration_provenance()
    manifest = tmp_path / "calibration.json"
    manifest.write_text(json.dumps(item.to_record()), encoding="utf-8")

    with pytest.raises(ValueError, match="missing artifact paths"):
        load_and_verify(manifest, {})
