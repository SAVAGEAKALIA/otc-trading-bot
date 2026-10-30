"""Immutable provenance for calibrated model probabilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import Mapping

from .time import require_utc


def _require_sha256(value: str, name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a hexadecimal SHA-256 digest")
    return normalized


@dataclass(frozen=True, slots=True)
class CalibrationProvenance:
    calibration_id: str
    model_version: str
    method: str
    target_definition: str
    dataset_id: str
    dataset_sha256: str
    training_start: datetime
    training_end: datetime
    calibration_start: datetime
    calibration_end: datetime
    test_start: datetime
    test_end: datetime
    sample_counts: Mapping[str, int]
    test_metrics: Mapping[str, float]
    artifact_sha256: Mapping[str, str]
    offline_deployment_approved: bool
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "calibration_id",
            "model_version",
            "method",
            "target_definition",
            "dataset_id",
        ):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        object.__setattr__(
            self, "dataset_sha256", _require_sha256(self.dataset_sha256, "dataset_sha256")
        )
        for name in (
            "training_start",
            "training_end",
            "calibration_start",
            "calibration_end",
            "test_start",
            "test_end",
            "created_at",
        ):
            require_utc(getattr(self, name), name)
        if not self.training_start < self.training_end < self.calibration_start:
            raise ValueError("training period must end before calibration period")
        if not self.calibration_start < self.calibration_end < self.test_start:
            raise ValueError("calibration period must end before untouched test period")
        if not self.test_start < self.test_end <= self.created_at:
            raise ValueError("test period must end no later than provenance creation")

        counts = {str(name): int(value) for name, value in self.sample_counts.items()}
        for required in ("training", "calibration", "test"):
            if counts.get(required, 0) <= 0:
                raise ValueError(f"sample_counts.{required} must be positive")
        metrics = {str(name): float(value) for name, value in self.test_metrics.items()}
        for required in ("brier_score", "log_loss"):
            if required not in metrics:
                raise ValueError(f"test_metrics.{required} is required")
            if not isfinite(metrics[required]) or metrics[required] < 0:
                raise ValueError(f"test_metrics.{required} must be finite and non-negative")
        if metrics["brier_score"] > 1:
            raise ValueError("test_metrics.brier_score must not exceed 1")
        hashes = {
            str(name).strip(): _require_sha256(value, f"artifact_sha256.{name}")
            for name, value in self.artifact_sha256.items()
        }
        if not hashes or any(not name for name in hashes):
            raise ValueError("artifact_sha256 must identify at least one artifact")
        object.__setattr__(self, "sample_counts", MappingProxyType(counts))
        object.__setattr__(self, "test_metrics", MappingProxyType(metrics))
        object.__setattr__(self, "artifact_sha256", MappingProxyType(hashes))

    def to_record(self) -> dict:
        return {
            "calibration_id": self.calibration_id,
            "model_version": self.model_version,
            "method": self.method,
            "target_definition": self.target_definition,
            "dataset_id": self.dataset_id,
            "dataset_sha256": self.dataset_sha256,
            "training_start": self.training_start.isoformat(),
            "training_end": self.training_end.isoformat(),
            "calibration_start": self.calibration_start.isoformat(),
            "calibration_end": self.calibration_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "sample_counts": dict(self.sample_counts),
            "test_metrics": dict(self.test_metrics),
            "artifact_sha256": dict(self.artifact_sha256),
            "offline_deployment_approved": self.offline_deployment_approved,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_record(cls, record: Mapping) -> "CalibrationProvenance":
        return cls(
            calibration_id=str(record["calibration_id"]),
            model_version=str(record["model_version"]),
            method=str(record["method"]),
            target_definition=str(record["target_definition"]),
            dataset_id=str(record["dataset_id"]),
            dataset_sha256=str(record["dataset_sha256"]),
            training_start=datetime.fromisoformat(str(record["training_start"])),
            training_end=datetime.fromisoformat(str(record["training_end"])),
            calibration_start=datetime.fromisoformat(str(record["calibration_start"])),
            calibration_end=datetime.fromisoformat(str(record["calibration_end"])),
            test_start=datetime.fromisoformat(str(record["test_start"])),
            test_end=datetime.fromisoformat(str(record["test_end"])),
            sample_counts=dict(record["sample_counts"]),
            test_metrics=dict(record["test_metrics"]),
            artifact_sha256=dict(record["artifact_sha256"]),
            offline_deployment_approved=bool(record["offline_deployment_approved"]),
            created_at=datetime.fromisoformat(str(record["created_at"])),
        )
