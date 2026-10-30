from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from trading_platform.research.registry import (
    TrialPromotionEvidence,
    TrialRecord,
    TrialRegistry,
)
from trading_platform.research.validation import PurgedWindow


START = datetime(2026, 1, 1, tzinfo=UTC)


def promotion_evidence(**overrides) -> TrialPromotionEvidence:
    values = {
        "independent_policy_partition": True,
        "strict_provenance_manifest": True,
        "threshold_selection_passed": True,
        "inference_parity_passed": True,
        "calibration_lower_expectancy": Decimal("0.04"),
        "test_lower_expectancy": Decimal("0.02"),
        "test_trades": 500,
        "minimum_test_trades": 300,
        "test_days": 60,
        "minimum_test_days": 30,
    }
    values.update(overrides)
    return TrialPromotionEvidence(**values)


def trial_record(**overrides) -> TrialRecord:
    values = {
        "trial_id": "trial-0001",
        "experiment_id": "otc-direction-v1",
        "experiment_name": "OTC directional baseline",
        "dataset_id": "otc-enriched-202601",
        "dataset_sha256": "a" * 64,
        "validation_windows": (
            PurgedWindow(
                train_start=START,
                train_end=START + timedelta(days=30),
                test_start=START + timedelta(days=31),
                test_end=START + timedelta(days=38),
            ),
        ),
        "candidate_version": "strategy-v3",
        "backtest_report": {
            "schema_version": "event_backtest_result_v1",
            "trades": [],
            "net_pnl": "12.50",
        },
        "metrics": {
            "profit_factor": Decimal("1.25"),
            "net_pnl": Decimal("12.50"),
        },
        "provenance_references": {
            "dataset_manifest": "prepared/manifest.json",
            "calibration_id": "cal-v1",
        },
        "created_at": START + timedelta(days=39),
        "status": "completed",
        "deployment_approved": False,
        "promotion_evidence": None,
        "evidence_metadata": {"runner": "event-backtester-v1"},
    }
    values.update(overrides)
    return TrialRecord(**values)


def test_trial_record_is_immutable_and_serializes_deterministically() -> None:
    first = trial_record(
        metrics={"net_pnl": Decimal("12.50"), "profit_factor": Decimal("1.25")},
        evidence_metadata={"z": [2, 1], "a": {"checked": True}},
    )
    second = trial_record(
        metrics={"profit_factor": Decimal("1.25"), "net_pnl": Decimal("12.50")},
        evidence_metadata={"a": {"checked": True}, "z": [2, 1]},
    )

    assert first.to_json() == second.to_json()
    assert TrialRecord.from_record(json.loads(first.to_json())) == first
    assert first.to_record()["metrics"] == {
        "net_pnl": "12.50",
        "profit_factor": "1.25",
    }
    with pytest.raises(FrozenInstanceError):
        first.status = "failed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        first.metrics["net_pnl"] = Decimal("0")  # type: ignore[index]
    with pytest.raises(TypeError):
        first.evidence_metadata["runner"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"trial_id": "bad id"}, "trial_id"),
        ({"experiment_id": ""}, "experiment_id"),
        ({"dataset_sha256": "abc"}, "dataset_sha256"),
        ({"created_at": datetime(2026, 2, 1)}, "created_at"),
        (
            {"created_at": datetime(2026, 2, 1, tzinfo=timezone(timedelta(hours=1)))},
            "created_at",
        ),
        ({"metrics": {}}, "metrics"),
        ({"metrics": {"score": Decimal("NaN")}}, "finite"),
        ({"status": "installed"}, "status"),
    ],
)
def test_trial_record_rejects_malformed_identity_time_and_metrics(
    override: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        trial_record(**override)


def test_trial_record_validates_serialized_walk_forward_windows() -> None:
    with pytest.raises(ValueError, match="validation window"):
        trial_record(
            validation_windows=(
                PurgedWindow(
                    train_start=START,
                    train_end=START + timedelta(days=30),
                    test_start=START + timedelta(days=29),
                    test_end=START + timedelta(days=38),
                ),
            )
        )


def test_deployment_approval_fails_closed_without_complete_passing_evidence() -> None:
    with pytest.raises(ValueError, match="promotion evidence"):
        trial_record(deployment_approved=True)

    with pytest.raises(ValueError, match="inference parity"):
        trial_record(
            deployment_approved=True,
            promotion_evidence=promotion_evidence(inference_parity_passed=False),
        )

    approved = trial_record(
        deployment_approved=True,
        promotion_evidence=promotion_evidence(),
    )
    assert approved.to_record()["promotion_evidence"]["assessment"] == {
        "approved": True,
        "reasons": [],
    }


def test_registry_is_idempotent_for_same_record_and_rejects_conflicts() -> None:
    registry = TrialRegistry()
    record = trial_record()

    assert registry.register(record) is True
    assert registry.register(record) is False
    assert registry.get(record.trial_id) == record
    assert registry.list_trials() == (record,)

    with pytest.raises(ValueError, match="different trial"):
        registry.register(trial_record(candidate_version="strategy-v4"))


def test_registry_persists_and_reloads_validated_records_atomically(tmp_path) -> None:
    path = tmp_path / "research" / "trial-registry.json"
    registry = TrialRegistry(path)
    later = trial_record(
        trial_id="trial-0002",
        created_at=START + timedelta(days=40),
    )
    first = trial_record()

    registry.register(later)
    registry.register(first)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == "trial_registry_v1"
    assert [item["trial_id"] for item in persisted["trials"]] == [
        "trial-0001",
        "trial-0002",
    ]
    reloaded = TrialRegistry(path)
    assert reloaded.list_trials() == (first, later)


def test_registry_rejects_conflicting_records_on_disk(tmp_path) -> None:
    path = tmp_path / "trial-registry.json"
    item = trial_record().to_record()
    conflicting = {**item, "candidate_version": "different"}
    path.write_text(
        json.dumps(
            {
                "schema_version": "trial_registry_v1",
                "trials": [item, conflicting],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="different trial"):
        TrialRegistry(path)
