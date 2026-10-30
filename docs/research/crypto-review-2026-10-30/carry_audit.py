"""Audit the historical funding-only proxy; never a tradable portfolio backtest.

Usage: python3 carry_audit.py path/to/funding.json
All returns are arithmetic, not compounded. Zero-filled gaps reproduce the old
proxy but are separately flagged; they must not pass a production data gate.
"""
import collections
import datetime as dt
import hashlib
import json
import math
import pathlib
import sys

DAY_MS = 86_400_000
ROUND_TRIP = {"bybit": 0.0031, "hyperliquid": 0.0023}


def minimum_capital(spot_notional, short_leverage=1.0, reserve=0.0):
    """Segregated, fully funded spot and stablecoin collateral; no offsets."""
    if spot_notional < 0 or short_leverage <= 0 or reserve < 0:
        raise ValueError("invalid capital assumptions")
    return spot_notional + spot_notional / short_leverage + reserve


def required_annual_funding(round_trip, horizon_days=7, coverage=2):
    if horizon_days <= 0 or round_trip < 0 or coverage < 0:
        raise ValueError("invalid cost assumptions")
    return round_trip * coverage * 365 / horizon_days


def funding_proxy(daily, round_trip, hurdle=0.08):
    """Prior completed days only; exact rule used by the original script."""
    state = False
    output = []
    for i, value in enumerate(daily):
        want = state
        if not state and i >= 7 and sum(daily[i-7:i]) / 7 * 365 > hurdle:
            want = True
        if state and i >= 3 and sum(daily[i-3:i]) / 3 * 365 < 0:
            want = False
        cost = round_trip / 2 if state != want else 0.0
        output.append((value * want - cost, want, state != want))
        state = want
    return output


def audit(path):
    content = pathlib.Path(path).read_bytes()
    rows = json.loads(content)
    groups = collections.defaultdict(list)
    for venue, symbol, stamp, rate in rows:
        if not math.isfinite(rate):
            raise ValueError("nonfinite funding")
        groups[venue, symbol].append((stamp, rate))
    results = []
    for (venue, symbol), observations in sorted(groups.items()):
        unique = dict(observations)
        if any(unique[t] != r for t, r in observations):
            raise ValueError("conflicting duplicate funding observations")
        stamps = sorted(unique)
        start, end = stamps[0] // DAY_MS, stamps[-1] // DAY_MS
        totals = collections.defaultdict(float)
        counts = collections.Counter()
        for stamp, rate in unique.items():
            day = stamp // DAY_MS
            totals[day] += rate
            counts[day] += 1
        days = list(range(start, end + 1))
        proxy = funding_proxy([totals[d] for d in days], ROUND_TRIP[venue])
        by_year = collections.defaultdict(list)
        for day, point in zip(days, proxy):
            year = dt.datetime.fromtimestamp(day * 86400, dt.timezone.utc).year
            by_year[year].append(point)
        years = []
        for year, points in sorted(by_year.items()):
            annual = sum(x[0] for x in points) * 365 / len(points)
            years.append({"year": year, "days": len(points),
                          "annualized_notional_proxy": annual,
                          "annualized_2x_capital_proxy": annual / 2,
                          "period_notional_proxy": sum(x[0] for x in points),
                          "transitions": sum(x[2] for x in points)})
        results.append({"venue": venue, "symbol": symbol, "observations": len(observations),
                        "duplicates": len(observations) - len(unique),
                        "first_utc": dt.datetime.fromtimestamp(stamps[0]/1000, dt.timezone.utc).isoformat(),
                        "last_utc": dt.datetime.fromtimestamp(stamps[-1]/1000, dt.timezone.utc).isoformat(),
                        "whole_missing_days": sum(counts[d] == 0 for d in days),
                        "daily_print_count_distribution": dict(sorted(collections.Counter(counts[d] for d in days).items())),
                        "max_gap_hours": max((b-a)/3600000 for a,b in zip(stamps, stamps[1:])),
                        "final_position_open": proxy[-1][1],
                        "unbooked_terminal_exit_per_notional": ROUND_TRIP[venue]/2 if proxy[-1][1] else 0,
                        "minimum_ann_for_2x_7d_cost_cover": required_annual_funding(ROUND_TRIP[venue]),
                        "years": years})
    return {"raw_sha256": hashlib.sha256(content).hexdigest(), "row_count": len(rows),
            "interpretation": "Funding-only diagnostic, not investable returns. Capital scenario assumes 2N, no reserves or idle yield.",
            "series": results}


if __name__ == "__main__":
    print(json.dumps(audit(sys.argv[1]), indent=2))
