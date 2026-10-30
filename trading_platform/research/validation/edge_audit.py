"""Deterministic edge audit for fixed-payout binary contracts.

A binary contract paying ``payout`` on a win and losing the stake otherwise
breaks even at a win rate of ``1 / (1 + payout)``. This module measures simple
candle-direction rules and settled trade logs against that line, using a
Wilson interval so small samples cannot pass on luck.

A rule "clears" only when the lower bound of its 95% interval is above
breakeven. A point estimate above breakeven is not enough.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

Z_95 = 1.959963984540054


def breakeven_win_rate(payout: float) -> float:
    if payout <= 0:
        raise ValueError("payout must be positive")
    return 1.0 / (1.0 + payout)


def wilson_interval(wins: int, n: int, z: float = Z_95) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    if not 0 <= wins <= n:
        raise ValueError("wins must be between 0 and n")
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((centre - margin) / denom, (centre + margin) / denom)


@dataclass(frozen=True, slots=True)
class RuleResult:
    name: str
    trades: int
    wins: int
    win_rate: float
    ci_low: float
    ci_high: float
    breakeven: float
    clears_breakeven: bool


def _result(name: str, wins: int, n: int, breakeven: float) -> RuleResult:
    low, high = wilson_interval(wins, n)
    return RuleResult(
        name=name,
        trades=n,
        wins=wins,
        win_rate=wins / n if n else 0.0,
        ci_low=low,
        ci_high=high,
        breakeven=breakeven,
        clears_breakeven=n > 0 and low > breakeven,
    )


def direction_frame(candles: pd.DataFrame, timeframe_sec: int) -> pd.DataFrame:
    """Return per-candle signs with three lags and the next-candle outcome.

    Expects columns ``asset``, ``timestamp`` (UTC), ``open`` and ``close`` for
    one timeframe. Rows survive only when the three previous candles and the
    next candle are contiguous, so gaps never leak across sessions. Doji
    candles (open == close) are dropped as both signal and outcome.
    """
    frames = []
    for _, group in candles.sort_values("timestamp").groupby("asset", sort=False):
        ts = pd.to_datetime(group["timestamp"], utc=True)
        seconds = (ts - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy()
        sign = np.sign(group["close"].to_numpy() - group["open"].to_numpy())
        frame = pd.DataFrame({"s0": sign, "t": seconds})
        step_ok = np.diff(seconds, prepend=np.nan) == timeframe_sec
        frame["s1"] = frame["s0"].shift(1)
        frame["s2"] = frame["s0"].shift(2)
        frame["y"] = frame["s0"].shift(-1)
        contiguous = pd.Series(step_ok)
        frame["ok"] = (
            contiguous
            & contiguous.shift(1, fill_value=False)
            & contiguous.shift(-1, fill_value=False)
        ).to_numpy()
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["s0", "s1", "s2", "y", "t"])
    out = pd.concat(frames, ignore_index=True)
    out = out[out["ok"]].dropna(subset=["s1", "s2", "y"])
    out = out[(out["s0"] != 0) & (out["s1"] != 0) & (out["s2"] != 0) & (out["y"] != 0)]
    return out.drop(columns="ok").reset_index(drop=True)


# Each rule maps the frame to (mask of rows it trades, predicted sign per row).
Rule = Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]]

RULES: Mapping[str, Rule] = {
    "lag1_continuation": lambda d: (pd.Series(True, index=d.index), d["s0"]),
    "lag1_reversal": lambda d: (pd.Series(True, index=d.index), -d["s0"]),
    "streak3_continuation": lambda d: ((d["s0"] == d["s1"]) & (d["s1"] == d["s2"]), d["s0"]),
    "streak3_reversal": lambda d: ((d["s0"] == d["s1"]) & (d["s1"] == d["s2"]), -d["s0"]),
    "mhi_majority": lambda d: (pd.Series(True, index=d.index), np.sign(d["s0"] + d["s1"] + d["s2"])),
    "mhi_minority": lambda d: (pd.Series(True, index=d.index), -np.sign(d["s0"] + d["s1"] + d["s2"])),
}


def audit_candle_rules(frame: pd.DataFrame, payout: float) -> list[RuleResult]:
    breakeven = breakeven_win_rate(payout)
    results = []
    for name, rule in RULES.items():
        mask, predicted = rule(frame)
        traded = frame.loc[mask]
        wins = int((predicted.loc[mask] == traded["y"]).sum())
        results.append(_result(name, wins, len(traded), breakeven))
    return results


def audit_trade_log(rows: Iterable[Mapping[str, object]], default_payout: float) -> RuleResult:
    """Summarize settled trades. Ties and unsettled rows are excluded."""
    wins = losses = 0
    payouts = []
    for row in rows:
        result = row.get("result")
        if result == "win":
            wins += 1
        elif result in ("lose", "loose", "loss"):
            losses += 1
        else:
            continue
        payout = row.get("payout_rate")
        payouts.append(float(payout) if payout else default_payout)
    payout = sum(payouts) / len(payouts) if payouts else default_payout
    return _result("trade_log", wins, wins + losses, breakeven_win_rate(payout))


def render_markdown(title: str, results: Iterable[RuleResult]) -> str:
    rows = list(results)
    lines = [
        f"## {title}",
        "",
        "| rule | trades | win rate | 95% CI | breakeven | clears |",
        "|---|---:|---:|---|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.name} | {r.trades:,} | {r.win_rate:.4f} | "
            f"[{r.ci_low:.4f}, {r.ci_high:.4f}] | {r.breakeven:.4f} | "
            f"{'YES' if r.clears_breakeven else 'no'} |"
        )
    verdict = "EDGE FOUND" if any(r.clears_breakeven for r in rows) else "NO EDGE"
    lines += ["", f"Verdict: **{verdict}**", ""]
    return "\n".join(lines)


def render_json(results: Iterable[RuleResult]) -> str:
    return json.dumps([asdict(r) for r in results], indent=2)
