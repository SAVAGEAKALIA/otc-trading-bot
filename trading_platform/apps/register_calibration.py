"""Verify and register a calibrated-model provenance manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine

from trading_platform.domain.calibration import CalibrationProvenance
from trading_platform.research.training_provenance import sha256_file
from trading_platform.storage.repository import LedgerRepository


def load_and_verify(
    manifest_path: Path, artifact_paths: dict[str, Path]
) -> CalibrationProvenance:
    provenance = CalibrationProvenance.from_record(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    required = set(provenance.artifact_sha256)
    supplied = set(artifact_paths)
    if missing := sorted(required - supplied):
        raise ValueError("missing artifact paths: " + ", ".join(missing))
    if unexpected := sorted(supplied - required):
        raise ValueError("unexpected artifact paths: " + ", ".join(unexpected))
    for name, expected in provenance.artifact_sha256.items():
        if sha256_file(artifact_paths[name]) != expected:
            raise ValueError(f"artifact checksum mismatch: {name}")
    return provenance


def parse_artifacts(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or not name.strip() or not raw_path.strip():
            raise ValueError("artifacts must use NAME=PATH")
        if name in result:
            raise ValueError(f"duplicate artifact name: {name}")
        result[name] = Path(raw_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database_url", help="SQLAlchemy URL for the platform ledger")
    parser.add_argument("manifest", type=Path, help="Calibration provenance JSON")
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Artifact named in artifact_sha256; repeat for every artifact",
    )
    args = parser.parse_args()
    provenance = load_and_verify(args.manifest, parse_artifacts(args.artifact))
    engine = create_engine(args.database_url, pool_pre_ping=True)
    try:
        inserted = LedgerRepository(engine).register_calibration_provenance(provenance)
    finally:
        engine.dispose()
    status = "registered" if inserted else "already registered"
    print(f"{provenance.calibration_id}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
