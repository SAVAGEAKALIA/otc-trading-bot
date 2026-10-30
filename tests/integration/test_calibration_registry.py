from sqlalchemy import create_engine

from trading_platform.storage.models import metadata
from trading_platform.storage.repository import LedgerRepository

from tests.calibration_fixtures import calibration_provenance


def test_calibration_registration_is_durable_and_idempotent(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'calibration.db'}")
    metadata.create_all(engine)
    repository = LedgerRepository(engine)
    item = calibration_provenance()

    assert repository.register_calibration_provenance(item) is True
    assert repository.register_calibration_provenance(item) is False
    assert repository.get_calibration_provenance(item.calibration_id) == item
    assert repository.calibration_provenance_count() == 1


def test_calibration_identity_cannot_be_reused_for_different_artifact(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'calibration.db'}")
    metadata.create_all(engine)
    repository = LedgerRepository(engine)
    repository.register_calibration_provenance(calibration_provenance())

    try:
        repository.register_calibration_provenance(
            calibration_provenance(
                artifact_sha256={"model": "d" * 64, "calibrator": "c" * 64}
            )
        )
    except ValueError as exc:
        assert "different provenance" in str(exc)
    else:
        raise AssertionError("changed provenance was accepted")
