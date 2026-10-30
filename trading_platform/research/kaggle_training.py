"""Coordinate one allowlisted training run in a prepared Kaggle workspace."""

from __future__ import annotations

from pathlib import Path

from trading_platform.research.train import execute_training_run, resolve_training_run
from trading_platform.research.training_artifacts import package_training_artifacts
from trading_platform.research.training_preflight import preflight_training_run


def run_kaggle_training(
    *,
    workspace: dict,
    contract_name: str,
    output_root: Path,
    dry_run: bool = False,
) -> dict:
    """Resolve and execute one bundled contract without accepting arbitrary paths."""
    relative = Path(contract_name)
    if (
        relative.name != contract_name
        or relative.suffix.lower() not in {".yaml", ".yml"}
    ):
        raise ValueError("contract_name must be a simple YAML filename")
    dataset_id = str(workspace.get("dataset_id", "")).strip()
    if not dataset_id:
        raise ValueError("workspace dataset_id is required")
    data_root = Path(str(workspace["data_root"])).resolve()
    source_root = Path(str(workspace["source_root"])).resolve()
    contract_path = source_root / "configs" / "research" / contract_name
    run = resolve_training_run(
        contract_path=contract_path,
        data_root=data_root,
        source_root=source_root,
        output_root=Path(output_root),
        environment="kaggle",
    )
    if run["dataset_id"] != dataset_id:
        raise ValueError(
            "training contract dataset identity does not match the validated workspace"
        )
    preflight = preflight_training_run(run)
    run["preflight"] = preflight
    returncode = execute_training_run(run, dry_run=dry_run)
    result = {
        "schema_version": "kaggle_training_result_v1",
        "dataset_id": dataset_id,
        "experiment_id": run["experiment_id"],
        "trainer": run["trainer"],
        "output": run["output"],
        "dry_run": bool(dry_run),
        "returncode": returncode,
        "preflight": preflight,
    }
    if returncode == 0 and not dry_run:
        archive = Path(run["output"]).parent / f"otc-training-{run['experiment_id']}.zip"
        packaged = package_training_artifacts(Path(run["output"]), archive)
        result["archive"] = packaged["archive"]
        result["archive_sha256"] = packaged["sha256"]
    return result
