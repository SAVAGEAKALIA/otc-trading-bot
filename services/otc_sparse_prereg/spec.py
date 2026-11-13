"""The frozen family. Every number here is copied from the 2026-11-12 report (section 5).

Changing anything in this file after registration changes its hash, and `evaluate` refuses to run
against a registration whose recorded source hashes differ (see freeze.verify).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

FAMILY_ALPHA = 0.05
K = 8
ALPHA = FAMILY_ALPHA / K  # 0.00625, one-sided, per hypothesis
PLANNING_EDGE = 0.05
DESIGN_EFFECT = 1.5

TURBO_PAYOUT_NOMINAL = 0.84
BINARY_PAYOUT_NOMINAL = 0.86
TIE_RATE_2MIN = 0.0061  # owner's lab report; used only for the documented tie-as-loss sensitivity

# Forward block. Starts after the server's 2026-11-07 cohort ends (2026-11-14T10:08Z) so two
# collectors never share the account. All times UTC, milliseconds.
FORWARD_START_UTC = "2026-11-14T12:00:00Z"
FORWARD_START_MS = int(datetime.fromisoformat(FORWARD_START_UTC.replace("Z", "+00:00")).timestamp() * 1000)
DAY_MS = 86_400_000

# Archive used ONLY to freeze thresholds (never to certify). freeze.py records its hash and range.
ARCHIVE_TIMEFRAME_S = 120

# Data conventions.
ENTRY_DELAY_MS = 2_000          # enter at decision + 2 s
MAX_PAYOUT_AGE_MS = 120_000     # payout sample must be at most 2 min old at entry (30 s sampling)
MAX_MOOD_AGE_MS = 60_000
PAYOUT_MERGE_MS = 300_000       # payout steps on one asset within 300 s are one event
PAYOUT_SAMPLE_MS = 30_000       # forward payout sampling interval (registered harvester flag)
PAYOUT_SOURCE = "init-snapshot" # commission-stream rows replay days-old values at reconnect
PAYOUT_PRODUCTS = ("turbo-option", "binary-option")
STALL_GAP_MS = 60_000
CONTROL_EXCLUSION_MS = 900_000  # mood-only control excludes +-15 min around any payout step


@dataclass(frozen=True)
class Hypothesis:
    hid: str
    rank: int
    name: str
    product: str            # "turbo" or "binary" (payout used for break-even)
    expiry_s: int
    trigger: str            # exact text, mirrored by triggers.py
    side: str
    max_days: int           # certification look at n_target or this many forward days, whichever first
    in_family: bool = True
    tradable: bool = True
    nested_in: str | None = None  # fixed-sequence: opened only if this hypothesis certifies


FAMILY: tuple[Hypothesis, ...] = (
    Hypothesis("H2", 1, "Extreme 2-min move fade", "turbo", 120,
               "abs(z0) >= per-asset 99.5% quantile of abs(z0) frozen on the archive", "reverse the move", 60),
    Hypothesis("H2b", 1, "Strict extreme 2-min move fade", "turbo", 120,
               "abs(z0) >= per-asset 99.9% quantile of abs(z0) frozen on the archive", "reverse the move", 60,
               in_family=False, nested_in="H2"),
    Hypothesis("H3", 2, "Anchor-gap reversion", "binary", 600,
               "abs(gap) > 2.5 on the first bar of the excursion, gap = (log c - mean log c over last 720 bars)"
               " / (vol60 * sqrt(720))", "toward the 1-day mean", 60),
    Hypothesis("H4", 3, "Round-number first-touch fade", "binary", 600,
               "close within 0.01% of the nearest 0.0050 lattice level (0.50 JPY); max distance from that level"
               " over the prior 5 bars >= 8 pips; no touch in the prior 30 bars; must beat 99th pct of"
               " 1,000 placebo lattices", "against the approach", 60),
    Hypothesis("H5", 4, "Breadth-extreme fade", "turbo", 120,
               "abs(mkt0) >= pooled 99.0% quantile frozen on the archive; one trade per timestamp, on the"
               " same-sign asset with the largest abs(z0)", "against the sign of mkt0", 60),
    Hypothesis("H1", 5, "Payout step-down crowd fade", "turbo", 300,
               "payout (turbo or binary) falls >= 0.03 vs that product's previous sample; steps within 300 s"
               " merged; nearest prior turbo mood within 60 s has 0.05 < call fraction < 0.95, != 0.5;"
               " must also beat the matched mood-only control", "against the mood majority", 210),
    Hypothesis("H6", 6, "Payout step-up mirror", "turbo", 300,
               "payout (turbo or binary) rises >= 0.03, merged as H1; nearest prior turbo mood within 60 s"
               " != 0.5", "with the mood majority", 100),
    Hypothesis("H7", 7, "Quote-stall resume fade", "turbo", 120,
               "gap >= 60 s between consecutive received quotes on the asset; decision at the first quote"
               " after the gap", "against the jump across the gap", 60, tradable=False),
    Hypothesis("H8", 8, "15-min breakout continuation", "binary", 900,
               "5-min bars: (close - 20-bar low) / (20-bar high - 20-bar low) >= 0.999 (call) or <= 0.001"
               " (put)", "with the break", 60),
)
IN_FAMILY = tuple(h for h in FAMILY if h.in_family)
assert len(IN_FAMILY) == K, "family size is frozen at 8"
BY_ID = {h.hid: h for h in FAMILY}

GATES = {
    "G1": "weekday-path replay: one cross-day path-correlation statistic per asset at lags 1 and 5 days vs"
          " day-shuffled and circularly shifted surrogates, Holm over 15 assets; a pass only unlocks a"
          " separately registered family",
    "G2": "planted-edge power check: evals/eval_power.py must recover a +5 pt edge at the registered n with"
          " power >= 0.80 and certify a true null at most at rate ALPHA",
    "G3": "known-null pipeline control: the full trigger-label-certificate pipeline on a memoryless random"
          " walk must certify nothing (evals/eval_power.py); Deriv volatility ticks to be added as G3b",
}
OUTCOME_STATES = ("CERTIFIED", "NULL-INFORMATIVE", "UNDERPOWERED", "FUTILE")


def breakeven(payout: float) -> float:
    return 1.0 / (1.0 + payout)


def as_dict() -> dict:
    return {
        "family_alpha": FAMILY_ALPHA, "k": K, "alpha": ALPHA, "planning_edge": PLANNING_EDGE,
        "design_effect": DESIGN_EFFECT, "forward_start_utc": FORWARD_START_UTC,
        "forward_start_ms": FORWARD_START_MS, "archive_timeframe_s": ARCHIVE_TIMEFRAME_S,
        "entry_delay_ms": ENTRY_DELAY_MS, "max_payout_age_ms": MAX_PAYOUT_AGE_MS,
        "max_mood_age_ms": MAX_MOOD_AGE_MS, "payout_merge_ms": PAYOUT_MERGE_MS,
        "stall_gap_ms": STALL_GAP_MS, "control_exclusion_ms": CONTROL_EXCLUSION_MS,
        "family": [asdict(h) for h in FAMILY], "gates": GATES, "outcome_states": list(OUTCOME_STATES),
    }
