"""Manifest already-built, immutable model-ready research datasets."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Mapping

from trading_platform.research.training_provenance import sha256_file


ALLOWED_ROLES = {"enriched_candles", "enriched_candidates"}


def create_prepared_dataset_manifest(
    *,
    dataset_id: str,
    root: Path,
    files: Mapping[str, Path],
    created_at: datetime | None = None,
) -> Path:
    dataset_id = dataset_id.strip()
    if not dataset_id or not all(char.isalnum() or char in "-_" for char in dataset_id):
        raise ValueError("invalid dataset_id")
    if not files:
        raise ValueError("at least one model-ready dataset file is required")
    unexpected = sorted(set(files) - ALLOWED_ROLES)
    if unexpected:
        raise ValueError("unsupported dataset roles: " + ", ".join(unexpected))
    resolved_root = root.resolve()
    records = []
    for role, raw_path in sorted(files.items()):
        path = raw_path.resolve()
        if resolved_root != path and resolved_root not in path.parents:
            raise ValueError(f"dataset file escapes root: {path}")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"dataset file must be regular: {path}")
        if not (path.name.endswith(".parquet") or path.name.endswith(".csv.gz")):
            raise ValueError(f"unsupported prepared dataset format: {path.name}")
        records.append(
            {
                "role": role,
                "path": path.relative_to(resolved_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    manifest = {
        "schema_version": "prepared_research_dataset_v1",
        "dataset_id": dataset_id,
        "created_at": timestamp.isoformat(),
        "records": records,
    }
    target = root / "manifest.json"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target
