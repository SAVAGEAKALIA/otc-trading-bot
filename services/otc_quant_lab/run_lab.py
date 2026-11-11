"""Run the full lab study. Read-only over the candle archive; writes only under --out.

    .venv-lab/bin/python -m services.otc_quant_lab.run_lab --out /tmp/otc-quant-lab/runs/main-120 \
        --tf 120 --horizons 1,2,5 --models all
    tail -f /tmp/otc-quant-lab/runs/main-120/progress.log
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import bandit, baselines, data, features, martingale, metrics, online, regimes, risk
from .features import DOWN, FEATURES, FEATURES_V2, UP
from .metrics import PRIMARY_PAYOUT, trade_summary
from .walkforward import COVERAGES, block_matrix, in_days, lab_splits, pbo_cscv, platt, selection_score, \
    thresholds, trades

ENSEMBLE_MEMBERS = ("logistic", "lightgbm", "catboost", "mlp", "deep_gru")


class Progress:
    def __init__(self, out: Path, total: int, title: str):
        self.path, self.total, self.title, self.done = out / "progress.log", total, title, 0
        self.started = time.monotonic()

    def step(self, what: str, n: int = 1):
        self.done += n
        elapsed = time.monotonic() - self.started
        eta = elapsed * (self.total - self.done) / self.done if self.done else None
        row = {"event": self.title, "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "percent": round(100 * self.done / self.total, 1), "eta_min": round(eta / 60, 1) if eta else None,
               "done": self.done, "total": self.total, "step": what}
        line = json.dumps(row)
        with self.path.open("a") as f:
            f.write(line + "\n")
        print(line, flush=True)


def model_factories(selection: str) -> dict:
    from .models import tabular_zoo

    zoo = {**tabular_zoo(), **regimes.regime_zoo()}
    if selection in ("all", "deep") or "deep_" in selection:
        from .seqmodels import seq_zoo

        zoo.update(seq_zoo())
    if selection == "deep":
        zoo = {k: v for k, v in zoo.items() if k.startswith("deep_")}
    elif selection not in ("all", "tabular"):
        zoo = {k: zoo[k] for k in selection.split(",")}
    return zoo


def binary_target(frame: pd.DataFrame, rows: np.ndarray, h: int):
    y = frame[f"y{h}"].to_numpy()[rows]
    keep = (y == UP) | (y == DOWN)
    return rows[keep], (y[keep] == UP).astype(np.int8)


def model_input(name: str, frame: pd.DataFrame, x_all: np.ndarray, rows: np.ndarray):
    if name.startswith("deep_"):
        return (features.sequences(frame, rows), x_all[rows])
    return x_all[rows]


def score_rows(frame, rows, h, p, base_rate: float) -> dict:
    """Test-window scores. base_rate comes from TRAIN labels (no oracle test up-rate).

    C1: log-loss improvement per row and per-day AUC, each with a 95% day-block bootstrap CI.
    """
    y = frame[f"y{h}"].to_numpy()[rows]
    keep = (y == UP) | (y == DOWN)
    yb, pb = (y[keep] == UP).astype(np.int8), p[keep]
    days = frame.day.to_numpy()[rows][keep]
    pc, bc = np.clip(pb, 1e-6, 1 - 1e-6), np.clip(base_rate, 1e-6, 1 - 1e-6)
    ll_model = -(yb * np.log(pc) + (1 - yb) * np.log(1 - pc))
    ll_base = -(yb * np.log(bc) + (1 - yb) * np.log(1 - bc))
    gain = ll_base - ll_model
    day_ids = np.unique(days)
    day_auc = np.array([metrics.auc(yb[days == d], pb[days == d]) for d in day_ids])
    ok = np.isfinite(day_auc)
    return {"n": int(keep.sum()), "auc": metrics.auc(yb, pb), "log_loss": float(ll_model.mean()),
            "base_log_loss": float(ll_base.mean()), "ll_gain": float(gain.mean()),
            "ll_gain_ci95": list(metrics.day_block_bootstrap(gain, days, reps=500)),
            "day_auc_mean": float(day_auc[ok].mean()) if ok.any() else None,
            "day_auc_ci95": list(metrics.day_block_bootstrap(day_auc[ok], day_ids[ok], reps=500)) if ok.any() else None,
            "brier": metrics.brier(yb, pb), "calibration_slope": metrics.calibration_slope(yb, pb)}


def hmm_predictions(frame, split, h, test_rows, inner_rows, train_rows):
    """3-state HMM, forward-filtered state x 3-bar pattern -> state table."""
    reset = (frame.pos.to_numpy() == 0) | (frame.asset_id.diff().fillna(1).to_numpy() != 0)
    fit_mask = np.zeros(len(frame), dtype=bool)
    fit_mask[train_rows] = True
    # fit on the most recent train rows of EVERY asset (rows are asset-sorted; a global tail = last assets)
    asset = frame.asset_id.to_numpy()
    per_asset = 200_000 // max(len(np.unique(asset)), 1)
    from_end = pd.Series(fit_mask[::-1].astype(int)).groupby(asset[::-1]).cumsum().to_numpy()[::-1]
    fit_mask &= from_end <= per_asset
    state = regimes.hmm_states(frame.z0.to_numpy(), frame.rng0.to_numpy(), reset, fit_mask)
    pat = np.nan_to_num(frame.pat3.to_numpy(), nan=-1).astype(int)
    combo = np.where(pat >= 0, state * 27 + pat, -1)
    tr, y = binary_target(frame, train_rows, h)
    n = np.bincount(combo[tr][combo[tr] >= 0], minlength=81)
    k = np.bincount(combo[tr][combo[tr] >= 0], weights=y[combo[tr] >= 0], minlength=81)
    table = (k + regimes.PRIOR) / (n + 2 * regimes.PRIOR)
    lookup = lambda r: np.where(combo[r] >= 0, table[np.clip(combo[r], 0, None)], 0.5)
    return lookup(inner_rows), lookup(test_rows)


def run(args, bars: pd.DataFrame | None = None) -> dict:
    """Full study. `bars` overrides the archive (used by the synthetic control evals)."""
    out = Path(args.out)
    resume = getattr(args, "resume", False)
    out.mkdir(parents=True, exist_ok=resume)
    cache = out / "cache"  # one file per (model, horizon, split): a killed run resumes where it stopped
    cache.mkdir(exist_ok=True)
    for stale in ("progress.log", "trials.jsonl"):
        (out / stale).unlink(missing_ok=True)
    tf, horizons = args.tf, tuple(int(h) for h in args.horizons.split(","))
    synthetic = bars is not None
    remote = bool(getattr(args, "bars_parquet", ""))
    source_hash = "synthetic" if synthetic else data.sha256_file(Path(args.bars_parquet) if remote else data.HISTORICAL_DB)
    if not synthetic:
        bars = pd.read_parquet(args.bars_parquet) if getattr(args, "bars_parquet", "") else data.load_historical(tf)
    keep_assets = args.assets.split(",") if getattr(args, "assets", None) else None
    if keep_assets:
        bars = bars[bars.asset.isin(keep_assets)]
    # Keep every bar: sequence windows gather the 31 previous rows, which must be the same asset's
    # contiguous history. Only rows with valid=True (pos >= LOOKBACK) are ever scored or trained on.
    frame = features.build(bars, tf, horizons)
    valid = frame.valid.to_numpy()
    feats = FEATURES_V2 if getattr(args, "feature_set", "v1") == "v2" else FEATURES
    x_all = frame[feats].to_numpy(np.float32)
    order = np.lexsort((frame.asset_id.to_numpy(), frame.t.to_numpy()))
    chrono = order[valid[order]]  # valid rows in time order
    folds, final = lab_splits(frame.day.to_numpy()[valid])
    splits = folds + [final]
    realtime = None
    if args.realtime:
        rt_bars = pd.read_parquet(args.realtime_parquet) if getattr(args, "realtime_parquet", "") \
            else data.load_realtime(tf)
        if keep_assets:
            rt_bars = rt_bars[rt_bars.asset.isin(keep_assets)]
        realtime = features.build(rt_bars, tf, horizons)
        rt_x = realtime[feats].to_numpy(np.float32)
        rt_order = np.lexsort((realtime.asset_id.to_numpy(), realtime.t.to_numpy()))
        rt_rows = rt_order[realtime.valid.to_numpy()[rt_order]]
    zoo = model_factories(args.models)
    meta = {"source": str(data.HISTORICAL_DB), "source_sha256": source_hash, "tf": tf, "horizons": horizons,
            "rows": int(valid.sum()), "bars": int(len(frame)), "assets": sorted(frame.asset.unique().tolist()),
            "first_day": str(pd.to_datetime(int(frame.day.min()) * 86400, unit="s").date()),
            "last_day": str(pd.to_datetime(int(frame.day.max()) * 86400, unit="s").date()),
            "splits": [{"name": s.name, "train": s.train, "inner": s.inner, "test": s.test} for s in splits],
            "models": list(zoo) + ["hmm3_pat3", "ensemble_mean"], "coverages": COVERAGES,
            "primary_payout": PRIMARY_PAYOUT, "realtime_rows": int(len(realtime)) if realtime is not None else 0}
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    progress = Progress(out, total=len(horizons) * len(splits) * (len(zoo) + 1) + 4, title=f"OTC lab tf={tf}")

    day = frame.day.to_numpy()
    dev_rows = chrono[day[chrono] < final.test[0] - 1]
    final_test_rows = chrono[in_days(day[chrono], final.test)]
    final_rows = chrono[in_days(day[chrono], final.test)]

    # 1. model-free tests (development rows only; final rows reported separately as confirmation)
    tests = {}
    for label, rows in (("dev", dev_rows), ("final", final_rows)):
        p3 = martingale.pattern_table(frame, rows, "pat3")
        p5 = martingale.pattern_table(frame, rows, "pat5")
        frame["hour_int"] = frame.hour.astype(int)
        hours = martingale.pattern_table(frame, rows, "hour_int")
        tests[label] = {
            "up_rate": martingale.up_rate_test(binary_target(frame, rows, 1)[1]),
            "tie_rate": {h: martingale.tie_rate(frame, rows, h) for h in horizons},
            "sign_autocorr": martingale.sign_autocorrelation(frame, rows),
            "variance_ratio": martingale.variance_ratio(frame, rows),
            "pattern3": {"chi2": martingale.chi_square_independence(p3), "top": p3.head(8).to_dict("records"),
                         "min_q": float(p3.q.min()) if len(p3) else None},
            "pattern5": {"chi2": martingale.chi_square_independence(p5), "top": p5.head(8).to_dict("records"),
                         "min_q": float(p5.q.min()) if len(p5) else None, "states": int(len(p5))},
            "hour": {"chi2": martingale.chi_square_independence(hours), "table": hours.to_dict("records")},
            "markov_orders_1_5": martingale.markov_orders(frame, rows),
            "feature_corr": martingale.feature_direction_corr(frame, rows, feats).head(15).to_dict("records"),
            "lead_lag_top": martingale.lead_lag(frame, rows).head(10).to_dict("records"),
        }
    tests["restart_window_all_days"] = martingale.restart_window(frame)
    (out / "martingale.json").write_text(json.dumps(tests, indent=2, default=float))
    progress.step("martingale tests", 4)

    registry = (out / "trials.jsonl").open("a")
    dev_trades: dict[str, list] = {}
    final_trades: dict[str, pd.DataFrame] = {}
    rt_trades: dict[str, pd.DataFrame] = {}
    scores: list[dict] = []
    preds: dict[tuple, np.ndarray] = {}
    preds_inner: dict[tuple, np.ndarray] = {}

    def record(model, h, split, inner_rows, p_inner, test_rows, p_test, base_rate, rt_p=None):
        y_inner = frame[f"y{h}"].to_numpy()[inner_rows]
        known = (y_inner == UP) | (y_inner == DOWN)
        calib = platt(p_inner[known], (y_inner[known] == UP).astype(np.int8))
        pi, pt = calib(p_inner), calib(p_test)
        preds[(model, h, split.name)] = pt
        preds_inner[(model, h, split.name)] = pi
        s = score_rows(frame, test_rows, h, pt, base_rate)
        s.update({"model": model, "h": h, "split": split.name})
        scores.append(s)
        for q, thr in thresholds(pi).items():
            name = f"{model}|h{h}|cov{q}"
            tr = trades(frame, test_rows, pt, thr, h, tf)
            registry.write(json.dumps({"config": name, "split": split.name, "trades": len(tr),
                                       "wins": int((tr.outcome == 1).sum()),
                                       "losses": int((tr.outcome == 0).sum())}) + "\n")
            if split.name == "final":
                final_trades[name] = tr
                if rt_p is not None:
                    rt_trades[name] = trades(realtime, rt_rows, calib(rt_p), thr, h, tf)
            else:
                dev_trades.setdefault(name, []).append(tr)

    fit_only = [int(h) for h in args.fit_only.split(",")] if getattr(args, "fit_only", "") else None
    for h in horizons:
        if fit_only is not None and h not in fit_only:
            continue
        for split in splits:
            train_rows = chrono[in_days(day[chrono], split.train)]
            inner_rows = chrono[in_days(day[chrono], split.inner)]
            test_rows = chrono[in_days(day[chrono], split.test)]
            tr_rows, y = binary_target(frame, train_rows, h)
            for name, make in zoo.items():
                t0 = time.monotonic()
                saved = cache / f"{name}_h{h}_{split.name}.npz"
                if saved.exists():
                    z = np.load(saved)
                    p_inner, p_test = z["p_inner"], z["p_test"]
                    rt_p = z["rt_p"] if z["rt_p"].size else None
                else:
                    model = make().fit(model_input(name, frame, x_all, tr_rows), y)
                    p_inner = model.predict(model_input(name, frame, x_all, inner_rows))
                    p_test = model.predict(model_input(name, frame, x_all, test_rows))
                    rt_p = None
                    if split.name == "final" and realtime is not None:
                        rt_in = (features.sequences(realtime, rt_rows), rt_x[rt_rows]) if name.startswith("deep_") \
                            else rt_x[rt_rows]
                        rt_p = model.predict(rt_in)
                    np.savez(saved, p_inner=p_inner, p_test=p_test,
                             rt_p=rt_p if rt_p is not None else np.array([]))
                record(name, h, split, inner_rows, p_inner, test_rows, p_test, float(y.mean()), rt_p)
                progress.step(f"{name} h{h} {split.name} {time.monotonic() - t0:.0f}s")
            p_inner, p_test = hmm_predictions(frame, split, h, test_rows, inner_rows, train_rows)
            record("hmm3_pat3", h, split, inner_rows, p_inner, test_rows, p_test, float(y.mean()))
            progress.step(f"hmm3_pat3 h{h} {split.name}")
    registry.close()
    if fit_only is not None:  # remote shard: cached fits are the deliverable; aggregation runs locally
        progress.step("fit-only shard complete", 0)
        return {}

    # ensemble = mean of calibrated member predictions (no extra fitting) on the test rows
    for h in horizons:
        members = [m for m in ENSEMBLE_MEMBERS if (m, h, "final") in preds]
        if len(members) < 2:
            continue
        for split in splits:
            test_rows = chrono[in_days(day[chrono], split.test)]
            p = np.mean([preds[(m, h, split.name)] for m in members], axis=0)
            p_inner = np.mean([preds_inner[(m, h, split.name)] for m in members], axis=0)
            preds[("ensemble_mean", h, split.name)] = p
            train_y = binary_target(frame, chrono[in_days(day[chrono], split.train)], h)[1]
            s = score_rows(frame, test_rows, h, p, float(train_y.mean()))
            s.update({"model": "ensemble_mean", "h": h, "split": split.name})
            scores.append(s)
            for q, thr in thresholds(p_inner).items():  # thresholds from inner days only
                tr = trades(frame, test_rows, p, thr, h, tf)
                name = f"ensemble_mean|h{h}|cov{q}"
                (final_trades.__setitem__(name, tr) if split.name == "final"
                 else dev_trades.setdefault(name, []).append(tr))

    # baselines: no fitting, so every period is out of sample; same selection rule
    suite = baselines.baseline_suite(frame, tf)
    rt_suite = baselines.baseline_suite(realtime, tf) if realtime is not None else None
    for name, p_all in suite.items():
        for h in horizons:
            cfg = f"rule:{name}|h{h}|cov1.0"
            for split in splits:
                test_rows = chrono[in_days(day[chrono], split.test)]
                tr = trades(frame, test_rows, p_all[test_rows], 0.51, h, tf)
                (final_trades.__setitem__(cfg, tr) if split.name == "final"
                 else dev_trades.setdefault(cfg, []).append(tr))
            if realtime is not None:
                rt_trades[cfg] = trades(realtime, rt_rows, rt_suite[name][rt_rows], 0.51, h, tf)

    # RL as contextual bandit over kmeans16 x session contexts, all horizons as arms
    rl = {}
    for split in splits:
        train_rows = chrono[in_days(day[chrono], split.train)]
        test_rows = chrono[in_days(day[chrono], split.test)]
        clusters = regimes.Clusters("kmeans", 16)
        clusters.fit_states(x_all[train_rows])
        session = (frame.hour.to_numpy() // 6).astype(int)
        ctx = lambda r: clusters._assign(clusters, x_all[r]) * 4 + session[r]
        rew = bandit.arm_rewards(frame, train_rows, horizons)
        for mode in ("greedy", "lcb"):
            choice = bandit.learn(ctx(train_rows), rew, 64, mode)
            tr = bandit.act(frame, test_rows, ctx(test_rows), choice, horizons, tf)
            cfg = f"bandit_{mode}|hmix|cov1.0"
            rl.setdefault(cfg, {})[split.name] = int((choice >= 0).sum())
            (final_trades.__setitem__(cfg, tr) if split.name == "final"
             else dev_trades.setdefault(cfg, []).append(tr))

    # online prequential SGD with Page-Hinkley suspension (h = first horizon)
    h0 = horizons[0]
    start_day = folds[0].test[0]
    order = chrono
    y_online = frame[f"y{h0}"].to_numpy()[order].astype(np.int64)
    y_online = np.where(y_online == UP, 1, np.where(y_online == DOWN, 0, -1))
    p_online = online.prequential_sgd(x_all[order], y_online, day[order], start_day)
    p_full = np.full(len(frame), 0.5)
    p_full[order] = np.nan_to_num(p_online, nan=0.5)
    for split in splits:
        test_rows = chrono[in_days(day[chrono], split.test)]
        for q in (1.0, 0.1):
            # per-day threshold from the previous 7 days of online predictions only (no test-window quantile)
            thr_rows = online.causal_thresholds(p_full[chrono], day[chrono], q)
            thr_map = np.full(len(frame), np.inf)
            thr_map[chrono] = thr_rows
            conf = np.maximum(p_full[test_rows], 1 - p_full[test_rows])
            eligible = test_rows[conf >= thr_map[test_rows]]
            tr = trades(frame, eligible, p_full[eligible], 0.0, h0, tf)
            for cfg, t in ((f"online_sgd|h{h0}|cov{q}", tr),
                           (f"online_sgd_ph|h{h0}|cov{q}", online.suspend_with_page_hinkley(tr))):
                (final_trades.__setitem__(cfg, t) if split.name == "final"
                 else dev_trades.setdefault(cfg, []).append(t))

    dev = {k: pd.concat(v, ignore_index=True).sort_values("t").reset_index(drop=True) for k, v in dev_trades.items()}
    # H6: every trial of every kind (zoo, ensemble, rules, bandit, online, adaptive) per split
    with (out / "trials_complete.jsonl").open("w") as reg:
        fold_names = [s.name for s in folds]
        for cfg, parts in sorted(dev_trades.items()):
            for name, tr in zip(fold_names, parts):
                reg.write(json.dumps({"config": cfg, "split": name, "trades": int(len(tr)),
                                      "wins": int((tr.outcome == 1).sum()), "losses": int((tr.outcome == 0).sum())}) + "\n")
        for cfg, tr in sorted(final_trades.items()):
            reg.write(json.dumps({"config": cfg, "split": "final", "trades": int(len(tr)),
                                  "wins": int((tr.outcome == 1).sum()) if len(tr) else 0,
                                  "losses": int((tr.outcome == 0).sum()) if len(tr) else 0}) + "\n")
    K = len(dev)

    # adaptive engine: daily switching among all dev-registered configs, scored on final days
    final_days = np.unique(day[final_rows])
    adaptive, adaptive_log = online.adaptive_selection(final_trades, final_days)
    final_trades["adaptive_switch|hmix|covmix"] = adaptive
    with (out / "trials_complete.jsonl").open("a") as reg:  # post hoc, final-only; registered, not selectable
        reg.write(json.dumps({"config": "adaptive_switch|hmix|covmix", "split": "final", "trades": int(len(adaptive)),
                              "wins": int((adaptive.outcome == 1).sum()) if len(adaptive) else 0,
                              "losses": int((adaptive.outcome == 0).sum()) if len(adaptive) else 0}) + "\n")

    # 2. selection on development only
    dev_table = []
    for cfg, tr in dev.items():
        out_c = tr.outcome.to_numpy()
        dev_table.append({"config": cfg, "score": selection_score(out_c), **trade_summary(out_c, tr.day.to_numpy(),
                                                                                         trials=K)})
    dev_table = sorted(dev_table, key=lambda r: -r["score"] if np.isfinite(r["score"]) else np.inf)
    winner = dev_table[0]["config"] if np.isfinite(dev_table[0]["score"]) else None

    dev_days = np.unique(np.concatenate([tr.day.to_numpy() for tr in dev.values() if len(tr)]))
    edges = np.linspace(dev_days.min(), dev_days.max() + 1, 17)
    eligible = {k: v for k, v in dev.items() if len(v) >= 500}
    matrix, names = block_matrix(eligible, edges)
    pbo = pbo_cscv(matrix)  # across every eligible config
    family = winner.split("|")[0] if winner else None
    fam = {k: v for k, v in eligible.items() if family and k.split("|")[0] == family}
    pbo_family = pbo_cscv(block_matrix(fam, edges)[0]) if len(fam) >= 2 else None

    # 3. final evaluation: the winner once, then everything descriptively (post hoc, flagged)
    final_table = []
    for cfg, tr in final_trades.items():
        out_c = tr.outcome.to_numpy() if len(tr) else np.array([], dtype=np.int8)
        days_c = tr.day.to_numpy() if len(tr) else np.array([])
        row = {"config": cfg, **trade_summary(out_c, days_c, trials=K)}
        if len(tr):
            per_asset = tr.assign(r=metrics.unit_returns(out_c, PRIMARY_PAYOUT)).groupby("asset").r.agg(["mean", "count"])
            big = per_asset[per_asset["count"] >= 50]
            row["assets_positive_share"] = float((big["mean"] > 0).mean()) if len(big) else None
            sess = tr.assign(w=(out_c == 1), d=(out_c >= 0), s=(tr.hour // 6).astype(int)).groupby("s")
            row["win_rate_by_session"] = {int(s): float(g.w.sum() / max(g.d.sum(), 1)) for s, g in sess}
        final_table.append(row)
    final_table.sort(key=lambda r: -(r["win_rate"] or 0))
    rt_table = []
    for cfg, tr in rt_trades.items():
        out_c = tr.outcome.to_numpy()
        rt_table.append({"config": cfg, **trade_summary(out_c, tr.day.to_numpy(), trials=K)})
    rt_table.sort(key=lambda r: -(r["win_rate"] or 0))

    position = np.full(len(frame), -1)
    position[final_test_rows] = np.arange(len(final_test_rows))

    def traded_calibration(config: str) -> dict | None:
        """P7 on the traded bucket. Rules, bandit and online policies emit no probability: None (fails P7)."""
        model, h = config.split("|")[0], config.split("|")[1]
        key = (model, int(h[1:]) if h[1:].isdigit() else -1, "final")
        tr = final_trades.get(config)
        if key not in preds or tr is None or not len(tr):
            return None
        p = preds[key][position[tr.row.to_numpy()]]
        return metrics.traded_calibration(p, tr.up.to_numpy(), tr.outcome.to_numpy())

    def one_bin_reliability(config: str) -> bool:
        """P7 for forecasters with one forecast value (rules, bandit arms, online cut-offs): the
        reliability diagram has a single bin, so its forecast (the dev win rate) must lie inside the
        Wilson 95% interval of the final traded win rate. Interpretation fixed before main results."""
        dev_row = next((r for r in dev_table if r["config"] == config), None)
        fin_row = next((r for r in final_table if r["config"] == config), None)
        if not (dev_row and fin_row and dev_row["win_rate"] is not None and fin_row["win_rate"] is not None):
            return False
        lo, hi = fin_row["wilson95"]
        return bool(lo <= dev_row["win_rate"] <= hi)

    def calibrated(config: str) -> bool:
        c = traded_calibration(config)
        if c is None:
            return one_bin_reliability(config)
        return bool(c["brier"] is not None and c["brier"] <= 0.25 and c["slope"] == c["slope"]
                    and 0.5 <= c["slope"] <= 1.5)

    def rubric(row):
        if row is None:
            return {"pass": False}
        checks = {
            "P1_trades_days": row["trades"] >= 1000 and row["days"] >= 15,
            "P2_bonferroni_wilson": (row["wilson_lower_bonferroni"] or 0) > row["breakeven_primary"],
            "P3_mean_and_bootstrap": (row["mean_return"]["0.84"] or -1) > 0 and row["mean_return_day_bootstrap95"][0] > 0,
            "P4_thirds": all((m or -1) > 0 for m in row["thirds_mean_return"]),
            "P5_assets": (row.get("assets_positive_share") or 0) >= 0.6,
            "P6_pbo": (pbo_family or pbo)["pbo"] < 0.25,
            "P7_calibration": calibrated(row["config"]),
        }
        checks = {k: bool(v) for k, v in checks.items()}
        return {**checks, "pass": all(checks.values())}

    winner_final = next((r for r in final_table if r["config"] == winner), None)
    model_scores = pd.DataFrame(scores)
    summary = {
        "meta": meta, "trials_K": K, "winner_selected_on_dev": winner,
        "winner_dev": next((r for r in dev_table if r["config"] == winner), None),
        "winner_final": winner_final, "winner_rubric": rubric(winner_final), "pbo": pbo,
        "pbo_winner_family": pbo_family,
        "winner_traded_calibration": traded_calibration(winner) if winner else None,
        "dev_top10": dev_table[:10], "final_top15_post_hoc": final_table[:15],
        "realtime_top10_post_hoc": rt_table[:10], "bandit_contexts_chosen": rl,
        "adaptive_log": adaptive_log,
        "model_scores_test_mean": model_scores.groupby(["model", "h"])[["auc", "log_loss", "base_log_loss", "brier",
                                                                        "calibration_slope"]].mean()
        .reset_index().to_dict("records"),
        "model_scores_final": [r for r in scores if r["split"] == "final"],
        "risk": {
            "kelly_at_winner_final": risk.kelly_fraction(winner_final["win_rate"]) if winner_final and winner_final[
                "win_rate"] else None,
            "trades_needed_for_2pt_edge": risk.trades_needed(0.02, metrics.breakeven(PRIMARY_PAYOUT)),
            "trades_needed_for_1pt_edge": risk.trades_needed(0.01, metrics.breakeven(PRIMARY_PAYOUT)),
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    model_scores.to_csv(out / "model_scores.csv", index=False)
    pd.DataFrame(dev_table).drop(columns=["wilson95", "mean_return", "mean_return_day_bootstrap95",
                                          "thirds_mean_return"]).to_csv(out / "dev_table.csv", index=False)
    pd.DataFrame(final_table).drop(columns=["wilson95", "mean_return", "mean_return_day_bootstrap95",
                                            "thirds_mean_return"], errors="ignore").to_csv(out / "final_table.csv",
                                                                                           index=False)
    if winner and winner in final_trades:
        final_trades[winner].to_csv(out / "winner_final_trades.csv", index=False)
    if not synthetic and not remote and data.sha256_file(data.HISTORICAL_DB) != source_hash:
        raise RuntimeError("source changed during run")
    progress.step("complete", 0)
    print(json.dumps({"winner": winner, "K": K, "pbo": pbo["pbo"], "winner_final": winner_final,
                      "rubric": summary["winner_rubric"]}, default=float, indent=1))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--tf", type=int, default=120)
    parser.add_argument("--horizons", default="1,2,5")
    parser.add_argument("--models", default="all")
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--assets", default="", help="comma list; default all")
    parser.add_argument("--resume", action="store_true", help="reuse cached fits in --out")
    parser.add_argument("--feature-set", default="v1", choices=["v1", "v2"], help="v2 adds asset id and clock features")
    parser.add_argument("--fit-only", default="", help="comma horizons: fit and cache only these, skip aggregation")
    parser.add_argument("--bars-parquet", default="", help="archive bars exported to parquet (remote runs)")
    parser.add_argument("--realtime-parquet", default="", help="realtime bars exported to parquet (remote runs)")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
