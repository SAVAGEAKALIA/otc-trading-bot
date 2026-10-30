from trading_platform.research.model_promotion import assess_offline_promotion


def passing_evidence(**overrides):
    evidence = {
        "independent_policy_partition": True,
        "strict_provenance_manifest": True,
        "threshold_selection_passed": True,
        "inference_parity_passed": True,
        "calibration_lower_expectancy": 0.02,
        "test_lower_expectancy": 0.01,
        "test_trades": 1_200,
        "minimum_test_trades": 1_000,
        "test_days": 20,
        "minimum_test_days": 15,
    }
    evidence.update(overrides)
    return evidence


def test_complete_independent_evidence_can_pass_offline_gate() -> None:
    assessment = assess_offline_promotion(**passing_evidence())

    assert assessment.approved is True
    assert assessment.reasons == ()


def test_reusing_calibration_for_policy_fails_closed() -> None:
    assessment = assess_offline_promotion(
        **passing_evidence(independent_policy_partition=False)
    )

    assert assessment.approved is False
    assert "independent chronological partitions" in assessment.reasons[0]


def test_missing_provenance_cannot_be_offset_by_positive_metrics() -> None:
    assessment = assess_offline_promotion(
        **passing_evidence(strict_provenance_manifest=False)
    )

    assert assessment.approved is False
    assert any("provenance" in reason for reason in assessment.reasons)
