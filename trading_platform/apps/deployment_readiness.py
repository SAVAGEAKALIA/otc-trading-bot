"""Offline deployment-readiness audit; never contacts brokers."""

from __future__ import annotations

from pathlib import Path


def audit(root: Path) -> tuple[str, ...]:
    findings: list[str] = []
    env_example = root / ".env.example"
    compose = root / "docker-compose.yml"
    migrations = root / "trading_platform/storage/migrations"
    if not env_example.exists(): findings.append("missing .env.example")
    if not compose.exists(): findings.append("missing docker-compose.yml")
    if not (migrations / "0007_hedge_leg_identity.sql").exists(): findings.append("missing hedge-leg migration")
    if (root / ".env").exists() and ".env" not in (root / ".gitignore").read_text(encoding="utf-8"):
        findings.append(".env is not excluded by .gitignore")
    if env_example.exists():
        text = env_example.read_text(encoding="utf-8")
        if "IQ_ACCOUNT_TYPE=PRACTICE" not in text: findings.append("practice account default missing")
        if "PLATFORM_SHADOW_ENABLED=false" not in text: findings.append("platform shadow default is not disabled")
    return tuple(findings)


def main() -> int:
    findings = audit(Path.cwd())
    if findings:
        for finding in findings: print(f"FAIL: {finding}")
        return 1
    print("PASS: offline deployment readiness checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
