import json
from pathlib import Path

import pytest
import yaml

import trading_platform.research.kaggle_training as kaggle_training
from trading_platform.research.kaggle_training import run_kaggle_training


def make_workspace(tmp_path: Path, *, contract_dataset_id: str = "dataset-v1") -> dict:
    data_root = tmp_path / "dataset" / "data"
    data_root.mkdir(parents=True)
    (data_root / "prepared.parquet").write_bytes(b"fixture")
    source_root = tmp_path / "platform"
    (source_root / "configs" / "research").mkdir(parents=True)
    (source_root / "train_catboost_directional.py").write_text(
        "raise RuntimeError('dry run must not execute trainer')\n",
        encoding="utf-8",
    )
    (source_root / "configs" / "research" / "experiment.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "research_contract_v1",
                "experiment_id": "experiment-v1",
                "trainer": "catboost_directional",
                "dataset_id": contract_dataset_id,
                "data": "prepared.parquet",
                "options": {},
            }
        ),
        encoding="utf-8",
    )
    return {
        "dataset_id": "dataset-v1",
        "data_root": str(data_root),
        "source_root": str(source_root),
    }


def test_runs_validated_contract_as_a_kaggle_dry_run(tmp_path: Path) -> None:
    result = run_kaggle_training(
        workspace=make_workspace(tmp_path),
        contract_name="experiment.yaml",
        output_root=tmp_path / "output",
        dry_run=True,
    )

    assert result["returncode"] == 0
    assert result["dataset_id"] == "dataset-v1"
    assert result["trainer"] == "catboost_directional"
    resolved = json.loads(
        (tmp_path / "output/experiment-v1/resolved_training_run.json").read_text()
    )
    assert resolved["environment"] == "kaggle"
    assert resolved["preflight"]["ready"] is True


def test_rejects_contract_for_a_different_dataset(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="dataset identity"):
        run_kaggle_training(
            workspace=make_workspace(tmp_path, contract_dataset_id="other-dataset"),
            contract_name="experiment.yaml",
            output_root=tmp_path / "output",
            dry_run=True,
        )


def test_rejects_contract_path_outside_research_config(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="simple YAML filename"):
        run_kaggle_training(
            workspace=make_workspace(tmp_path),
            contract_name="../experiment.yaml",
            output_root=tmp_path / "output",
            dry_run=True,
        )


def test_successful_training_is_packaged_for_download(tmp_path: Path, monkeypatch) -> None:
    def execute(run, *, dry_run=False):
        Path(run["output"]).mkdir(parents=True)
        return 0

    def package(source, destination):
        assert source.name == "experiment-v1"
        return {"archive": str(destination), "sha256": "a" * 64}

    monkeypatch.setattr(kaggle_training, "execute_training_run", execute)
    monkeypatch.setattr(kaggle_training, "package_training_artifacts", package)

    result = run_kaggle_training(
        workspace=make_workspace(tmp_path),
        contract_name="experiment.yaml",
        output_root=tmp_path / "output",
    )

    assert result["archive"].endswith("otc-training-experiment-v1.zip")
    assert result["archive_sha256"] == "a" * 64
