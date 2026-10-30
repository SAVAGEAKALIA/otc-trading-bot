from pathlib import Path

from trading_platform.research.feature_dataset import (
    FeatureDatasetRequest,
    build_feature_dataset,
)


class FakePort:
    def __init__(self, candidates=None):
        self.candidates = candidates or []
        self.calls = []

    def context_start(self, warmup_hours):
        self.calls.append(("context_start", warmup_hours))
        return 1000

    def load_candles(self, start_ms, timeframe):
        self.calls.append(("load_candles", start_ms, timeframe))
        return ["candle"]

    def enrich_candles(self, candles, timeframe):
        return ["enriched"]

    def load_candidates(self):
        return self.candidates

    def is_empty(self, value):
        return not value

    def technical_candidate_rows(self, enriched):
        return ["featured"]

    def build_candidate_dataset(self, candidates, featured):
        return ["candidate-output"]

    def write_frame(self, frame, target):
        target.write_bytes(repr(frame).encode())
        return target

    def coverage_report(self, candles, candidates):
        return {"enriched_candles": len(candles), "candidate_rows": len(candidates)}


def test_platform_orchestrates_build_and_emits_manifest(tmp_path) -> None:
    port = FakePort(candidates=["candidate"])
    result = build_feature_dataset(
        FeatureDatasetRequest(
            output_dir=tmp_path / "prepared/enriched",
            dataset_id="dataset-v1",
        ),
        port,
    )

    assert result["candle_dataset"].is_file()
    assert result["candidate_dataset"].is_file()
    assert result["manifest"] == tmp_path / "prepared/manifest.json"
    assert ("load_candles", 1000, 120) in port.calls


def test_all_history_does_not_require_context_start(tmp_path) -> None:
    port = FakePort()
    build_feature_dataset(
        FeatureDatasetRequest(
            output_dir=tmp_path / "enriched",
            all_history=True,
        ),
        port,
    )

    assert not any(call[0] == "context_start" for call in port.calls)
