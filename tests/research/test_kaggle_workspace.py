import hashlib
import importlib.util
import json
from pathlib import Path

from trading_platform.research.kaggle_workspace import (
    discover_bundle,
    prepare_kaggle_workspace,
)
from trading_platform.research.manual_kaggle_bundle import prepare_bundle_from_export


def make_bundle(tmp_path: Path) -> Path:
    export = tmp_path / "export"
    table = export / "quote_samples"
    table.mkdir(parents=True)
    part = table / "part-00001.parquet"
    part.write_bytes(b"parquet-fixture")
    manifest = export / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "sqlite_research_export_v1",
                "collector_schema_version": "fixture-v1",
                "records": [
                    {
                        "path": "quote_samples/part-00001.parquet",
                        "size": part.stat().st_size,
                        "sha256": hashlib.sha256(part.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    platform = tmp_path / "trading_platform"
    platform.mkdir(parents=True)
    (platform / "__init__.py").write_text("", encoding="utf-8")
    trainer = tmp_path / "train.py"
    trainer.write_text("print('train')\n", encoding="utf-8")
    return prepare_bundle_from_export(
        dataset_id="fixture-v1",
        export_manifest=manifest,
        output_root=tmp_path / "mounted" / "owner" / "dataset-name",
        platform_root=platform,
        trainer=trainer,
        max_part_size_mb=1,
    )


def test_discovers_bundle_without_username_specific_path_and_extracts(tmp_path) -> None:
    bundle = make_bundle(tmp_path)

    discovered = discover_bundle(tmp_path / "mounted", "fixture-v1")
    result = prepare_kaggle_workspace(
        bundle=discovered, working_root=tmp_path / "working"
    )

    assert discovered == bundle
    assert result["collector_schema_version"] == "fixture-v1"
    assert (
        tmp_path
        / "working/dataset/data/quote_samples/part-00001.parquet"
    ).read_bytes() == b"parquet-fixture"
    assert (tmp_path / "working/platform/trading_platform/__init__.py").is_file()


def test_notebook_bootstrap_verifies_source_then_loads_platform(tmp_path) -> None:
    make_bundle(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "kaggle_otc_training", Path("notebooks/kaggle_otc_training.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    result = module.bootstrap(
        tmp_path / "mounted", tmp_path / "notebook-working", "fixture-v1"
    )

    assert result["dataset_id"] == "fixture-v1"
    assert (tmp_path / "notebook-working/workspace.json").is_file()
