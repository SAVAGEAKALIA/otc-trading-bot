"""Standard-library helpers for portable training provenance manifests."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Mapping


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_dataset(path: Path) -> dict[str, int | str]:
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("dataset changed while its SHA-256 was being calculated")
    return {"sha256": digest, "size": after.st_size, "mtime_ns": after.st_mtime_ns}


def require_unchanged_dataset(path: Path, fingerprint: Mapping[str, int | str]) -> None:
    current = path.stat()
    if (current.st_size, current.st_mtime_ns) != (
        fingerprint["size"],
        fingerprint["mtime_ns"],
    ):
        raise RuntimeError("dataset changed during model training")


def build_calibration_manifest(
    *,
    model_version: str,
    method: str,
    target_definition: str,
    dataset_id: str,
    dataset_sha256: str,
    split_windows: Mapping[str, tuple[datetime, datetime, int]],
    test_metrics: Mapping[str, float],
    artifact_paths: Mapping[str, Path],
    offline_deployment_approved: bool,
    created_at: datetime | None = None,
) -> dict:
    required = {"train", "early_stop", "calibration", "policy", "test"}
    missing = sorted(required - set(split_windows))
    if missing:
        raise ValueError("missing provenance split windows: " + ", ".join(missing))
    training_start = split_windows["train"][0]
    training_end = split_windows["early_stop"][1]
    calibration_start = split_windows["calibration"][0]
    calibration_end = split_windows["policy"][1]
    test_start, test_end, test_count = split_windows["test"]
    for name, (start, end, count) in split_windows.items():
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError(f"{name} split start must be timezone-aware")
        if end.tzinfo is None or end.utcoffset() is None:
            raise ValueError(f"{name} split end must be timezone-aware")
        if start >= end or count <= 0:
            raise ValueError(f"{name} split must have ordered times and positive rows")
    if not training_start < training_end < calibration_start:
        raise ValueError("training/early-stop data must precede calibration data")
    if not calibration_start < calibration_end < test_start:
        raise ValueError("calibration/policy data must precede untouched test data")
    artifact_sha256 = {
        name: sha256_file(path) for name, path in sorted(artifact_paths.items())
    }
    calibration_id_seed = "|".join(
        [model_version, dataset_sha256]
        + [f"{name}:{digest}" for name, digest in artifact_sha256.items()]
    )
    calibration_id = (
        f"{model_version}-"
        f"{hashlib.sha256(calibration_id_seed.encode()).hexdigest()[:20]}"
    )
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    if timestamp < test_end:
        raise ValueError("created_at cannot predate the untouched test period")
    return {
        "calibration_id": calibration_id,
        "model_version": model_version,
        "method": method,
        "target_definition": target_definition,
        "dataset_id": dataset_id,
        "dataset_sha256": dataset_sha256,
        "training_start": training_start.isoformat(),
        "training_end": training_end.isoformat(),
        "calibration_start": calibration_start.isoformat(),
        "calibration_end": calibration_end.isoformat(),
        "test_start": test_start.isoformat(),
        "test_end": test_end.isoformat(),
        "sample_counts": {
            "training": split_windows["train"][2] + split_windows["early_stop"][2],
            "calibration": split_windows["calibration"][2] + split_windows["policy"][2],
            "test": test_count,
        },
        "test_metrics": {
            "brier_score": float(test_metrics["brier_score"]),
            "log_loss": float(test_metrics["log_loss"]),
        },
        "artifact_sha256": artifact_sha256,
        "offline_deployment_approved": bool(offline_deployment_approved),
        "created_at": timestamp.isoformat(),
    }
