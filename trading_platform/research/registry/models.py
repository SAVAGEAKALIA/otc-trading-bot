"""Immutable research-trial records and promotion evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping

from trading_platform.domain.time import require_utc
from trading_platform.research.model_promotion import assess_offline_promotion
from trading_platform.research.validation import PurgedWindow


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_ALLOWED_STATUSES = {"pending", "running", "completed", "failed", "rejected"}


def _require_identifier(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{name} must be a non-empty portable identifier")
    return normalized


def _require_sha256(value: str, name: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a hexadecimal SHA-256 digest")
    return normalized


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a decimal number") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _freeze_json(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if not key:
                raise ValueError(f"{name} keys must not be empty")
            frozen[key] = _freeze_json(item, f"{name}.{key}")
        return MappingProxyType(dict(sorted(frozen.items())))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, name) for item in value)
    if value is None or isinstance(value, (str, bool, int, Decimal)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} values must be finite")
        return value
    raise ValueError(f"{name} contains a non-JSON value: {type(value).__name__}")


def _json_record(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_record(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_json_record(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


@dataclass(frozen=True, slots=True)
class TrialPromotionEvidence:
    independent_policy_partition: bool
    strict_provenance_manifest: bool
    threshold_selection_passed: bool
    inference_parity_passed: bool
    calibration_lower_expectancy: Decimal
    test_lower_expectancy: Decimal
    test_trades: int
    minimum_test_trades: int
    test_days: int
    minimum_test_days: int

    def __post_init__(self) -> None:
        for name in ("calibration_lower_expectancy", "test_lower_expectancy"):
            object.__setattr__(self, name, _decimal(getattr(self, name), name))
        for name in ("test_trades", "minimum_test_trades", "test_days", "minimum_test_days"):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
            if name.startswith("minimum_") and value == 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)

    @property
    def assessment(self):
        return assess_offline_promotion(
            independent_policy_partition=self.independent_policy_partition,
            strict_provenance_manifest=self.strict_provenance_manifest,
            threshold_selection_passed=self.threshold_selection_passed,
            inference_parity_passed=self.inference_parity_passed,
            calibration_lower_expectancy=float(self.calibration_lower_expectancy),
            test_lower_expectancy=float(self.test_lower_expectancy),
            test_trades=self.test_trades,
            minimum_test_trades=self.minimum_test_trades,
            test_days=self.test_days,
            minimum_test_days=self.minimum_test_days,
        )

    def to_record(self) -> dict[str, object]:
        assessment = self.assessment
        return {
            "independent_policy_partition": self.independent_policy_partition,
            "strict_provenance_manifest": self.strict_provenance_manifest,
            "threshold_selection_passed": self.threshold_selection_passed,
            "inference_parity_passed": self.inference_parity_passed,
            "calibration_lower_expectancy": str(self.calibration_lower_expectancy),
            "test_lower_expectancy": str(self.test_lower_expectancy),
            "test_trades": self.test_trades,
            "minimum_test_trades": self.minimum_test_trades,
            "test_days": self.test_days,
            "minimum_test_days": self.minimum_test_days,
            "assessment": {
                "approved": assessment.approved,
                "reasons": list(assessment.reasons),
            },
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "TrialPromotionEvidence":
        return cls(
            independent_policy_partition=bool(record["independent_policy_partition"]),
            strict_provenance_manifest=bool(record["strict_provenance_manifest"]),
            threshold_selection_passed=bool(record["threshold_selection_passed"]),
            inference_parity_passed=bool(record["inference_parity_passed"]),
            calibration_lower_expectancy=_decimal(
                record["calibration_lower_expectancy"], "calibration_lower_expectancy"
            ),
            test_lower_expectancy=_decimal(
                record["test_lower_expectancy"], "test_lower_expectancy"
            ),
            test_trades=int(record["test_trades"]),
            minimum_test_trades=int(record["minimum_test_trades"]),
            test_days=int(record["test_days"]),
            minimum_test_days=int(record["minimum_test_days"]),
        )


@dataclass(frozen=True, slots=True)
class TrialRecord:
    trial_id: str
    experiment_id: str
    experiment_name: str
    dataset_id: str
    dataset_sha256: str
    validation_windows: tuple[PurgedWindow, ...]
    candidate_version: str
    backtest_report: Mapping[str, object]
    metrics: Mapping[str, Decimal]
    provenance_references: Mapping[str, str]
    created_at: datetime
    status: str
    deployment_approved: bool = False
    promotion_evidence: TrialPromotionEvidence | None = None
    evidence_metadata: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        for name in ("trial_id", "experiment_id", "dataset_id", "candidate_version"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        experiment_name = self.experiment_name.strip()
        if not experiment_name:
            raise ValueError("experiment_name must not be empty")
        object.__setattr__(self, "experiment_name", experiment_name)
        object.__setattr__(
            self, "dataset_sha256", _require_sha256(self.dataset_sha256, "dataset_sha256")
        )
        require_utc(self.created_at, "created_at")
        status = self.status.strip().lower()
        if status not in _ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {sorted(_ALLOWED_STATUSES)}")
        object.__setattr__(self, "status", status)

        windows = tuple(self.validation_windows)
        if not windows:
            raise ValueError("at least one validation window is required")
        previous_test_end: datetime | None = None
        for window in windows:
            if not isinstance(window, PurgedWindow):
                raise ValueError("validation windows must be PurgedWindow records")
            for name in ("train_start", "train_end", "test_start", "test_end"):
                require_utc(getattr(window, name), f"validation window {name}")
            if not window.train_start < window.train_end < window.test_start < window.test_end:
                raise ValueError("validation window must order train, purge, and test periods")
            if previous_test_end is not None and window.train_start < previous_test_end:
                raise ValueError("validation windows must be chronological and non-overlapping")
            previous_test_end = window.test_end
        if windows[-1].test_end > self.created_at:
            raise ValueError("created_at cannot predate the final validation window")
        object.__setattr__(self, "validation_windows", windows)

        report = _freeze_json(self.backtest_report, "backtest_report")
        if not isinstance(report, Mapping) or not report:
            raise ValueError("backtest_report must not be empty")
        object.__setattr__(self, "backtest_report", report)

        metrics = {
            str(name).strip(): _decimal(value, f"metrics.{name}")
            for name, value in self.metrics.items()
        }
        if not metrics or any(not name for name in metrics):
            raise ValueError("metrics must identify at least one metric")
        object.__setattr__(self, "metrics", MappingProxyType(dict(sorted(metrics.items()))))

        references = {
            str(name).strip(): str(value).strip()
            for name, value in self.provenance_references.items()
        }
        if not references or any(not name or not value for name, value in references.items()):
            raise ValueError("provenance_references must contain non-empty identities")
        object.__setattr__(
            self, "provenance_references", MappingProxyType(dict(sorted(references.items())))
        )
        metadata = _freeze_json(self.evidence_metadata, "evidence_metadata")
        if not isinstance(metadata, Mapping):
            raise ValueError("evidence_metadata must be a mapping")
        object.__setattr__(self, "evidence_metadata", metadata)

        if self.deployment_approved:
            if self.status != "completed":
                raise ValueError("deployment approval requires a completed trial")
            if self.promotion_evidence is None:
                raise ValueError("deployment approval requires promotion evidence")
            assessment = self.promotion_evidence.assessment
            if not assessment.approved:
                raise ValueError(
                    "deployment approval rejected by promotion evidence: "
                    + "; ".join(assessment.reasons)
                )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": "research_trial_v1",
            "trial_id": self.trial_id,
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "dataset_id": self.dataset_id,
            "dataset_sha256": self.dataset_sha256,
            "validation_windows": [
                {
                    "train_start": window.train_start.isoformat(),
                    "train_end": window.train_end.isoformat(),
                    "test_start": window.test_start.isoformat(),
                    "test_end": window.test_end.isoformat(),
                }
                for window in self.validation_windows
            ],
            "candidate_version": self.candidate_version,
            "backtest_report": _json_record(self.backtest_report),
            "metrics": {name: str(value) for name, value in self.metrics.items()},
            "provenance_references": dict(self.provenance_references),
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "deployment_approved": self.deployment_approved,
            "promotion_evidence": (
                self.promotion_evidence.to_record() if self.promotion_evidence else None
            ),
            "evidence_metadata": _json_record(self.evidence_metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_record(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "TrialRecord":
        if record.get("schema_version") != "research_trial_v1":
            raise ValueError("unsupported research trial schema")
        raw_windows = record["validation_windows"]
        if not isinstance(raw_windows, (list, tuple)):
            raise ValueError("validation_windows must be a list")
        windows = tuple(
            PurgedWindow(
                train_start=datetime.fromisoformat(str(item["train_start"])),
                train_end=datetime.fromisoformat(str(item["train_end"])),
                test_start=datetime.fromisoformat(str(item["test_start"])),
                test_end=datetime.fromisoformat(str(item["test_end"])),
            )
            for item in raw_windows
        )
        raw_evidence = record.get("promotion_evidence")
        return cls(
            trial_id=str(record["trial_id"]),
            experiment_id=str(record["experiment_id"]),
            experiment_name=str(record["experiment_name"]),
            dataset_id=str(record["dataset_id"]),
            dataset_sha256=str(record["dataset_sha256"]),
            validation_windows=windows,
            candidate_version=str(record["candidate_version"]),
            backtest_report=dict(record["backtest_report"]),  # type: ignore[arg-type]
            metrics={
                str(name): _decimal(value, f"metrics.{name}")
                for name, value in dict(record["metrics"]).items()  # type: ignore[arg-type]
            },
            provenance_references={
                str(name): str(value)
                for name, value in dict(record["provenance_references"]).items()  # type: ignore[arg-type]
            },
            created_at=datetime.fromisoformat(str(record["created_at"])),
            status=str(record["status"]),
            deployment_approved=bool(record.get("deployment_approved", False)),
            promotion_evidence=(
                TrialPromotionEvidence.from_record(raw_evidence)  # type: ignore[arg-type]
                if raw_evidence is not None
                else None
            ),
            evidence_metadata=dict(record.get("evidence_metadata", {})),  # type: ignore[arg-type]
        )
