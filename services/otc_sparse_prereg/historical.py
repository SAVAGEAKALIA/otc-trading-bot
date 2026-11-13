"""Historical test of the frozen family on data already collected (owner's request, 2026-11-13).

Plan (written and committed BEFORE any outcome of these rules is read):
  * Candle rules H2, H2b, H3, H4, H5 (2-min archive) and H8 (5-min archive):
      - thresholds frozen on the first 40% of the 2-min archive's calendar days (threshold block);
      - outcomes read only on the remaining days (test block), same split date for the 5-min archive;
      - label = close-to-close proxy on archive candles: entry = close of the trigger bar, exit = close of
        the bar ending expiry_s later (it must exist exactly), at the nominal payout (0.84 turbo, 0.86 binary);
      - the look is the first n_target non-overlapping trades of the test block, else the whole block.
  * Event rules H1, H6, H7 and the H1 control (live window 2026-07-31 to 2026-08-20):
      - 1-s candle labels and the payout in force, exactly as the forward block (labels.label);
      - payout steps from init-snapshot samples, previous sample at most 2 x 300 s old.
  * Same certificate (certify.evaluate), same alpha 0.05/8, same fail-closed H1 control and H4 placebos.
  * Evidence grade: DEVELOPMENT. The archive was mined by the earlier lab for other rules, the live window
    was read for the crowd-level fade, and archive labels are a bar-close proxy. A CERTIFIED row here earns
    a short forward confirmation of that one row, not money. A non-certified row is retired.

Run once: .venv-lab/bin/python -m services.otc_sparse_prereg.historical --run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from services.otc_quant_lab import data

from . import certify, labels, spec, triggers

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "docs/research/otc-lab/sparse-entry/historical"
PLAN = OUT_DIR / "plan.json"
RESULT = OUT_DIR / "result.json"
THRESHOLD_FRACTION = 0.40
LIVE_PAYOUT_SAMPLE_MS = 300_000
PLACEBO_SEED = 20261113
SOURCES = ["services/otc_sparse_prereg/historical.py", "services/otc_sparse_prereg/triggers.py",
           "services/otc_sparse_prereg/labels.py", "services/otc_sparse_prereg/certify.py",
           "services/otc_sparse_prereg/stats.py", "services/otc_sparse_prereg/spec.py"]
NOMINAL = {"turbo": spec.TURBO_PAYOUT_NOMINAL, "binary": spec.BINARY_PAYOUT_NOMINAL}


def split_day(bars2: pd.DataFrame) -> int:
    days = np.sort(np.unique(bars2.t.to_numpy(np.int64) // 86400))
    return int(days[int(len(days) * THRESHOLD_FRACTION)])


def label_bars(events: pd.DataFrame, bars: pd.DataFrame, tf: int) -> pd.DataFrame:
    """Close-to-close proxy: entry = close of the bar ending at the decision, exit = close of the bar
    ending expiry_s later. Missing exact bars -> unlabeled (availability only, never the outcome)."""
    ev = events.copy().reset_index(drop=True)
    if ev.empty:
        return ev.assign(entry=[], exit=[], payout=[], outcome=[], label_status=[])
    close = bars.assign(end_ms=(bars.t.astype(np.int64) + tf) * 1000).set_index(["asset", "end_ms"]).c
    key_in = list(zip(ev.asset, ev.decision_ms.astype(np.int64)))
    key_out = list(zip(ev.asset, ev.decision_ms.astype(np.int64) + ev.expiry_s.astype(np.int64) * 1000))
    ev["entry"] = close.reindex(key_in).to_numpy()
    ev["exit"] = close.reindex(key_out).to_numpy()
    ev["payout"] = ev["product"].map(NOMINAL).astype(float)
    move = ev.side * (ev.exit - ev.entry)
    ev["outcome"] = np.where(move > 0, labels.WIN, np.where(move < 0, labels.LOSS, labels.TIE)).astype(float)
    ev["label_status"] = np.where(ev.entry.isna(), "missing_entry_price",
                                  np.where(ev.exit.isna(), "missing_exit_price", "labeled"))
    ev.loc[ev.label_status != "labeled", "outcome"] = np.nan
    return ev


def plan() -> dict:
    bars2 = data.load_historical(120)
    cut_day = split_day(bars2)
    body = {
        "name": "historical test of the frozen sparse-entry family",
        "written_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "doc": __doc__,
        "threshold_block": {"first_day_utc": _day(bars2.t.min() // 86400), "last_day_utc": _day(cut_day - 1)},
        "test_block": {"first_day_utc": _day(cut_day), "last_day_utc": _day(bars2.t.max() // 86400)},
        "live_window": "2026-07-31 to 2026-08-20 (data/ml/market_context.sqlite)",
        "archive_sha256": data.sha256_file(data.HISTORICAL_DB),
        "spec": spec.as_dict(),
        "source_hashes": {p: data.sha256_file(ROOT / p) for p in SOURCES},
    }
    body["plan_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


def _day(d) -> str:
    return datetime.fromtimestamp(int(d) * 86400, timezone.utc).date().isoformat()


def run() -> dict:
    stored = json.loads(PLAN.read_text())
    fresh = plan()
    if stored["source_hashes"] != fresh["source_hashes"] or stored["spec"] != fresh["spec"] \
            or stored["archive_sha256"] != fresh["archive_sha256"]:
        raise SystemExit("refusing: code, spec or archive changed since the plan was committed")
    if RESULT.exists():
        raise SystemExit(f"refusing: {RESULT} exists; the historical look is done once")
    no = triggers.non_overlapping
    bars2 = data.load_historical(120)
    bars5 = data.load_historical(300)
    cut_ms = split_day(bars2) * spec.DAY_MS
    f_all = triggers.candle_frame(bars2)
    thr = triggers.thresholds_from_archive(f_all[f_all.t * 1000 < cut_ms])
    test = lambda e: no(e[e.decision_ms >= cut_ms])
    ev = {"H2": test(triggers.h2(f_all, thr)), "H2b": test(triggers.h2b(f_all, thr)),
          "H3": test(triggers.h3(f_all)), "H4": test(triggers.h4(bars2)), "H5": test(triggers.h5(f_all, thr)),
          "H8": test(triggers.h8(bars5))}
    lab = {k: label_bars(v, bars5 if k == "H8" else bars2, 300 if k == "H8" else 120) for k, v in ev.items()}
    offsets = np.random.default_rng(PLACEBO_SEED).uniform(0.1, 0.9, certify.PLACEBO_REQUIRED)
    placebos = [label_bars(test(triggers.h4(bars2, float(o))), bars2, 120) for o in offsets]

    live = data.CONTEXT_DB
    q = lambda sql: pd.read_sql_query(sql, data._connect(live))
    payouts = q("select broker_asset as asset, instrument_type, received_at_ms, payout_fraction, source from payout_samples")
    mood = q("select broker_asset as asset, received_at_ms, call_fraction from mood_samples where instrument_type='turbo-option'")
    quotes = q("select broker_asset as asset, received_at_ms, mid from quote_samples")
    c1 = q("select broker_asset as asset, candle_start_ms, close from realtime_candles where timeframe_sec=1")
    live_start = int(c1.candle_start_ms.min())
    lab["H1"] = labels.label(no(triggers.h1(payouts, mood, LIVE_PAYOUT_SAMPLE_MS)), c1, payouts)
    lab["H6"] = labels.label(no(triggers.h6(payouts, mood, LIVE_PAYOUT_SAMPLE_MS)), c1, payouts)
    lab["H7"] = labels.label(no(triggers.h7(quotes)), c1, payouts)
    control = labels.label(no(triggers.h1_control(payouts, mood, LIVE_PAYOUT_SAMPLE_MS)), c1, payouts)

    end_arch = (int(bars2.t.max()) + 86400) * 1000
    end_live = int(c1.candle_start_ms.max()) + spec.DAY_MS
    results = {}
    for h in spec.FAMILY:
        if h.nested_in:
            continue
        is_live = h.hid in ("H1", "H6", "H7")
        start, end = (live_start, end_live) if is_live else (cut_ms, end_arch)
        extras = {"H1": {"control": control}, "H4": {"placebos": placebos}}.get(h.hid)
        results[h.hid] = certify.evaluate(h.hid, lab.get(h.hid), end, extras, start_ms=start, horizon_end_ms=end)
    if results["H2"].state == "CERTIFIED":
        results["H2b"] = certify.evaluate("H2b", lab["H2b"], end_arch, None, start_ms=cut_ms, horizon_end_ms=end_arch)
    else:
        results["H2b"] = certify.Result(hid="H2b", state="NOT-OPENED", n_events=len(lab["H2b"]), n_labeled=0,
                                        n_target=1648, look_reached=False, note="H2 did not certify")
    order = {h.hid: i for i, h in enumerate(spec.FAMILY)}
    out = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "plan_sha256": stored["plan_sha256"],
           "evidence_grade": "DEVELOPMENT", "thresholds": thr,
           "coverage": {k: v.label_status.value_counts().to_dict() for k, v in lab.items() if len(v)},
           "control_coverage": control.label_status.value_counts().to_dict() if len(control) else {},
           "results": [results[k].as_dict() for k in sorted(results, key=order.get)]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULT, "x") as fh:  # write-once
        json.dump(out, fh, indent=1, default=float)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-plan", action="store_true", help="write plan.json (commit it before --run)")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args(argv)
    if a.write_plan:
        if PLAN.exists():
            print(f"refusing: {PLAN} exists", file=sys.stderr)
            return 2
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        body = plan()
        PLAN.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
        print(json.dumps({k: body[k] for k in ("threshold_block", "test_block", "plan_sha256")}, indent=1))
        return 0
    if a.run:
        out = run()
        print(json.dumps({"results": out["results"], "coverage": out["coverage"]}, indent=1, default=float))
        return 0
    ap.print_help()
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
