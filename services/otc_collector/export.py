"""Freeze consistent SQLite backup plus canonical observations and receipt lineage."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from .protocol import canonical, digest


def freeze(database, output):
    output = Path(output).resolve()
    if not output.is_relative_to(Path("/tmp")) or output.exists():
        raise ValueError("export directory must be a new /tmp directory")
    output.mkdir(parents=True)
    source = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    snapshot = output / "receipts.sqlite"
    conn = sqlite3.connect(snapshot)
    try:
        source.backup(conn)
    finally:
        source.close()
    try:
        conn.execute("PRAGMA query_only=ON")
        reg = json.loads(conn.execute("SELECT record_json FROM registration WHERE singleton=1").fetchone()[0])
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("snapshot integrity failure")
        count, admitted = 0, 0
        lineage = {}
        with (output / "observations.jsonl").open("x") as all_rows, (output / "observations-admissible.jsonl").open("x") as safe_rows:
            for obs_raw, meta_raw in conn.execute("SELECT observation_json,lineage_json FROM observations ORDER BY available_ms,event_id"):
                obs, meta = json.loads(obs_raw), json.loads(meta_raw)
                all_rows.write(canonical(obs) + "\n")
                if meta["clock_status"] == "ok":
                    safe_rows.write(canonical(obs) + "\n")
                    admitted += 1
                lineage[obs["event_id"]] = meta
                count += 1
        (output / "lineage.json").write_text(canonical(lineage) + "\n")
        (output / "registration.json").write_text(canonical(reg) + "\n")
        health = [{"health_id": identity, "session_id": session, "at_ms": at, "code": code, "details": json.loads(info)} for identity, session, at, code, info in conn.execute("SELECT * FROM health ORDER BY at_ms,health_id")]
        (output / "health.json").write_text(canonical(health) + "\n")
        sessions = [{"session_id": identity, "transition": transition, "at_ms": at, "details": json.loads(info)} for identity, transition, at, info in conn.execute("SELECT * FROM sessions ORDER BY at_ms,session_id,transition")]
        (output / "sessions.json").write_text(canonical(sessions) + "\n")
        unclosed = conn.execute("SELECT count(*) FROM sessions s WHERE s.transition='open' AND NOT EXISTS(SELECT 1 FROM sessions c WHERE c.session_id=s.session_id AND c.transition='close')").fetchone()[0]
    finally:
        conn.close()
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(output.iterdir())}
    manifest = {"schema": "fresh_otc_export_v1", "registration_sha256": reg["registration_sha256"],
                "code_sha256": reg["code_sha256"], "config_sha256": reg["config_sha256"],
                "observation_count": count, "admissible_clock_observation_count": admitted,
                "unclosed_sessions": unclosed, "hashes": hashes,
                "source_clock": "receiver_utc", "quote_product_basis": "explicit_assumed",
                "evidence_class": "received_price_proxy", "research_scope": "exploratory_development",
                "admission": "fresh_loader_checks_required; schedule/coverage/faults remain visible"}
    manifest["manifest_sha256"] = digest(manifest)
    (output / "manifest.json").write_text(canonical(manifest) + "\n")
    return manifest
