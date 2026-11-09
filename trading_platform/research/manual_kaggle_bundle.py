"""Prepare and validate inspectable, credential-free Kaggle upload bundles."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Iterable
import zipfile

import yaml

from trading_platform.research.training_provenance import sha256_file


ALLOWED_DATA_SUFFIXES = (".parquet", ".csv", ".csv.gz")
FORBIDDEN_NAME_PARTS = (
    ".env",
    "secret",
    "session",
    "credential",
    "private_key",
    ".sqlite",
    ".sqlite3",
    ".db",
    "-wal",
    "-shm",
)


def _validate_dataset_id(dataset_id: str) -> str:
    dataset_id = dataset_id.strip()
    if not dataset_id or not all(char.isalnum() or char in "-_" for char in dataset_id):
        raise ValueError("dataset_id may contain only letters, numbers, '-' and '_'")
    return dataset_id


def _validate_data_path(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"data input must be a regular file: {path}")
    lowered = path.name.lower()
    if any(part in lowered for part in FORBIDDEN_NAME_PARTS):
        raise ValueError(f"forbidden upload filename: {path.name}")
    if not any(lowered.endswith(suffix) for suffix in ALLOWED_DATA_SUFFIXES):
        raise ValueError(f"unsupported research-data file: {path.name}")


def _write_source_archive(
    destination: Path,
    platform_root: Path,
    trainer: Path,
    dataset_id: str,
    contract: Path | None = None,
) -> None:
    if not platform_root.is_dir() or not trainer.is_file():
        raise ValueError("platform source tree and trainer must exist")
    entries: list[tuple[Path, Path, bytes | None]] = [
        (trainer, Path(trainer.name), None)
    ]
    if contract is not None:
        if not contract.is_file() or contract.is_symlink():
            raise ValueError("research contract must be a regular file")
        payload = yaml.safe_load(contract.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != "research_contract_v1":
            raise ValueError("unsupported research contract")
        declared_dataset_id = str(payload.get("dataset_id", "")).strip()
        if declared_dataset_id not in {dataset_id, "replace-with-export-dataset-id"}:
            raise ValueError("research contract dataset_id does not match the bundle")
        payload["dataset_id"] = dataset_id
        resolved_contract = yaml.safe_dump(payload, sort_keys=False).encode("utf-8")
        entries.append(
            (
                contract,
                Path("configs/research") / contract.name,
                resolved_contract,
            )
        )
    entries.extend(
        (path, Path("trading_platform") / path.relative_to(platform_root), None)
        for path in platform_root.rglob("*.py")
        if path.is_file() and not path.is_symlink()
    )
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, relative, content in sorted(entries, key=lambda item: str(item[1])):
            info = zipfile.ZipInfo(str(relative).replace("\\", "/"))
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes() if content is None else content)


def _write_data_archive(destination: Path, entries: list[tuple[Path, Path]]) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, relative in sorted(entries, key=lambda item: str(item[1])):
            info = zipfile.ZipInfo(relative.as_posix())
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())


def _finalize_bundle(
    *,
    bundle: Path,
    dataset_id: str,
    records: list[dict],
    platform_root: Path,
    trainer: Path,
    contract: Path | None,
    created_at: datetime | None,
    extra_manifest: dict | None = None,
) -> Path:
    source_archive = bundle / "platform-source.zip"
    _write_source_archive(source_archive, platform_root, trainer, dataset_id, contract)
    records.append(
        {
            "path": source_archive.name,
            "size": source_archive.stat().st_size,
            "sha256": sha256_file(source_archive),
        }
    )
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    manifest = {
        "schema_version": "manual_kaggle_bundle_v1",
        "dataset_id": dataset_id,
        "created_at": timestamp.isoformat(),
        "files": records,
        "instructions": (
            "Upload every item in UPLOAD_ME to one private Kaggle dataset; "
            "never upload the live SQLite database or credentials."
        ),
        **(extra_manifest or {}),
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    validate_manual_bundle(bundle)
    return bundle


def prepare_manual_bundle(
    *,
    dataset_id: str,
    data_files: Iterable[Path],
    output_root: Path,
    platform_root: Path,
    trainer: Path,
    contract: Path | None = None,
    created_at: datetime | None = None,
) -> Path:
    dataset_id = _validate_dataset_id(dataset_id)
    inputs = [Path(path) for path in data_files]
    if not inputs:
        raise ValueError("at least one exported research-data file is required")
    for path in inputs:
        _validate_data_path(path)
    names = [path.name for path in inputs]
    if len(names) != len(set(names)):
        raise ValueError("data input basenames must be unique")

    bundle = output_root / f"otc-{dataset_id}" / "UPLOAD_ME"
    if bundle.exists():
        raise FileExistsError(f"bundle already exists: {bundle}")
    data_dir = bundle / "data"
    data_dir.mkdir(parents=True)
    records = []
    for source in sorted(inputs, key=lambda item: item.name):
        destination = data_dir / source.name
        shutil.copyfile(source, destination)
        records.append(
            {
                "path": f"data/{destination.name}",
                "size": destination.stat().st_size,
                "sha256": sha256_file(destination),
            }
        )

    return _finalize_bundle(
        bundle=bundle,
        dataset_id=dataset_id,
        records=records,
        platform_root=platform_root,
        trainer=trainer,
        contract=contract,
        created_at=created_at,
    )


def prepare_bundle_from_export(
    *,
    dataset_id: str,
    export_manifest: Path,
    output_root: Path,
    platform_root: Path,
    trainer: Path,
    contract: Path | None = None,
    max_part_size_mb: int = 1_000,
    created_at: datetime | None = None,
) -> Path:
    dataset_id = _validate_dataset_id(dataset_id)
    if max_part_size_mb <= 0:
        raise ValueError("max_part_size_mb must be positive")
    export = json.loads(export_manifest.read_text(encoding="utf-8"))
    if export.get("schema_version") not in {
        "sqlite_research_export_v1",
        "prepared_research_dataset_v1",
    }:
        raise ValueError("unsupported research export manifest")
    export_root = export_manifest.parent
    entries = []
    for record in export.get("records", []):
        if "path" not in record:
            continue
        relative = Path(str(record["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("export manifest contains an unsafe path")
        source = export_root / relative
        _validate_data_path(source)
        if source.stat().st_size != int(record["size"]):
            raise ValueError(f"export size mismatch: {relative}")
        if sha256_file(source) != record["sha256"]:
            raise ValueError(f"export checksum mismatch: {relative}")
        entries.append((source, Path("data") / relative))
    if not entries:
        raise ValueError("export manifest contains no research-data files")

    bundle = output_root / f"otc-{dataset_id}" / "UPLOAD_ME"
    if bundle.exists():
        raise FileExistsError(f"bundle already exists: {bundle}")
    maximum = max_part_size_mb * 1024 * 1024
    groups: list[list[tuple[Path, Path]]] = []
    current: list[tuple[Path, Path]] = []
    current_size = 0
    for entry in sorted(entries, key=lambda item: item[1].as_posix()):
        size = entry[0].stat().st_size
        if size > maximum:
            raise ValueError(
                f"export file exceeds max part size and must be re-exported "
                f"with fewer chunk rows: {entry[1]}"
            )
        if current and current_size + size > maximum:
            groups.append(current)
            current = []
            current_size = 0
        current.append(entry)
        current_size += size
    groups.append(current)

    bundle.mkdir(parents=True)
    records = []
    for index, group in enumerate(groups, start=1):
        archive = bundle / f"otc-data-part-{index:03d}.zip"
        _write_data_archive(archive, group)
        records.append(
            {
                "path": archive.name,
                "size": archive.stat().st_size,
                "sha256": sha256_file(archive),
                "uncompressed_size": sum(path.stat().st_size for path, _ in group),
                "members": [relative.as_posix() for _, relative in group],
            }
        )
    copied_manifest = bundle / "export-manifest.json"
    shutil.copyfile(export_manifest, copied_manifest)
    records.append(
        {
            "path": copied_manifest.name,
            "size": copied_manifest.stat().st_size,
            "sha256": sha256_file(copied_manifest),
        }
    )
    return _finalize_bundle(
        bundle=bundle,
        dataset_id=dataset_id,
        records=records,
        platform_root=platform_root,
        trainer=trainer,
        contract=contract,
        created_at=created_at,
        extra_manifest={
            "source_export_manifest_sha256": sha256_file(export_manifest),
            "max_part_size_mb": max_part_size_mb,
        },
    )


def validate_manual_bundle(bundle: Path) -> dict:
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "manual_kaggle_bundle_v1":
        raise ValueError("unsupported manual bundle schema")
    declared = set()
    for record in manifest.get("files", []):
        relative = Path(str(record["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("manifest contains an unsafe path")
        path = bundle / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"declared file is missing or unsafe: {relative}")
        if path.stat().st_size != int(record["size"]):
            raise ValueError(f"size mismatch: {relative}")
        if sha256_file(path) != record["sha256"]:
            raise ValueError(f"checksum mismatch: {relative}")
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    members = archive.namelist()
                    if archive.testzip() is not None:
                        raise ValueError(f"corrupt ZIP member: {relative}")
            except zipfile.BadZipFile as exc:
                raise ValueError(f"invalid ZIP archive: {relative}") from exc
            if any(
                Path(member).is_absolute() or ".." in Path(member).parts
                for member in members
            ):
                raise ValueError(f"unsafe ZIP member path: {relative}")
            if "members" in record and members != list(record["members"]):
                raise ValueError(f"ZIP member manifest mismatch: {relative}")
        declared.add(relative.as_posix())
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual != declared:
        raise ValueError("bundle contains undeclared or missing files")
    return manifest
