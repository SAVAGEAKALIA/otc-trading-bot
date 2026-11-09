"""Deterministic, read-only reports for OTC shadow decision parity."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from typing import Callable, Iterable

from trading_platform.storage.repository import SignalDecisionRecord


LEGACY_SUBMISSION_DISPOSITION = "legacy_would_submit"


@dataclass(frozen=True, slots=True)
class DecisionBreakdown:
    total: int
    approved: int
    rejected: int


@dataclass(frozen=True, slots=True)
class OTCParityReport:
    total_candidates: int
    approved: int
    rejected: int
    approval_rate: str
    missing_calibration: int
    missing_calibration_version: int
    unregistered_calibration: int
    unapproved_calibration: int
    stale: int
    martingale_exclusions: int
    low_payout: int
    non_positive_expectancy: int
    rejection_reasons: dict[str, int]
    by_asset: dict[str, DecisionBreakdown]
    by_source: dict[str, DecisionBreakdown]
    by_strategy: dict[str, DecisionBreakdown]
    by_calibration_version: dict[str, DecisionBreakdown]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False) + "\n"

    def to_markdown(self) -> str:
        lines = [
            "# OTC Shadow Parity Report",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Legacy submission candidates | {self.total_candidates} |",
            f"| Shadow approved | {self.approved} |",
            f"| Shadow rejected | {self.rejected} |",
            f"| Approval rate | {float(self.approval_rate) * 100:.4f}% |",
            f"| Missing calibration | {self.missing_calibration} |",
            f"| Missing calibration version | {self.missing_calibration_version} |",
            f"| Unregistered calibration | {self.unregistered_calibration} |",
            f"| Unapproved calibration | {self.unapproved_calibration} |",
            f"| Stale | {self.stale} |",
            f"| Martingale exclusions | {self.martingale_exclusions} |",
            f"| Low payout | {self.low_payout} |",
            f"| Non-positive expectancy | {self.non_positive_expectancy} |",
        ]
        self._append_breakdown(lines, "By asset", self.by_asset)
        self._append_breakdown(lines, "By source", self.by_source)
        self._append_breakdown(lines, "By strategy", self.by_strategy)
        self._append_breakdown(
            lines, "By calibration version", self.by_calibration_version
        )
        lines.extend(
            ["", "## Rejection reasons", "", "| Reason | Count |", "|---|---:|"]
        )
        lines.extend(
            f"| {reason} | {count} |"
            for reason, count in self.rejection_reasons.items()
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _append_breakdown(
        lines: list[str], title: str, values: dict[str, DecisionBreakdown]
    ) -> None:
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                "| Value | Total | Approved | Rejected |",
                "|---|---:|---:|---:|",
            ]
        )
        lines.extend(
            f"| {key} | {value.total} | {value.approved} | {value.rejected} |"
            for key, value in values.items()
        )


def build_otc_parity_report(
    records: Iterable[SignalDecisionRecord],
) -> OTCParityReport:
    candidates = [
        record
        for record in records
        if record.legacy_disposition == LEGACY_SUBMISSION_DISPOSITION
    ]
    approved = sum(record.approved for record in candidates)
    total = len(candidates)
    reason_counts = Counter(
        reason for record in candidates if not record.approved for reason in record.reasons
    )
    return OTCParityReport(
        total_candidates=total,
        approved=approved,
        rejected=total - approved,
        approval_rate=f"{approved / total if total else 0:.6f}",
        missing_calibration=reason_counts["calibrated win probability is missing"],
        missing_calibration_version=reason_counts["calibration version is missing"],
        unregistered_calibration=reason_counts[
            "calibration provenance is not registered"
        ],
        unapproved_calibration=reason_counts[
            "calibration provenance is not deployment approved"
        ],
        stale=reason_counts["signal is stale"],
        martingale_exclusions=reason_counts[
            "martingale is disabled in the migrated OTC path"
        ],
        low_payout=reason_counts["OTC payout is below minimum"],
        non_positive_expectancy=reason_counts[
            "payout-dependent expectancy is not positive"
        ],
        rejection_reasons=dict(sorted(reason_counts.items())),
        by_asset=_breakdown(candidates, lambda record: record.symbol),
        by_source=_breakdown(candidates, lambda record: record.source or "<missing>"),
        by_strategy=_breakdown(candidates, lambda record: record.strategy_id),
        by_calibration_version=_breakdown(
            candidates, lambda record: record.calibration_version or "<missing>"
        ),
    )


def _breakdown(
    records: list[SignalDecisionRecord],
    key: Callable[[SignalDecisionRecord], str],
) -> dict[str, DecisionBreakdown]:
    grouped: dict[str, list[SignalDecisionRecord]] = {}
    for record in records:
        grouped.setdefault(key(record), []).append(record)
    return {
        name: DecisionBreakdown(
            total=len(items),
            approved=sum(item.approved for item in items),
            rejected=sum(not item.approved for item in items),
        )
        for name, items in sorted(grouped.items())
    }
