import json
from datetime import UTC, datetime
from uuid import UUID

from trading_platform.storage.repository import SignalDecisionRecord
from trading_platform.strategies.otc.reporting import build_otc_parity_report


NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def record(
    suffix: int,
    *,
    approved: bool,
    reasons: tuple[str, ...] = (),
    asset: str = "EURUSD-OTC",
    source: str = "scanner",
    strategy: str = "catboost-gate",
    calibration: str | None = "cal-v1",
    disposition: str | None = "legacy_would_submit",
) -> SignalDecisionRecord:
    return SignalDecisionRecord(
        signal_id=UUID(f"00000000-0000-0000-0000-{suffix:012d}"),
        environment="shadow",
        venue="iqoption",
        product_type="binary_option",
        symbol=asset,
        strategy_id=strategy,
        source=source,
        calibration_version=calibration,
        legacy_disposition=disposition,
        approved=approved,
        reasons=reasons,
        proposal={},
        risk_decision={},
        created_at=NOW,
    )


def test_parity_report_counts_reasons_and_dimensions_deterministically() -> None:
    report = build_otc_parity_report(
        [
            record(1, approved=True),
            record(2, approved=False, calibration=None, reasons=("calibrated win probability is missing",)),
            record(3, approved=False, source="telegram", reasons=("signal is stale",)),
            record(4, approved=False, asset="GBPUSD-OTC", reasons=("martingale is disabled in the migrated OTC path",)),
            record(5, approved=False, asset="GBPUSD-OTC", reasons=("OTC payout is below minimum", "payout-dependent expectancy is not positive")),
            record(6, approved=True, disposition=None),
        ]
    )

    assert report.total_candidates == 5
    assert report.approved == 1
    assert report.rejected == 4
    assert report.approval_rate == "0.200000"
    assert report.missing_calibration == 1
    assert report.stale == 1
    assert report.martingale_exclusions == 1
    assert report.low_payout == 1
    assert report.non_positive_expectancy == 1
    assert report.by_asset["GBPUSD-OTC"].total == 2
    assert report.by_source["telegram"].rejected == 1
    assert report.by_calibration_version["<missing>"].total == 1

    payload = json.loads(report.to_json())
    assert list(payload["by_asset"]) == ["EURUSD-OTC", "GBPUSD-OTC"]
    assert payload["rejection_reasons"]["signal is stale"] == 1
    assert report.to_json() == report.to_json()
    assert "| GBPUSD-OTC | 2 | 0 | 2 |" in report.to_markdown()
    assert "Approval rate | 20.0000%" in report.to_markdown()


def test_empty_report_has_zero_rate_and_no_division_error() -> None:
    report = build_otc_parity_report([])

    assert report.total_candidates == 0
    assert report.approval_rate == "0.000000"
    assert report.to_markdown().startswith("# OTC Shadow Parity Report")


def test_report_exposes_calibration_provenance_failures() -> None:
    report = build_otc_parity_report(
        [
            record(10, approved=False, reasons=("calibration version is missing",)),
            record(
                11,
                approved=False,
                reasons=("calibration provenance is not registered",),
            ),
            record(
                12,
                approved=False,
                reasons=("calibration provenance is not deployment approved",),
            ),
        ]
    )

    assert report.missing_calibration_version == 1
    assert report.unregistered_calibration == 1
    assert report.unapproved_calibration == 1
