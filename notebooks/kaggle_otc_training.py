#!/usr/bin/env python3
"""Thin trusted bootstrap for the platform-owned Kaggle workspace command."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import sys
import zipfile


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bootstrap(input_root: Path, working_root: Path, dataset_id: str | None) -> dict:
    candidates = []
    for path in input_root.rglob("manifest.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("schema_version") == "manual_kaggle_bundle_v1" and (
            dataset_id is None or payload.get("dataset_id") == dataset_id
        ):
            candidates.append((path.parent, payload))
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one matching bundle; found {len(candidates)}")
    bundle, manifest = candidates[0]
    source_record = next(
        (item for item in manifest["files"] if item["path"] == "platform-source.zip"),
        None,
    )
    if source_record is None:
        raise RuntimeError("platform-source.zip is not declared")
    archive_path = bundle / "platform-source.zip"
    if _sha256(archive_path) != source_record["sha256"]:
        raise RuntimeError("platform-source.zip checksum mismatch")
    bootstrap_root = working_root / "platform-bootstrap"
    if bootstrap_root.exists():
        raise FileExistsError(bootstrap_root)
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            relative = Path(info.filename)
            mode = info.external_attr >> 16
            if relative.is_absolute() or ".." in relative.parts or stat.S_ISLNK(mode):
                raise RuntimeError(f"unsafe source member: {info.filename}")
            target = bootstrap_root / relative
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    sys.path.insert(0, str(bootstrap_root))
    from trading_platform.research.kaggle_workspace import (  # noqa: PLC0415
        prepare_kaggle_workspace,
    )

    return prepare_kaggle_workspace(bundle=bundle, working_root=working_root)


def train(
    workspace: dict,
    contract_name: str,
    output_root: Path,
    *,
    dry_run: bool = False,
) -> dict:
    from trading_platform.research.kaggle_training import (  # noqa: PLC0415
        run_kaggle_training,
    )

    return run_kaggle_training(
        workspace=workspace,
        contract_name=contract_name,
        output_root=output_root,
        dry_run=dry_run,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=Path("/kaggle/input"))
    parser.add_argument("--working-root", type=Path, default=Path("/kaggle/working"))
    parser.add_argument("--dataset-id")
    parser.add_argument("--contract", help="Bundled YAML contract filename")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    workspace = bootstrap(args.input_root, args.working_root, args.dataset_id)
    result = workspace
    if args.contract:
        result = train(
            workspace,
            args.contract,
            args.output or (args.working_root / "output"),
            dry_run=args.dry_run,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
