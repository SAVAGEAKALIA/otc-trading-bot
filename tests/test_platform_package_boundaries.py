"""Architecture tests for the eventual trading-platform project root."""

from __future__ import annotations

import ast
from pathlib import Path


PLATFORM_ROOT = Path("src/trading_platform")
FORBIDDEN_IMPORT_ROOTS = {
    "iqoption_bot",
    "training_provenance",
    "register_calibration_provenance",
    "generate_otc_shadow_parity_report",
}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    return roots


def test_platform_package_never_depends_on_legacy_or_root_shims() -> None:
    violations: dict[str, list[str]] = {}
    for path in PLATFORM_ROOT.rglob("*.py"):
        forbidden = sorted(imported_roots(path) & FORBIDDEN_IMPORT_ROOTS)
        if forbidden:
            violations[str(path)] = forbidden

    assert violations == {}, (
        "trading_platform must own implementations and expose ports; it must "
        f"not import legacy packages or root compatibility shims: {violations}"
    )
