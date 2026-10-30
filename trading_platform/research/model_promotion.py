"""Deterministic, fail-closed offline model-promotion decisions."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class OfflinePromotionAssessment:
    approved: bool
    reasons: tuple[str, ...]


def assess_offline_promotion(
    *,
    independent_policy_partition: bool,
    strict_provenance_manifest: bool,
    threshold_selection_passed: bool,
    inference_parity_passed: bool,
    calibration_lower_expectancy: float,
    test_lower_expectancy: float,
    test_trades: int,
    minimum_test_trades: int,
    test_days: int,
    minimum_test_days: int,
) -> OfflinePromotionAssessment:
    """Evaluate research evidence without allowing absent evidence to pass."""

    reasons: list[str] = []
    if not independent_policy_partition:
        reasons.append(
            "probability calibration and threshold policy require independent "
            "chronological partitions"
        )
    if not strict_provenance_manifest:
        reasons.append("strict dataset and artifact provenance manifest is missing")
    if not threshold_selection_passed:
        reasons.append("threshold-selection gate did not pass")
    if not inference_parity_passed:
        reasons.append("exported-model inference parity did not pass")
    if not math.isfinite(calibration_lower_expectancy) or calibration_lower_expectancy <= 0:
        reasons.append("calibration lower-bound expectancy is not positive")
    if not math.isfinite(test_lower_expectancy) or test_lower_expectancy <= 0:
        reasons.append("untouched-test lower-bound expectancy is not positive")
    if test_trades < minimum_test_trades:
        reasons.append("untouched-test trade count is below the configured minimum")
    if test_days < minimum_test_days:
        reasons.append("untouched-test day count is below the configured minimum")
    return OfflinePromotionAssessment(approved=not reasons, reasons=tuple(reasons))
