"""Validate and materialize a manually uploaded Kaggle dataset."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import stat
import zipfile

from trading_platform.research.manual_kaggle_bundle import validate_manual_bundle
from trading_platform.research.sqlite_export import validate_research_export


def discover_bundle(input_root: Path, dataset_id: str | None = None) -> Path:
    matches = []
    for manifest in input_root.rglob("manifest.json"):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("schema_version") != "manual_kaggle_bundle_v1":
            continue
        if dataset_id is None or payload.get("dataset_id") == dataset_id:
            matches.append(manifest.parent)
    if not matches:
        raise FileNotFoundError("no matching manual Kaggle bundle was mounted")
    if len(matches) != 1:
        raise ValueError("multiple matching Kaggle bundles are mounted; specify dataset_id")
    return matches[0]


def _safe_extract(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            relative = Path(info.filename)
            mode = info.external_attr >> 16
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or stat.S_ISLNK(mode)
            ):
                raise ValueError(f"unsafe ZIP member: {info.filename}")
            target = destination / relative
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists():
                raise FileExistsError(f"ZIP member would overwrite: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def prepare_kaggle_workspace(
    *,
    bundle: Path,
    working_root: Path,
) -> dict:
    manifest = validate_manual_bundle(bundle)
    data_root = working_root / "dataset"
    source_root = working_root / "platform"
    if data_root.exists() or source_root.exists():
        raise FileExistsError("Kaggle workspace destinations must not already exist")
    data_root.mkdir(parents=True)
    source_root.mkdir(parents=True)
    for archive in sorted(bundle.glob("otc-data-part-*.zip")):
        _safe_extract(archive, data_root)
    _safe_extract(bundle / "platform-source.zip", source_root)
    export_manifest = data_root / "data" / "manifest.json"
    shutil.copyfile(bundle / "export-manifest.json", export_manifest)
    export = validate_research_export(export_manifest)
    result = {
        "dataset_id": manifest["dataset_id"],
        "data_root": str(data_root / "data"),
        "source_root": str(source_root),
        "export_manifest": str(export_manifest),
        "collector_schema_version": export.get("collector_schema_version"),
    }
    (working_root / "workspace.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result
