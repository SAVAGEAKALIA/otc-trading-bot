import json
from pathlib import Path

import yaml

from trading_platform.research.train import execute_training_run, resolve_training_run


def fixture(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "dataset.parquet").write_bytes(b"data")
    source_root = tmp_path / "source"
    source_root.mkdir()
    trainer = source_root / "train_catboost_directional.py"
    trainer.write_text(
        """import argparse, pathlib
p=argparse.ArgumentParser(); p.add_argument('--data'); p.add_argument('--dataset-id'); p.add_argument('--output-dir'); p.add_argument('--minimum-rows'); a=p.parse_args()
pathlib.Path(a.output_dir, 'trainer-ran.json').write_text(a.dataset_id)
""",
        encoding="utf-8",
    )
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": "research_contract_v1",
                "experiment_id": "experiment-v1",
                "trainer": "catboost_directional",
                "dataset_id": "dataset-v1",
                "data": "dataset.parquet",
                "options": {"minimum_rows": 10},
            }
        ),
        encoding="utf-8",
    )
    return contract, data_root, source_root


def test_resolves_allowlisted_training_command_and_dry_run(tmp_path) -> None:
    contract, data_root, source_root = fixture(tmp_path)
    run = resolve_training_run(
        contract_path=contract,
        data_root=data_root,
        source_root=source_root,
        output_root=tmp_path / "outputs",
        environment="kaggle",
    )

    assert run["trainer"] == "catboost_directional"
    assert "--minimum-rows" in run["command"]
    assert execute_training_run(run, dry_run=True) == 0
    assert json.loads(
        (tmp_path / "outputs/experiment-v1/resolved_training_run.json").read_text()
    )["dataset_id"] == "dataset-v1"


def test_executes_only_resolved_trainer_without_shell(tmp_path) -> None:
    contract, data_root, source_root = fixture(tmp_path)
    run = resolve_training_run(
        contract_path=contract,
        data_root=data_root,
        source_root=source_root,
        output_root=tmp_path / "outputs",
        environment="local",
    )

    assert execute_training_run(run) == 0
    assert (tmp_path / "outputs/experiment-v1/trainer-ran.json").read_text() == "dataset-v1"


def test_lstm_launcher_uses_only_explicit_training_environment(tmp_path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "dataset.parquet").write_bytes(b"data")
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "train_trading_model_v3.py").write_text(
        """import json, os, pathlib
out=pathlib.Path(os.environ['TRAINING_ARTIFACT_DIR'])
(out/'lstm-ran.json').write_text(json.dumps({k: os.environ[k] for k in ('TRAINING_DATA_FILE','TRAINING_ARTIFACT_DIR','TRAINING_DATASET_ID')}))
""",
        encoding="utf-8",
    )
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": "research_contract_v1",
                "experiment_id": "lstm-v1",
                "trainer": "lstm_stationary",
                "dataset_id": "dataset-v1",
                "data": "dataset.parquet",
                "options": {},
            }
        ),
        encoding="utf-8",
    )
    run = resolve_training_run(
        contract_path=contract,
        data_root=data_root,
        source_root=source_root,
        output_root=tmp_path / "outputs",
        environment="gcp",
    )

    assert run["command"] == [
        __import__("sys").executable,
        str(source_root / "train_trading_model_v3.py"),
    ]
    assert set(run["environment_variables"]) == {
        "TRAINING_DATA_FILE",
        "TRAINING_ARTIFACT_DIR",
        "TRAINING_DATASET_ID",
    }
    assert execute_training_run(run) == 0
    payload = json.loads((tmp_path / "outputs/lstm-v1/lstm-ran.json").read_text())
    assert payload["TRAINING_DATASET_ID"] == "dataset-v1"
