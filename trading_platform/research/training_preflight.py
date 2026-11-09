"""Fail-fast environment checks for allowlisted research trainers."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import shutil
from typing import Callable


COMMON_MODULES = {"joblib", "numpy", "pandas", "pyarrow", "sklearn"}
TRAINER_MODULES = {
    "catboost_directional": COMMON_MODULES | {"catboost", "pandas_ta"},
    "catboost_gate": COMMON_MODULES | {"catboost"},
    "lstm_stationary": COMMON_MODULES
    | {"onnx", "onnxruntime", "pandas_ta", "torch"},
    "lstm_regime_mtf": COMMON_MODULES
    | {"onnx", "onnxruntime", "pandas_ta", "torch"},
}


def _existing_parent(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise FileNotFoundError(path)
        candidate = parent
    return candidate


def preflight_training_run(
    run: dict,
    *,
    module_finder: Callable[[str], object | None] = find_spec,
    disk_usage: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage,
    minimum_fixed_bytes: int = 512 * 1024 * 1024,
) -> dict:
    trainer = str(run.get("trainer", ""))
    if trainer not in TRAINER_MODULES:
        raise ValueError(f"unsupported trainer preflight: {trainer}")
    data = Path(str(run.get("data", "")))
    if not data.is_file() or data.stat().st_size <= 0:
        raise ValueError("training data must be a non-empty regular file")
    required_modules = sorted(TRAINER_MODULES[trainer])
    missing = sorted(name for name in required_modules if module_finder(name) is None)
    if missing:
        raise RuntimeError("missing training dependencies: " + ", ".join(missing))
    required_free = max(int(minimum_fixed_bytes), data.stat().st_size * 3)
    output_parent = _existing_parent(Path(str(run["output"])).parent)
    total, used, free = disk_usage(output_parent)
    if int(free) < required_free:
        raise RuntimeError(
            f"insufficient free disk space: need {required_free} bytes, have {free}"
        )
    return {
        "schema_version": "training_preflight_v1",
        "ready": True,
        "trainer": trainer,
        "data_size_bytes": data.stat().st_size,
        "required_modules": required_modules,
        "missing_modules": [],
        "disk_path": str(output_parent),
        "disk_total_bytes": int(total),
        "disk_used_bytes": int(used),
        "disk_free_bytes": int(free),
        "required_free_bytes": required_free,
    }
