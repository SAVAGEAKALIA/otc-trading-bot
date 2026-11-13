"""CLI: freeze | verify | evaluate.

  .venv-lab/bin/python -m services.otc_sparse_prereg.run freeze
  .venv-lab/bin/python -m services.otc_sparse_prereg.run verify
  .venv-lab/bin/python -m services.otc_sparse_prereg.run evaluate --forward-db data/forward/sparse_forward.sqlite

freeze reads only the spent archive's past-return features (z0, mkt0, gap, posr20); no label is computed.
evaluate refuses to run unless every registered source hash still matches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from services.otc_quant_lab import data

from . import certify, labels, spec, triggers

ROOT = Path(__file__).resolve().parents[2]
REGISTRATION = ROOT / "docs/research/otc-lab/sparse-entry/registration.json"
LOOKS_DIR = ROOT / "docs/research/otc-lab/sparse-entry/looks"
LOG = ROOT / "docs/research/otc-lab/sparse-entry/looks.jsonl"
PLACEBO_SEED = 20261113
DEVIATIONS = [
    "H5 trades one asset per timestamp (the same-sign asset with the largest abs(z0)) so each cluster is"
    " one trade; the report counted asset-bars and noted that clusters bind.",
    "H3 fires on the first bar of an excursion only; the report's frequency counted every bar beyond"
    " 2.5. exact_rule_counts below are the registered frequencies.",
    "All scales use prior data only: vol60 excludes the current bar, the H3 anchor must span <= 1.1 days,"
    " H4 measures the approach against the touched level and needs 30 contiguous prior bars, H8 needs"
    " 20 contiguous bars. Archive counts are recomputed under these rules.",
    "Overlapping trades are dropped: an event is kept only if its entry is at or after the previous kept"
    " trade's expiry on the same hypothesis and asset.",
    "Horizons: H1 210 days and H6 100 days (report calendar: about 204 and 92 days to n at +5 pt); all"
    " others 60 days. H8 is in-family with the standard look although the report calls it a monitor.",
    "Expiry is modeled as entry + duration on 1-s closes; IQ contracts expire on clock boundaries, so"
    " labels are a price proxy and a CERTIFIED row still needs broker-settled practice confirmation.",
]
SOURCES = [
    "services/otc_sparse_prereg/__init__.py", "services/otc_sparse_prereg/spec.py",
    "services/otc_sparse_prereg/stats.py", "services/otc_sparse_prereg/triggers.py",
    "services/otc_sparse_prereg/labels.py", "services/otc_sparse_prereg/certify.py",
    "services/otc_sparse_prereg/run.py", "services/otc_sparse_prereg/collect.sh",
    "services/otc_sparse_prereg/evals/eval_power.py", "services/otc_quant_lab/risk.py",
    "services/otc_quant_lab/metrics.py", "services/otc_quant_lab/data.py",
    "trading_platform/scripts/harvest_market_data.py",
]
ASSETS = ("EURUSD-OTC,GBPUSD-OTC,USDJPY-OTC,AUDUSD-OTC,NZDUSD-OTC,USDCAD-OTC,USDCHF-OTC,EURGBP-OTC,"
          "EURJPY-OTC,GBPJPY-OTC,EURAUD-OTC,GBPAUD-OTC,AUDJPY-OTC,CHFJPY-OTC,CADJPY-OTC")
COLLECTION = {
    "harvester": "trading_platform/scripts/harvest_market_data.py",
    "live_flags": ["--mode", "live", "--assets", ASSETS, "--payout-interval-seconds", "30",
                   "--mood-interval-seconds", "5", "--live-timeframes", "1,120,300", "--no-binary-deals",
                   "--account-type", "PRACTICE"],
    "backfill_flags": ["--mode", "backfill", "--assets", ASSETS, "--history-timeframes", "120,300",
                       "--history-days", "<days since forward start + 3>"],
    "backfill_schedule": "once before each evaluation look (live stopped first, so only one session logs in);"
                         " trigger candles for H2-H5 and H8 come only from history-API candles",
    "forward_db": "data/forward/sparse_forward.sqlite",
    "launcher": "services/otc_sparse_prereg/collect.sh",
}


def sha256(path: Path) -> str:
    return data.sha256_file(path)


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def source_hashes() -> dict:
    return {p: sha256(ROOT / p) for p in SOURCES}


def freeze(args) -> int:
    now = int(time.time() * 1000)
    if now >= spec.FORWARD_START_MS:
        print("refusing: the forward block has started; a registration must precede it", file=sys.stderr)
        return 2
    if REGISTRATION.exists() and not args.force:
        print(f"refusing: {REGISTRATION} exists (use --force only before the forward start)", file=sys.stderr)
        return 2
    bars = data.load_historical(spec.ARCHIVE_TIMEFRAME_S)
    f = triggers.candle_frame(bars)
    thr = triggers.thresholds_from_archive(f)
    days = int(f.loc[f.valid, "t"].floordiv(86400).nunique())
    no = triggers.non_overlapping
    counts = {  # exact frozen rules on the spent archive: counts only, outcomes never read
        "H2": len(no(triggers.h2(f, thr))), "H2b": len(no(triggers.h2b(f, thr))), "H3": len(no(triggers.h3(f))),
        "H4": len(no(triggers.h4(bars))), "H5": len(no(triggers.h5(f, thr))),
        "H8": len(no(triggers.h8(data.load_historical(300)))),
    }
    reg = {
        "name": "otc-sparse-entry family, pre-registration",
        "created_utc": datetime.fromtimestamp(now / 1000, timezone.utc).isoformat(),
        "report": "docs/research/otc-lab/2026-11-12-sparse-entry-research.md",
        "spec": spec.as_dict(),
        "thresholds": thr,
        "archive": {"path": "data/ml/historical_candles.sqlite", "sha256": sha256(data.HISTORICAL_DB),
                    "first_bar_utc": datetime.fromtimestamp(int(bars.t.min()), timezone.utc).isoformat(),
                    "last_bar_utc": datetime.fromtimestamp(int(bars.t.max()), timezone.utc).isoformat(),
                    "valid_days": days, "exact_rule_counts": counts,
                    "exact_rule_per_day": {k: round(v / days, 2) for k, v in counts.items()}},
        "deviations_from_report": DEVIATIONS,
        "collection": COLLECTION,
        "libraries": {m.__name__: m.__version__ for m in (np, pd, __import__("scipy"))},
        "python": sys.version.split()[0],
        "source_hashes": source_hashes(),
    }
    reg["registration_sha256"] = hashlib.sha256(canonical(reg)).hexdigest()
    REGISTRATION.parent.mkdir(parents=True, exist_ok=True)
    REGISTRATION.write_text(json.dumps(reg, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"registration": str(REGISTRATION.relative_to(ROOT)),
                      "sha256": reg["registration_sha256"], "exact_rule_counts": counts}, indent=1))
    return 0


def verify(_args=None, quiet: bool = False) -> bool:
    if not REGISTRATION.is_file():
        if not quiet:
            print(json.dumps({"ok": False, "problems": ["no registration"]}))
        return False
    reg = json.loads(REGISTRATION.read_text())
    claimed = reg.pop("registration_sha256")
    problems = []
    if hashlib.sha256(canonical(reg)).hexdigest() != claimed:
        problems.append("registration body changed after freezing")
    for path, digest in reg["source_hashes"].items():
        target = ROOT / path
        if not target.is_file():
            problems.append(f"registered source missing: {path}")
        elif sha256(target) != digest:
            problems.append(f"source changed since freeze: {path}")
    if reg["spec"] != json.loads(json.dumps(spec.as_dict())):
        problems.append("spec.py differs from the registered spec")
    if not quiet:
        print(json.dumps({"ok": not problems, "problems": problems, "sha256": claimed}, indent=1))
    return not problems


def _read(db: Path, sql: str) -> pd.DataFrame:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        return pd.read_sql_query(sql, c)


def load_forward(db: Path) -> dict:
    warm = spec.FORWARD_START_MS - 2 * spec.DAY_MS  # 720-bar anchor and 64-bar warm-up
    hist = lambda tf: _read(db, f"select broker_asset as asset, candle_start_ms/1000 as t, open as o, high as h,"
                                f" low as l, close as c from historical_candles where timeframe_sec={tf}"
                                f" and candle_start_ms >= {warm} order by asset, t")
    return {
        "bars2": data._clean(hist(120)), "bars5": data._clean(hist(300)),
        "payouts": _read(db, "select broker_asset as asset, instrument_type, received_at_ms, payout_fraction, source"
                             f" from payout_samples where payout_fraction is not null and received_at_ms >= {warm}"),
        "mood": _read(db, "select broker_asset as asset, received_at_ms, call_fraction from mood_samples"
                          f" where instrument_type='turbo-option' and received_at_ms >= {warm}"),
        "quotes": _read(db, f"select broker_asset as asset, received_at_ms, mid from quote_samples"
                            f" where received_at_ms >= {warm}"),
        "c1": _read(db, "select broker_asset as asset, candle_start_ms, close from realtime_candles"
                        f" where timeframe_sec=1 and candle_start_ms >= {spec.FORWARD_START_MS}"),
    }


def build_labeled(d: dict, thr: dict, placebos: int = certify.PLACEBO_REQUIRED) -> tuple[dict, dict]:
    """All family events -> non-overlapping -> forward-only -> labeled. Plus H1 control and H4 placebos."""
    fwd = lambda e: triggers.non_overlapping(e[e.decision_ms >= spec.FORWARD_START_MS])
    lab = lambda e: labels.label(fwd(e), d["c1"], d["payouts"])
    ev = {}
    if len(d["bars2"]):
        f = triggers.candle_frame(d["bars2"])
        ev.update(H2=triggers.h2(f, thr), H2b=triggers.h2b(f, thr), H3=triggers.h3(f),
                  H4=triggers.h4(d["bars2"]), H5=triggers.h5(f, thr))
    if len(d["bars5"]):
        ev["H8"] = triggers.h8(d["bars5"])
    ev.update(H1=triggers.h1(d["payouts"], d["mood"]), H6=triggers.h6(d["payouts"], d["mood"]),
              H7=triggers.h7(d["quotes"]))
    labeled = {k: lab(v) for k, v in ev.items()}
    extras = {"H1": {"control": lab(triggers.h1_control(d["payouts"], d["mood"]))}}
    if len(d["bars2"]) and placebos:
        offsets = np.random.default_rng(PLACEBO_SEED).uniform(0.1, 0.9, placebos)  # away from the real lattice
        extras["H4"] = {"placebos": [lab(triggers.h4(d["bars2"], float(o))) for o in offsets]}
    return labeled, extras


def read_sealed() -> dict:
    out = {}
    if LOOKS_DIR.is_dir():
        for p in LOOKS_DIR.glob("*.json"):
            out[p.stem] = json.loads(p.read_text())["result"]
    return out


def seal(result: certify.Result, reg_sha: str, now_ms: int) -> None:
    LOOKS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOOKS_DIR / f"{result.hid}.json"
    with open(path, "x") as fh:  # write-once: an existing seal raises, so a look can never be redone
        json.dump({"sealed_utc": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(),
                   "registration_sha256": reg_sha, "result": result.as_dict()}, fh, indent=1, default=float)


def gates_pass() -> tuple[bool, dict]:
    from .evals import eval_power
    out = eval_power.run_all()
    return out["passed"], out["checks"]


def evaluate(args) -> int:
    if not verify(quiet=True):
        verify()
        print("refusing to evaluate: registration does not verify", file=sys.stderr)
        return 2
    reg = json.loads(REGISTRATION.read_text())
    d = load_forward(Path(args.forward_db))
    last_data = max([int(d["c1"].candle_start_ms.max())] if len(d["c1"]) else [0])
    now_ms = min(int(time.time() * 1000), last_data)  # never later than the wall clock or the data
    labeled, extras = build_labeled(d, reg["thresholds"])
    sealed = read_sealed()
    results = certify.evaluate_family(labeled, now_ms, extras, sealed)
    newly = [r for r in results if r.hid not in sealed and r.state in certify.SEAL_STATES]
    gate_ok, gate_checks = (True, {}) if not newly else gates_pass()
    if newly and not gate_ok:
        results = [r if r.hid in sealed or r.state not in certify.SEAL_STATES else
                   certify.Result(hid=r.hid, state="GATE-FAILED", n_events=r.n_events, n_labeled=r.n_labeled,
                                  n_target=r.n_target, look_reached=r.look_reached, note="G2/G3 did not pass")
                   for r in results]
    else:
        for r in newly:
            seal(r, reg["registration_sha256"], now_ms)
    out = {"evaluated_utc": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(),
           "registration_sha256": reg["registration_sha256"], "gates": gate_checks,
           "results": [r.as_dict() for r in results],
           "label_coverage": {k: v.label_status.value_counts().to_dict() for k, v in labeled.items() if len(v)}}
    print(json.dumps(out, indent=1, default=float))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:  # every evaluation is logged
        fh.write(json.dumps(out, default=float) + "\n")
    return 0


def status(args) -> int:
    """Collection health only: row counts, coverage, receipt ages, schedule progress. Reads no outcome."""
    db = Path(args.forward_db)
    now = int(time.time() * 1000)
    out = {"utc": datetime.fromtimestamp(now / 1000, timezone.utc).isoformat(timespec="seconds")}
    if not db.exists():
        out["error"] = f"{db} does not exist yet"
        print(json.dumps(out))
        return 1
    tables = {"realtime_candles_1s": "select count(*), max(received_at_ms) from realtime_candles where timeframe_sec=1",
              "quote_samples": "select count(*), max(received_at_ms) from quote_samples",
              "mood_samples": "select count(*), max(received_at_ms) from mood_samples",
              "payout_samples": "select count(*), max(received_at_ms) from payout_samples",
              "historical_candles": "select count(*), max(harvested_at_ms) from historical_candles"}
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        for name, sql in tables.items():
            try:
                n, last = c.execute(sql).fetchone()
            except sqlite3.OperationalError:
                n, last = 0, None
            out[name] = {"rows": n, "last_age_s": None if last is None else round((now - last) / 1000)}
        try:
            secs = c.execute("select count(distinct candle_start_ms/1000) from realtime_candles where timeframe_sec=1"
                             f" and candle_start_ms >= {spec.FORWARD_START_MS}").fetchone()[0]
        except sqlite3.OperationalError:
            secs = 0
    elapsed = max(0, now - spec.FORWARD_START_MS)
    out["forward_elapsed_days"] = round(elapsed / spec.DAY_MS, 2)
    out["percent_of_60_days"] = round(min(100.0, 100 * elapsed / (60 * spec.DAY_MS)), 1)
    out["eta_60_days_utc"] = datetime.fromtimestamp((spec.FORWARD_START_MS + 60 * spec.DAY_MS) / 1000,
                                                    timezone.utc).isoformat(timespec="minutes")
    out["one_second_coverage"] = round(secs / max(1, elapsed // 1000), 4) if elapsed else None
    stale = [k for k, v in out.items() if isinstance(v, dict) and k != "historical_candles"
             and (v["last_age_s"] is None or v["last_age_s"] > 300)]
    out["stale_streams"] = stale
    line = json.dumps(out)
    print(line)
    if args.progress_log:
        Path(args.progress_log).parent.mkdir(parents=True, exist_ok=True)
        with open(args.progress_log, "a") as fh:
            fh.write(f"OTC sparse forward collection | {line}\n")
    return 0 if not stale else 3


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    fz = sub.add_parser("freeze")
    fz.add_argument("--force", action="store_true")
    sub.add_parser("verify")
    e = sub.add_parser("evaluate")
    e.add_argument("--forward-db", required=True)
    s = sub.add_parser("status")
    s.add_argument("--forward-db", default=COLLECTION["forward_db"])
    s.add_argument("--progress-log", default="data/forward/progress.log")
    a = p.parse_args(argv)
    if a.cmd == "status":
        return status(a)
    if a.cmd == "freeze":
        return freeze(a)
    if a.cmd == "verify":
        return 0 if verify(a) else 1
    return evaluate(a)


if __name__ == "__main__":
    raise SystemExit(main())
