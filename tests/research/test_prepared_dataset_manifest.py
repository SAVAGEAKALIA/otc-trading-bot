from datetime import UTC, datetime
import json

from trading_platform.research.prepared_dataset import create_prepared_dataset_manifest
from trading_platform.research.sqlite_export import validate_research_export


def test_model_ready_dataset_gets_immutable_manifest(tmp_path) -> None:
    dataset = tmp_path / "enriched" / "enriched_candles.parquet"
    dataset.parent.mkdir()
    dataset.write_bytes(b"causal-feature-matrix")

    manifest_path = create_prepared_dataset_manifest(
        dataset_id="otc-enriched-v1",
        root=tmp_path,
        files={"enriched_candles": dataset},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    manifest = validate_research_export(manifest_path)

    assert manifest["dataset_id"] == "otc-enriched-v1"
    assert manifest["records"][0]["role"] == "enriched_candles"


def test_manifest_validation_detects_changed_feature_matrix(tmp_path) -> None:
    dataset = tmp_path / "enriched_candles.parquet"
    dataset.write_bytes(b"before")
    manifest = create_prepared_dataset_manifest(
        dataset_id="otc-enriched-v1",
        root=tmp_path,
        files={"enriched_candles": dataset},
    )
    dataset.write_bytes(b"after")

    try:
        validate_research_export(manifest)
    except ValueError as exc:
        assert "size mismatch" in str(exc) or "checksum mismatch" in str(exc)
    else:
        raise AssertionError("changed feature matrix was accepted")
