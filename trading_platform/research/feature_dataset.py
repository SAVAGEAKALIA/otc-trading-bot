"""Platform-owned orchestration for causal OTC feature-dataset builds."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Protocol

from trading_platform.research.prepared_dataset import create_prepared_dataset_manifest


class FeatureDatasetPort(Protocol):
    def context_start(self, warmup_hours: int) -> int | None: ...
    def load_candles(self, start_ms: int | None, timeframe: int) -> Any: ...
    def enrich_candles(self, candles: Any, timeframe: int) -> Any: ...
    def load_candidates(self) -> Any: ...
    def is_empty(self, value: Any) -> bool: ...
    def technical_candidate_rows(self, enriched: Any) -> Any: ...
    def build_candidate_dataset(self, candidates: Any, featured: Any) -> Any: ...
    def write_frame(self, frame: Any, target: Path) -> Path: ...
    def coverage_report(self, candles: Any, candidates: Any) -> dict: ...


@dataclass(frozen=True, slots=True)
class FeatureDatasetRequest:
    output_dir: Path
    timeframe: int = 120
    warmup_hours: int = 6
    all_history: bool = False
    dataset_id: str | None = None


def build_feature_dataset(
    request: FeatureDatasetRequest,
    port: FeatureDatasetPort,
) -> dict:
    if request.timeframe <= 0:
        raise ValueError("timeframe must be positive")
    if request.warmup_hours < 0:
        raise ValueError("warmup_hours cannot be negative")
    start = None if request.all_history else port.context_start(request.warmup_hours)
    if start is None and not request.all_history:
        raise RuntimeError("No quote/mood/payout context exists yet")
    candles = port.load_candles(start, request.timeframe)
    enriched = port.enrich_candles(candles, request.timeframe)
    candidate_ledger = port.load_candidates()
    if port.is_empty(candidate_ledger):
        candidates = candidate_ledger
    else:
        candidates = port.build_candidate_dataset(
            candidate_ledger,
            port.technical_candidate_rows(enriched),
        )

    request.output_dir.mkdir(parents=True, exist_ok=True)
    candle_path = port.write_frame(
        enriched, request.output_dir / "enriched_candles.parquet"
    )
    candidate_path = None
    if not port.is_empty(candidates):
        candidate_path = port.write_frame(
            candidates, request.output_dir / "enriched_candidates.parquet"
        )
    report = port.coverage_report(enriched, candidates)
    report.update(
        candle_dataset=str(candle_path),
        candidate_dataset=str(candidate_path) if candidate_path else None,
    )
    report_path = request.output_dir / "coverage_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    manifest_path = None
    if request.dataset_id:
        files = {"enriched_candles": candle_path}
        if candidate_path:
            files["enriched_candidates"] = candidate_path
        manifest_path = create_prepared_dataset_manifest(
            dataset_id=request.dataset_id,
            root=request.output_dir.parent,
            files=files,
        )
    return {
        "candle_dataset": candle_path,
        "candidate_dataset": candidate_path,
        "coverage_report": report_path,
        "manifest": manifest_path,
    }
