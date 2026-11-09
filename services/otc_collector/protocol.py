"""Frozen exploratory schedule and source locks, constructed before networking."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import os

ASSETS = {76: "EURUSD-OTC", 81: "GBPUSD-OTC"}
PRODUCT = "turbo-option"
SCHEMA = "fresh_otc_receipts_v1"
DAY_MS = 86_400_000
CONFIG = {
    "source_priority": {"quote": ["quote_samples"], "mood": ["mood_samples"],
                        "payout": ["commission-stream", "init-snapshot"]},
    "max_age_ms": {"quote": 5000, "mood": 60_000, "payout": 600_000},
    "max_entry_wait_ms": 2000, "max_settlement_wait_ms": 0,
    "lookback_ms": 60_000, "tie_rule": "full_refund",
    "terminal_policy": "last_received_before",
}
LIMITS = {"clock_jump_ms": 1000, "broker_offset_ms": 15_000,
          "clock_sync_max_age_ms": 60_000, "frame_bytes": 1_048_576,
          "queue_capacity": 2048, "http_timeout_s": 10,
          "socket_timeout_s": 5, "snapshot_interval_ms": 300_000,
          "snapshot_timeout_ms": 15_000, "max_reconnects": 8,
          "max_backoff_s": 30, "monitor_interval_s": 30}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc_ms():
    return time.time_ns() // 1_000_000


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_start(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z", value):
        raise ValueError("start requires explicit UTC YYYY-MM-DDTHH:MM:SS[.mmm]Z")
    start = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(start.timestamp() * 1000)


def code_manifest(root=None):
    root = Path(root).resolve() if root is not None else Path(__file__).resolve().parent
    result = {}
    for directory, subdirs, filenames in os.walk(root):
        subdirs[:] = sorted(name for name in subdirs if name != "__pycache__")
        for name in sorted(filenames):
            if name.endswith(".py"):
                path = os.path.join(directory, name)
                with open(path, "rb") as handle:
                    result[os.path.relpath(path, root)] = hashlib.sha256(handle.read()).hexdigest()
    return dict(sorted(result.items()))


def make_registration(start, *, now_ms=None, root=None, research_source_root=None):
    start_ms = parse_start(start)
    if start_ms <= (utc_ms() if now_ms is None else now_ms):
        raise ValueError("registration start must be future UTC; never shifted by coverage")
    if start_ms % 120_000:
        raise ValueError("registration start must align to the fixed 120 second UTC grid")
    boundaries = []
    cursor = start_ms
    for phase, days in (("training", 3), ("early", 1), ("calibration", 1), ("policy", 1), ("diagnostic", 1)):
        end = cursor + days * DAY_MS
        boundaries.append({"phase": phase, "start_ms": cursor, "end_ms": end,
                           "start_utc": iso(cursor), "end_utc": iso(end)})
        cursor = end
    source = code_manifest(root)
    research_root = Path(research_source_root).resolve() if research_source_root is not None else Path(__file__).resolve().parents[2]
    if not (research_root / "services" / "otc_research" / "dataset.py").is_file():
        raise ValueError("registration requires the actual research source root")
    research_source = {}
    for base in (research_root / "services" / "otc_research", research_root / "contracts" / "otc_v1"):
        prefix = os.path.relpath(base, research_root)
        research_source.update({f"{prefix}/{name}": value for name, value in code_manifest(base).items()})
    created = utc_ms() if now_ms is None else now_ms
    partitions = {name: {"start_ms": boundary["start_ms"], "end_ms": boundary["end_ms"]}
                  for name, boundary in zip(("train", "early", "calibration", "policy", "diagnostic_test"), boundaries)}
    record = {"schema": SCHEMA, "registered_at_ms": created,
              "created_ms": created,
              "scope": "exploratory_development_received_price_proxy",
              "accepted_contract_evidence": False, "capital_promotion": False,
              "assets": list(ASSETS.values()), "active_ids": {str(k): v for k, v in ASSETS.items()},
              "product": PRODUCT, "quote_product_basis": "explicit_assumed",
              "start_ms": start_ms, "end_ms": cursor, "start_utc": iso(start_ms), "end_utc": iso(cursor),
              "phases": boundaries, "partitions": partitions, "grid_ms": 120_000, "hypothetical_expiry_ms": 120_000,
              "split_basis": "registered_utc_independent_of_label_coverage",
              "config": CONFIG, "config_sha256": digest(CONFIG), "limits": LIMITS,
              "code_files": source, "code_sha256": digest(source),
              "research_source_root": str(research_root), "research_code_files": research_source,
              "research_code_sha256": digest(research_source),
              "source_hashes": {"collector": source, "research": research_source},
              "source_sha256": digest({"collector": source, "research": research_source}),
              "registration_policy": "fixed7d_train3d_early1d_calibration1d_policy1d_diagnostic1d"}
    record["registration_sha256"] = digest(record)
    return record


def validate_registration(record, *, verify_code=True, root=None):
    if not isinstance(record, dict):
        raise ValueError("invalid registration")
    original = dict(record)
    lock = original.pop("registration_sha256", None)
    if lock != digest(original):
        raise ValueError("registration hash mismatch")
    expected = make_registration(record["start_utc"], now_ms=record["registered_at_ms"], root=root,
                                 research_source_root=record["research_source_root"])
    if record != expected:
        raise ValueError("registration differs from frozen schedule/config/source")
    if verify_code and record["code_files"] != code_manifest(root):
        raise ValueError("source changed after registration")
    return record


def write_registration(path, record):
    path = Path(path).resolve()
    if not path.is_relative_to(Path("/tmp")):
        raise ValueError("registration must live under /tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(canonical(record) + "\n")
        handle.flush()
        import os
        os.fsync(handle.fileno())


def read_registration(path):
    return validate_registration(json.loads(Path(path).read_text()))
