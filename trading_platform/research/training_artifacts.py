"""Read-only validation of downloaded model-artifact directories and ZIPs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import stat
import zipfile

from trading_platform.domain.calibration import CalibrationProvenance


FORBIDDEN_PARTS = (".env", "secret", "credential", "session", "private_key", ".sqlite")


class ArtifactReader:
    def __init__(self, source: Path):
        self.source = source
        self.archive = zipfile.ZipFile(source) if source.is_file() else None
        if self.archive:
            infos = self.archive.infolist()
            names = [info.filename for info in infos if not info.is_dir()]
            if len(names) != len(set(names)):
                raise ValueError("artifact ZIP contains duplicate member names")
            for info in infos:
                relative = Path(info.filename)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or stat.S_ISLNK(info.external_attr >> 16)
                ):
                    raise ValueError(f"unsafe artifact ZIP member: {info.filename}")
            self.names = names
        elif source.is_dir():
            paths = [path for path in source.rglob("*") if path.is_file()]
            if any(path.is_symlink() for path in paths):
                raise ValueError("artifact directory must not contain symlinks")
            self.names = [path.relative_to(source).as_posix() for path in paths]
        else:
            raise FileNotFoundError(source)
        for name in self.names:
            lowered = Path(name).name.lower()
            if any(part in lowered for part in FORBIDDEN_PARTS):
                raise ValueError(f"forbidden file in artifact bundle: {name}")

    def close(self) -> None:
        if self.archive:
            self.archive.close()

    def read_bytes(self, name: str, maximum: int | None = None) -> bytes:
        if self.archive:
            info = self.archive.getinfo(name)
            if maximum is not None and info.file_size > maximum:
                raise ValueError(f"artifact file is too large to parse: {name}")
            with self.archive.open(info) as handle:
                return handle.read()
        path = self.source / name
        if maximum is not None and path.stat().st_size > maximum:
            raise ValueError(f"artifact file is too large to parse: {name}")
        return path.read_bytes()

    def sha256(self, name: str) -> str:
        digest = hashlib.sha256()
        if self.archive:
            handle = self.archive.open(name)
        else:
            handle = (self.source / name).open("rb")
        with handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def size(self, name: str) -> int:
        if self.archive:
            return int(self.archive.getinfo(name).file_size)
        return int((self.source / name).stat().st_size)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_bundle_manifest(reader: ArtifactReader, hashes: dict[str, str]) -> dict | None:
    name = "training_bundle_manifest.json"
    if name not in reader.names:
        return None
    payload = json.loads(reader.read_bytes(name, 5_000_000))
    if payload.get("schema_version") != "training_artifact_bundle_v1":
        raise ValueError("unsupported training artifact bundle manifest")
    records = payload.get("files")
    if not isinstance(records, list):
        raise ValueError("training artifact bundle files must be a list")
    expected_names = set(reader.names) - {name}
    declared_names = {str(record.get("path", "")) for record in records}
    if declared_names != expected_names or len(records) != len(declared_names):
        raise ValueError("training artifact bundle file inventory mismatch")
    for record in records:
        path = str(record["path"])
        if int(record.get("size", -1)) != reader.size(path):
            raise ValueError(f"training artifact bundle size mismatch: {path}")
        if str(record.get("sha256", "")) != hashes[path]:
            raise ValueError(f"training artifact bundle checksum mismatch: {path}")
    return payload


def validate_training_artifacts(source: Path) -> dict:
    reader = ArtifactReader(source)
    try:
        provenance_names = [
            name for name in reader.names
            if Path(name).name.endswith("calibration_provenance.json")
            or Path(name).name == "calibration_provenance.json"
        ]
        if len(provenance_names) != 1:
            raise ValueError("artifact bundle must contain exactly one provenance manifest")
        raw = json.loads(reader.read_bytes(provenance_names[0], 2_000_000))
        provenance = CalibrationProvenance.from_record(raw)
        hashes = {name: reader.sha256(name) for name in reader.names}
        bundle_manifest = _validate_bundle_manifest(reader, hashes)
        if bundle_manifest is not None:
            if bundle_manifest.get("dataset_id") != provenance.dataset_id:
                raise ValueError("training bundle dataset ID does not match provenance")
            if bundle_manifest.get("calibration_id") != provenance.calibration_id:
                raise ValueError("training bundle calibration ID does not match provenance")
        mapping = {}
        for artifact_name, expected in provenance.artifact_sha256.items():
            matches = [name for name, digest in hashes.items() if digest == expected]
            if len(matches) != 1:
                raise ValueError(
                    f"declared artifact {artifact_name!r} matched {len(matches)} files"
                )
            mapping[artifact_name] = matches[0]

        metadata_ids = []
        for name in reader.names:
            if not Path(name).name.endswith("metadata.json"):
                continue
            payload = json.loads(reader.read_bytes(name, 5_000_000))
            if calibration_id := str(payload.get("calibration_id", "")).strip():
                metadata_ids.append(calibration_id)
        if not metadata_ids:
            raise ValueError("artifact metadata must declare the calibration ID")
        if set(metadata_ids) != {provenance.calibration_id}:
            raise ValueError("metadata calibration ID does not match provenance")
        return {
            "calibration_id": provenance.calibration_id,
            "model_version": provenance.model_version,
            "dataset_id": provenance.dataset_id,
            "offline_deployment_approved": provenance.offline_deployment_approved,
            "provenance_manifest": provenance_names[0],
            "artifact_files": mapping,
            "registration_allowed": True,
            "installation_allowed": False,
        }
    finally:
        reader.close()


def package_training_artifacts(source: Path, destination: Path) -> dict:
    """Create a deterministic ZIP only from an already valid artifact directory."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_dir():
        raise ValueError("artifact packaging source must be a directory")
    if destination.exists():
        raise FileExistsError(destination)
    if source == destination.parent or source in destination.parents:
        raise ValueError("artifact archive must be written outside the source directory")
    validation = validate_training_artifacts(source)
    paths = sorted(
        (path for path in source.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source).as_posix(),
    )
    records = []
    for path in paths:
        relative = path.relative_to(source).as_posix()
        records.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    manifest = {
        "schema_version": "training_artifact_bundle_v1",
        "dataset_id": validation["dataset_id"],
        "model_version": validation["model_version"],
        "calibration_id": validation["calibration_id"],
        "files": records,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            entries = [(path, path.relative_to(source).as_posix()) for path in paths]
            entries.append((None, "training_bundle_manifest.json"))
            for path, relative in entries:
                info = zipfile.ZipInfo(relative)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with archive.open(info, "w") as output:
                    if path is None:
                        output.write(
                            (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
                        )
                    else:
                        with path.open("rb") as input_file:
                            shutil.copyfileobj(input_file, output, length=1024 * 1024)
        temporary.replace(destination)
        validate_training_artifacts(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    return {
        "archive": str(destination),
        "sha256": _sha256_file(destination),
        "size": destination.stat().st_size,
        **validation,
    }
