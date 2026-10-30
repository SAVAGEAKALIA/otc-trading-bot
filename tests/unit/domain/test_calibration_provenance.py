from datetime import timedelta

import pytest

from tests.calibration_fixtures import START, calibration_provenance


def test_provenance_requires_temporally_separated_final_test() -> None:
    item = calibration_provenance()

    assert item.calibration_end < item.test_start
    assert item.test_metrics["brier_score"] == 0.22


def test_overlapping_calibration_and_test_is_rejected() -> None:
    with pytest.raises(ValueError, match="test period"):
        calibration_provenance(test_start=START + timedelta(days=39))


def test_invalid_artifact_hash_is_rejected() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        calibration_provenance(artifact_sha256={"model": "not-a-hash"})


def test_required_probability_metrics_cannot_be_missing() -> None:
    with pytest.raises(ValueError, match="brier_score"):
        calibration_provenance(test_metrics={"log_loss": 0.64})
