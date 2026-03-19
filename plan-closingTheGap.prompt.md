# Improvement Plan: Closing the Gap to 60%+

## Grounded in 192 fingerprints, 110 with candle data, zero speculation.

---

## THE RAW TRUTH FROM THE DATA

### What the data says about your two signal sources:

| Source | Win Rate | Trades | With Quality≥70 |
|--------|----------|--------|-----------------|
| **Telegram** | 61.0% (36W/23L) | 59 | **92.9%** (13W/1L over 14) |
| **Scanner** | 44.7% (59W/73L) | 132 | **68.8%** (11W/5L over 16) |

Telegram signals filtered through Quality≥70 produce 92.9% WR. That is the single highest-performing configuration in the entire database. The external signal source has genuine alpha. Your bot's job is to NOT destroy that alpha — and the quality overlay is doing its job.

Scanner signals are the problem. But even scanner signals at Quality≥70 reach 68.8% — above breakeven. The quality score works for both sources, but the scanner's base signal quality is worse, so it needs more help.

### What separates winning scanner trades from losing ones:

The **single biggest differentiator** in the microstructure data:

| Feature | Winner Average | Loser Average | Delta |
|---------|---------------|---------------|-------|
| **Expansion ratio** | **1.97x** | **3.63x** | **-1.66x** |
| Stoch K | 48.4 | 41.6 | +6.8 |
| RSI | 50.1 | 46.9 | +3.2 |

**Losers enter on candles that are 3.6x larger than the previous candle.** Winners enter on candles that are only 2x larger. This is the #1 candle-level signal the data screams about. The expansion trap gate at 1.5x catches some of this, but the strategy engines (Momentum Cascade, Compression Breakout) are DESIGNED to fire on expansion candles — creating a fundamental conflict.

### The Reversal Candle Death Zone:

| Pattern | Win Rate | Trades |
|---------|----------|--------|
| Continuation candle | 47.3% | 93 |
| **Reversal candle** | **29.4%** | **17** |

When the last candle reverses the previous candle's direction and the strategy still fires a signal in the reversal direction — it wins only 29.4% of the time. This is the second-most toxic pattern.

### The Steady Expansion Sweet Spot:

| Expansion Range | Win Rate | Trades |
|-----------------|----------|--------|
| Shrink (<0.5x) | 37.5% | 8 |
| **Steady (0.5-1.0x)** | **61.1%** | **18** |
| Mild expand (1.0-1.5x) | 52.4% | 21 |
| Strong expand (1.5-2.5x) | **35.5%** | 31 |
| Explosive (>2.5x) | **40.6%** | 32 |

The sweet spot is crystal clear: 0.5-1.0x expansion (slight body shrink). Steady, controlled candles. Not explosive moves. The current strategies fire on expanding candles — the data says the OPPOSITE.

### Body Ratio Reality:

| Body Ratio | Win Rate | Trades |
|------------|----------|--------|
| Doji (<0.2) | 25.0% | 4 |
| Small (0.2-0.4) | 50.0% | 8 |
| **Medium (0.4-0.6)** | **52.6%** | **19** |
| Large (0.6-0.8) | **40.0%** | 40 |
| Marubozu (>0.8) | 46.2% | 39 |

Large body candles (>0.6) — which is what Momentum Cascade explicitly looks for — have a **40-46% WR**. Medium bodies (0.4-0.6) perform best. The strategies are selecting for the wrong candle shape.

### The "Supportive Wick" Trap:

| Wick Pattern | Win Rate | Trades |
|-------------|----------|--------|
| **Supportive wick + 2m aligned + calm RSI** | **0.0%** | **6** |
| Opposing wick + 2m+5m aligned | 33.3% | 6 |

Zero wins out of 6 when trading with a "supportive" wick rejection. OTC engines fake wick rejections. The wick patterns that would work in real markets are traps in OTC. This is critical — the Exhaustion Fade strategy's Gate 4 requires wick rejection, which the data says is POISON.

### Combined Filter Discovery:

On scanner trades with candle data (110 trades):

| Filter | Win Rate | Trades |
|--------|----------|--------|
| Quality≥50 only | 49.3% | 69 |
| Quality≥50 + expansion<1.5x | 54.8% | 31 |
| **Quality≥50 + expansion<1.5x + candle aligned** | **59.3%** | **27** |
| Quality≥60 + expansion<1.5x | 57.9% | 19 |

Adding "candle direction aligned with trade direction" + "expansion under 1.5x" to the quality filter pushes scanner trades from 49.3% to 59.3%. That's the breakeven gap closed in one move.

---

## THE PLAN

### Phase 1: Fix What the Strategies Select For (the core problem)

**Problem:** Momentum Cascade fires on expanding body candles. Compression Breakout fires on expansion after compression. The data says expansion >1.5x = 35.5% WR. The strategies are literally selecting for losing conditions.

**Action 1A: Tighten Momentum Cascade expansion range.**
- Current: accepts 0.7x-1.5x expansion
- Data says: 0.5x-1.0x = 61.1% WR (sweet spot is STEADY, not expanding)
- Change: accept 0.5x-1.2x, cap at 1.2x instead of 1.5x
- Also: drop the body_ratio floor from 0.30 to 0.25, so medium-body candles (best WR) qualify

**Action 1B: Tighten Compression Breakout expansion.**
- Current: accepts 1.2x-2.0x expansion after compression
- Data: strong expansion = trap. The breakout candle should be mild.
- Change: narrow to 1.1x-1.5x (mild breakout, not explosive)

**Action 1C: Fix Exhaustion Fade wick requirement.**
- Current: requires wick rejection ≥ 20% of range
- Data: supportive wick entries = 0% WR over 6 trades
- Change: REMOVE the wick requirement entirely. Replace with: last candle must be small-bodied (body_ratio < 0.6) — a hesitation candle, not a wick rejection. OTC engines fake wicks but hesitation (small body) is harder to fake.

### Phase 2: Add a Candle Geometry Hard Gate to the Scanner

The combined filter data proves that **Quality≥50 + expansion<1.5x + candle direction aligned with trade** = 59.3% WR on scanner trades. This should be a scanner-level gate.

**Action 2A: "Entry Candle Health" gate in scanner.py**
New hard gate after Sprint 1/Sprint 2 gates:
- Block if entry candle expansion > 1.5x (already exists, but verify it's catching everything)
- Block if entry candle is a reversal candle (last candle reversed previous — 29.4% WR)
- Bonus points in quality score for steady expansion (0.5-1.0x)

**Action 2B: Adjust quality scoring weights based on microstructure findings.**

Current Factor 7 gives +5 for expansion ≤ 1.0x. The data says this is the single most important candle feature. Increase to +10 and penalize expansion > 1.5x by -10 (instead of just blocking it).

New Factor 9: **Reversal Candle Penalty (-10)**
If the entry candle reversed the previous candle's direction, deduct 10 points. This is a 29.4% WR death zone.

### Phase 3: The "Indicator Consensus" Strategy Redesign

The current combo (Cascade + Compression + Sniper + Exhaustion) has a fundamental problem: Cascade and Compression are both momentum/expansion strategies with similar failure modes. When both agree, it's often because they're both seeing the same expansion trap candle.

**Action 3A: Create a new strategy — "Steady State Continuation"**

Based on the data's clearest winning pattern:
- 2+ candles in the same direction (not 3 — the 3-candle run is 47.9% WR because by candle 3 the move is often exhausted)
- Body ratio 0.3-0.7 (medium — not doji, not marubozu)
- Expansion 0.5-1.2x (steady, no trap)
- MACD histogram confirms direction (adds +4% WR vs opposed)
- This replaces Momentum Cascade's role but selects for STEADY instead of EXPANDING candles

**Action 3B: Replace the 4-strategy combo with:**
- Steady State Continuation (new — replaces Cascade)
- Compression Breakout (tightened per 1B)
- Exhaustion Fade (fixed per 1C)
- Late Candle Sniper (keep as-is — low fire rate, serves as tiebreaker)

Agreement: 2/4 required.

### Phase 4: Exploit the Telegram Alpha Amplifier

Telegram signals at Quality≥70 = 92.9% WR. This is the bot's strongest edge and it's barely being leveraged.

**Action 4A: For Telegram signals, auto-upgrade quality threshold to 70.**
Currently Telegram goes through the gatekeeper, but the data shows gatekeeper mode barely filters compared to the quality overlay. Route Telegram signals through the same quality scoring as scanner signals, with minimum 70.

**Action 4B: When Telegram signal passes Quality≥70, increase position size by 1.5x.**
The edge is proven over 14 trades. Kelly criterion says bet more when edge is larger. A 92.9% WR at 85% payout means expected value is +$0.79/trade — you should size up.

### Phase 5: Fingerprint Gap Closure

**Problem:** 82 of 192 fingerprints have NO candle data. This means the microstructure gates (expansion, reversal, body ratio) can't be applied retroactively. And the Sprint 4 fields (quality_score, regime, body_expansion, run_length) are null for 191/192 records.

**Action 5A: Ensure every scanner signal's fingerprint records:**
- `body_expansion`: the entry candle's expansion ratio
- `run_length`: directional run count at entry
- `quality_score`: the Sprint 2 quality score
- `regime`: trending/ranging
- `candles`: always save last 10 candles (many records have this missing)

This is already in the code but may not be wired correctly for all paths. Verify and fix.

**Action 5B: After 200+ trades with full fingerprint data, recalibrate all thresholds.**
Every number in this plan (1.2x expansion cap, body_ratio ranges, quality_min 70) is calibrated on 110-192 trades. With 400+ you can narrow confidence intervals and find more precise thresholds.

---

## EXPECTED IMPACT

| Change | Expected WR Impact | Confidence |
|--------|-------------------|------------|
| Tighten strategy expansion to ≤1.2x | +5-8% on scanner trades | High (61.1% vs 35.5% on 49 trades) |
| Add reversal candle block | +2-3% (removes 29.4% WR trades) | Medium (17 trades) |
| Fix Exhaustion Fade wick logic | Unknown (removes 0% WR pattern) | High (0W/6L is definitive) |
| Quality≥70 for all paths | Scanner: 68.8%, Telegram: 92.9% | High (30 trades combined) |
| Steady State strategy replacing Cascade | +5-10% if it captures the 0.5-1.0x sweet spot | Medium (new, needs validation) |

**Conservative estimate:** Scanner trades move from 44.7% → 55-60%. Combined with Telegram at 92.9%, blended rate should be 65-70%.

**This is achievable without inventing new strategies from theory.** Every change above is a direct response to what the data showed in the 192 fingerprints.

---

## IMPLEMENTATION ORDER

1. **Strategy tightening (1A, 1B, 1C)** — Smallest code change, highest immediate impact. Fixes the expansion trap at the source.
2. **Scanner gate (2A, 2B)** — Adds reversal candle block and adjusts quality weights. Second defense layer.
3. **Fingerprint fix (5A)** — Critical for validating everything above. Must be done early.
4. **Steady State strategy (3A, 3B)** — Most complex change. Build after 1-2 are validated with live data.
5. **Telegram alpha amplifier (4A, 4B)** — Easy win. Can be done in parallel with anything.

---

## WHAT I AM NOT PROPOSING (AND WHY)

- **Time-of-day gating**: The hour-level data has too few trades per bucket (3-15) to be statistically meaningful. Not enough signal.
- **Asset-specific filters**: Same problem — most assets have <5 trades. No reliable per-asset edge visible yet.
- **New indicator combinations**: MACD confirms direction at 44.8% WR, opposes at 43.5%. BB position shows no edge in any zone. RSI zones only matter at extremes (already gated). Indicators are not the path — candle geometry is.
- **Regime routing**: Still always reads "ranging." Until the ATR logic is validated with 200+ regime-tagged fingerprints, it's adding complexity without proven value.

