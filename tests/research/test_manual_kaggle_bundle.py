from datetime import UTC, datetime
import json
from pathlib import Path
import zipfile

import pytest
import yaml

from trading_platform.research.manual_kaggle_bundle import (
    prepare_bundle_from_export,
    prepare_manual_bundle,
    validate_manual_bundle,
)


def make_sources(tmp_path: Path):
    data = tmp_path / "enriched_candles.parquet"
    data.write_bytes(b"immutable-parquet-fixture")
    platform = tmp_path / "trading_platform"
    platform.mkdir(parents=True)
    (platform / "__init__.py").write_text('"""platform"""\n', encoding="utf-8")
    trainer = tmp_path / "train.py"
    trainer.write_text("print('train')\n", encoding="utf-8")
    return data, platform, trainer


def test_prepare_and_validate_manual_bundle(tmp_path) -> None:
    data, platform, trainer = make_sources(tmp_path)
    bundle = prepare_manual_bundle(
        dataset_id="snapshot-v1",
        data_files=[data],
        output_root=tmp_path / "output",
        platform_root=platform,
        trainer=trainer,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    manifest = validate_manual_bundle(bundle)
    assert manifest["dataset_id"] == "snapshot-v1"
    assert (bundle / "data" / data.name).read_bytes() == data.read_bytes()
    with zipfile.ZipFile(bundle / "platform-source.zip") as archive:
        assert "train.py" in archive.namelist()
        assert "trading_platform/__init__.py" in archive.namelist()


def test_bundled_contract_is_resolved_to_the_export_dataset_id(tmp_path) -> None:
    data, platform, trainer = make_sources(tmp_path)
    contract = tmp_path / "experiment.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": "research_contract_v1",
                "experiment_id": "experiment-v1",
                "trainer": "catboost_directional",
                "dataset_id": "replace-with-export-dataset-id",
                "data": data.name,
                "options": {},
            }
        ),
        encoding="utf-8",
    )

    bundle = prepare_manual_bundle(
        dataset_id="snapshot-v1",
        data_files=[data],
        output_root=tmp_path / "output",
        platform_root=platform,
        trainer=trainer,
        contract=contract,
    )

    with zipfile.ZipFile(bundle / "platform-source.zip") as archive:
        resolved = yaml.safe_load(
            archive.read("configs/research/experiment.yaml").decode("utf-8")
        )
    assert resolved["dataset_id"] == "snapshot-v1"


def test_live_database_and_secret_names_are_rejected(tmp_path) -> None:
    _, platform, trainer = make_sources(tmp_path)
    database = tmp_path / "market.sqlite"
    database.write_bytes(b"do-not-upload")

    with pytest.raises(ValueError, match="forbidden upload filename"):
        prepare_manual_bundle(
            dataset_id="snapshot-v1",
            data_files=[database],
            output_root=tmp_path / "output",
            platform_root=platform,
            trainer=trainer,
        )


def test_corrupted_bundle_fails_checksum_validation(tmp_path) -> None:
    data, platform, trainer = make_sources(tmp_path)
    bundle = prepare_manual_bundle(
        dataset_id="snapshot-v1",
        data_files=[data],
        output_root=tmp_path / "output",
        platform_root=platform,
        trainer=trainer,
    )
    (bundle / "data" / data.name).write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="size mismatch|checksum mismatch"):
        validate_manual_bundle(bundle)


def test_undeclared_file_is_rejected(tmp_path) -> None:
    data, platform, trainer = make_sources(tmp_path)
    bundle = prepare_manual_bundle(
        dataset_id="snapshot-v1",
        data_files=[data],
        output_root=tmp_path / "output",
        platform_root=platform,
        trainer=trainer,
    )
    (bundle / ".env").write_text("SECRET=x", encoding="utf-8")

    with pytest.raises(ValueError, match="undeclared"):
        validate_manual_bundle(bundle)


def test_export_manifest_is_verified_and_grouped_into_parts(tmp_path) -> None:
    _, platform, trainer = make_sources(tmp_path)
    export = tmp_path / "export"
    table = export / "quote_samples"
    table.mkdir(parents=True)
    files = []
    for index in range(3):
        path = table / f"part-{index:05d}.parquet"
        path.write_bytes(bytes([index]) * 600_000)
        import hashlib

        files.append(
            {
                "path": path.relative_to(export).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = export / "manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": "sqlite_research_export_v1", "records": files}),
        encoding="utf-8",
    )

    bundle = prepare_bundle_from_export(
        dataset_id="snapshot-v1",
        export_manifest=manifest,
        output_root=tmp_path / "output",
        platform_root=platform,
        trainer=trainer,
        max_part_size_mb=1,
    )

    archives = sorted(bundle.glob("otc-data-part-*.zip"))
    assert len(archives) == 3
    with zipfile.ZipFile(archives[0]) as archive:
        assert archive.namelist()[0].startswith("data/quote_samples/")
    validate_manual_bundle(bundle)
