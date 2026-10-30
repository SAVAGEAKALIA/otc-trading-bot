from pathlib import Path

import pytest

from trading_platform.research.training_preflight import preflight_training_run


def run_fixture(tmp_path: Path, trainer: str = "catboost_directional") -> dict:
    data = tmp_path / "dataset.parquet"
    data.write_bytes(b"data")
    return {
        "trainer": trainer,
        "data": str(data),
        "output": str(tmp_path / "outputs" / "experiment-v1"),
    }


def test_reports_dependencies_and_bounded_disk_requirement(tmp_path: Path) -> None:
    available = lambda name: object()
    report = preflight_training_run(
        run_fixture(tmp_path),
        module_finder=available,
        disk_usage=lambda path: (10_000, 5_000, 5_000),
        minimum_fixed_bytes=100,
    )

    assert report["ready"] is True
    assert "catboost" in report["required_modules"]
    assert report["required_free_bytes"] == 100


def test_rejects_missing_lstm_dependencies_before_training(tmp_path: Path) -> None:
    def finder(name: str):
        return None if name in {"torch", "onnx"} else object()

    with pytest.raises(RuntimeError, match="onnx, torch"):
        preflight_training_run(
            run_fixture(tmp_path, "lstm_stationary"),
            module_finder=finder,
            disk_usage=lambda path: (10_000, 5_000, 5_000),
            minimum_fixed_bytes=100,
        )


def test_rejects_insufficient_output_disk_space(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="free disk space"):
        preflight_training_run(
            run_fixture(tmp_path),
            module_finder=lambda name: object(),
            disk_usage=lambda path: (100, 99, 1),
            minimum_fixed_bytes=100,
        )
