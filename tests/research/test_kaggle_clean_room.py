import hashlib
import importlib.util
import json
from pathlib import Path

import yaml

from trading_platform.research.manual_kaggle_bundle import prepare_bundle_from_export
from trading_platform.research.training_artifacts import validate_training_artifacts


def test_synthetic_bundle_reaches_validated_download_archive(tmp_path: Path) -> None:
    export = tmp_path / "export"
    partition = export / "quote_samples"
    partition.mkdir(parents=True)
    data = partition / "part-00001.parquet"
    data.write_bytes(b"synthetic-clean-room-data")
    export_manifest = export / "manifest.json"
    export_manifest.write_text(
        json.dumps(
            {
                "schema_version": "sqlite_research_export_v1",
                "collector_schema_version": "synthetic-v1",
                "records": [
                    {
                        "path": data.relative_to(export).as_posix(),
                        "size": data.stat().st_size,
                        "sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    trainer = tmp_path / "train_catboost_directional.py"
    trainer.write_text(
        """from datetime import UTC, datetime, timedelta
import argparse, json
from pathlib import Path
from trading_platform.research.training_provenance import build_calibration_manifest

p=argparse.ArgumentParser()
p.add_argument('--data'); p.add_argument('--dataset-id'); p.add_argument('--output-dir')
a=p.parse_args()
out=Path(a.output_dir)
model=out/'model.cbm'; calibrator=out/'calibrator.joblib'
model.write_bytes(b'synthetic-model'); calibrator.write_bytes(b'synthetic-calibrator')
start=datetime(2025, 1, 1, tzinfo=UTC)
windows={name: (start+timedelta(days=index*2), start+timedelta(days=index*2+1), 10) for index, name in enumerate(('train','early_stop','calibration','policy','test'))}
manifest=build_calibration_manifest(model_version='synthetic-v1', method='platt', target_definition='synthetic-win', dataset_id=a.dataset_id, dataset_sha256='a'*64, split_windows=windows, test_metrics={'brier_score': 0.2, 'log_loss': 0.6}, artifact_paths={'model': model, 'calibrator': calibrator}, offline_deployment_approved=False, created_at=start+timedelta(days=12))
(out/'calibration_provenance.json').write_text(json.dumps(manifest))
(out/'model_metadata.json').write_text(json.dumps({'calibration_id': manifest['calibration_id']}))
""",
        encoding="utf-8",
    )
    contract = tmp_path / "synthetic.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": "research_contract_v1",
                "experiment_id": "synthetic-clean-room",
                "trainer": "catboost_directional",
                "dataset_id": "replace-with-export-dataset-id",
                "data": "quote_samples/part-00001.parquet",
                "options": {},
            }
        ),
        encoding="utf-8",
    )
    mounted = tmp_path / "mounted" / "owner" / "dataset"
    prepare_bundle_from_export(
        dataset_id="synthetic-v1",
        export_manifest=export_manifest,
        output_root=mounted,
        platform_root=Path("trading_platform"),
        trainer=trainer,
        contract=contract,
        max_part_size_mb=1,
    )
    spec = importlib.util.spec_from_file_location(
        "kaggle_clean_room_notebook", Path("notebooks/kaggle_otc_training.py")
    )
    notebook = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(notebook)

    working = tmp_path / "working"
    workspace = notebook.bootstrap(mounted, working, "synthetic-v1")
    result = notebook.train(
        workspace,
        "synthetic.yaml",
        working / "output",
    )

    archive = Path(result["archive"])
    assert result["returncode"] == 0
    assert archive.is_file()
    report = validate_training_artifacts(archive)
    assert report["dataset_id"] == "synthetic-v1"
    assert report["offline_deployment_approved"] is False
