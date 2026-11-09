"""Portable, allowlisted research-training launcher."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

from trading_platform.research.training_preflight import preflight_training_run


TRAINERS = {
    "catboost_directional": "train_catboost_directional.py",
    "catboost_gate": "train_catboost_gate.py",
    "lstm_stationary": "train_trading_model_v3.py",
    "lstm_regime_mtf": "train_regime_mtf_lstm_v5.py",
}
COMMON_OPTIONS = {
    "minimum_rows": ("--minimum-rows", int),
    "purge_minutes": ("--purge-minutes", int),
    "minimum_policy_trades": ("--minimum-policy-trades", int),
    "minimum_test_trades": ("--minimum-test-trades", int),
    "minimum_test_days": ("--minimum-test-days", int),
    "minimum_context_coverage": ("--minimum-context-coverage", float),
    "assumed_payout": ("--assumed-payout", float),
    "iterations": ("--iterations", int),
    "depth": ("--depth", int),
    "learning_rate": ("--learning-rate", float),
    "bootstrap_samples": ("--bootstrap-samples", int),
    "seed": ("--seed", int),
}
TRAINER_OPTIONS = {
    "catboost_directional": {
        **COMMON_OPTIONS,
        "cooldown_seconds": ("--cooldown-seconds", int),
    },
    "catboost_gate": {
        **COMMON_OPTIONS,
        "minimum_days": ("--minimum-days", int),
    },
    "lstm_stationary": {},
    "lstm_regime_mtf": {},
}


def _inside(root: Path, relative: str, label: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"{label} escapes its configured root")
    return candidate


def resolve_training_run(
    *,
    contract_path: Path,
    data_root: Path,
    source_root: Path,
    output_root: Path,
    environment: str,
) -> dict:
    if environment not in {"local", "kaggle", "gcp"}:
        raise ValueError("environment must be local, kaggle, or gcp")
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict) or contract.get("schema_version") != "research_contract_v1":
        raise ValueError("unsupported research contract")
    trainer_name = str(contract.get("trainer", ""))
    if trainer_name not in TRAINERS:
        raise ValueError(f"trainer is not allowlisted: {trainer_name}")
    dataset_id = str(contract.get("dataset_id", "")).strip()
    experiment_id = str(contract.get("experiment_id", "")).strip()
    if not dataset_id or not experiment_id:
        raise ValueError("dataset_id and experiment_id are required")
    data_path = _inside(data_root, str(contract.get("data", "")), "data path")
    if not data_path.is_file():
        raise FileNotFoundError(data_path)
    trainer_path = _inside(source_root, TRAINERS[trainer_name], "trainer path")
    if not trainer_path.is_file():
        raise FileNotFoundError(trainer_path)
    output_path = _inside(output_root, experiment_id, "output path")
    options = contract.get("options", {}) or {}
    if not isinstance(options, dict):
        raise ValueError("options must be a mapping")
    allowed = TRAINER_OPTIONS[trainer_name]
    unexpected = sorted(set(options) - set(allowed) - {"gpu"})
    if unexpected:
        raise ValueError("unsupported trainer options: " + ", ".join(unexpected))
    command = [sys.executable, str(trainer_path)]
    environment_variables = {}
    if trainer_name.startswith("catboost_"):
        command.extend(
            [
                "--data",
                str(data_path),
                "--dataset-id",
                dataset_id,
                "--output-dir",
                str(output_path),
            ]
        )
    else:
        environment_variables = {
            "TRAINING_DATA_FILE": str(data_path),
            "TRAINING_ARTIFACT_DIR": str(output_path),
            "TRAINING_DATASET_ID": dataset_id,
        }
    resolved_options = {}
    for name in sorted(set(options) - {"gpu"}):
        flag, converter = allowed[name]
        value = converter(options[name])
        command.extend([flag, str(value)])
        resolved_options[name] = value
    if bool(options.get("gpu", False)):
        command.append("--gpu")
        resolved_options["gpu"] = True
    return {
        "schema_version": "resolved_training_run_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "experiment_id": experiment_id,
        "dataset_id": dataset_id,
        "trainer": trainer_name,
        "data": str(data_path),
        "output": str(output_path),
        "options": resolved_options,
        "command": command,
        "source_root": str(source_root.resolve()),
        "environment_variables": environment_variables,
    }


def execute_training_run(run: dict, *, dry_run: bool = False) -> int:
    output = Path(run["output"])
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    (output / "resolved_training_run.json").write_text(
        json.dumps(run, indent=2) + "\n", encoding="utf-8"
    )
    if dry_run:
        return 0
    source_root = Path(run["source_root"])
    environment = os.environ.copy()
    platform_path = str(source_root)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = platform_path + (os.pathsep + existing if existing else "")
    environment.update(
        {str(name): str(value) for name, value in run["environment_variables"].items()}
    )
    completed = subprocess.run(
        run["command"],
        cwd=source_root,
        env=environment,
        check=False,
    )
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environment", choices=("local", "kaggle", "gcp"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run = resolve_training_run(
        contract_path=args.contract,
        data_root=args.data_root,
        source_root=args.source_root,
        output_root=args.output,
        environment=args.environment,
    )
    run["preflight"] = preflight_training_run(run)
    print(json.dumps(run, indent=2))
    return execute_training_run(run, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
