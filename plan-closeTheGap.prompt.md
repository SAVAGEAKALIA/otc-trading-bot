## Plan: Close the Gap — From 37% to 60%+

### The Starting Point (Unflinching)

Current win rate: **~37%**. Breakeven at 80% payout: **55.6%**. Target: **60%**. Gap: **23 points**. The fingerprint database was contaminated — **Phase 0 is complete** (cache key fix, result checker fix, data purge). Every trade from now on produces clean data.

Phase 1 redesigned the strategy layer: fixed the broken voting logic, fixed the scanner single-mode bug, added 3 new OTC-native strategies alongside the existing ones, and enforced real agreement-based signal quality.

---

### Phase 0: Fix The Measurement ✅ DONE

- ✅ Cache key collision fix (`analytics.py`) — full candle identity + symbol
- ✅ Cache TTL 10s → 3s
- ✅ Worker candle fallback removed (`worker.py`) — no cross-asset contamination
- ✅ Result checker: unknown → tie (not loss), 3× API retry, `result_method` field
- ✅ Fingerprint DB purged, 344 contaminated records backed up
- ✅ **API race condition fix** (`data_provider.py`) — IQ Option API's `get_candles()` uses
  a shared mutable `candles_data` attribute that gets overwritten by concurrent calls.
  Scanner ran 5 parallel fetches via semaphore, causing Asset A to read Asset B's candle
  data. Fixed by adding `asyncio.Lock()` to serialize all `_api_fetch()` calls.
  **This was the real root cause of identical indicators across different pairs.**

---

### Phase 1: Strategy & Engine Fixes ✅ DONE

#### 1.1 — Fixed voting logic in `StrategyEngine.evaluate()` ✅

**Was:** `evaluate()` picked the single strongest strategy by weighted score. Confluence was counted but never enforced. A lone strategy could fire trades when everyone else disagreed.

**Now:** After finding the best signal, counts how many strategies agree (`confluence_count`). If `confluence_count < min_agreement` (default 2) AND there are 2+ strategies running, returns `should_trade=False`. Solo strategies bypass the gate. Tournament mode (`evaluate_single()`) is unaffected.

#### 1.2 — Fixed scanner single-mode bug ✅

**Was:** `can_place_trade()` checked `if self.active_martingale_series: return False`. When `martingale_enabled=True`, every trade created a step-0 tracking stub, blocking ALL scanner signals for 2+ minutes.

**Now:** Only blocks if any series has `step > 0` (actively recovering). Step-0 stubs don't block.

#### 1.3 — Bypassed gatekeeper for scanner signals ✅

**Was:** Scanner signals went through `gatekeeper.decide()` PLUS the strategy engine — double-filtering that killed valid signals.

**Now:** Scanner uses a thin inline risk check (volatility regime + confidence threshold). `SignalGatekeeper` is fully intact for Telegram signals in `worker.py`.

#### 1.4 — Added 3 new OTC-native strategies ✅

All 9 existing strategies kept. 3 new ones added:

- **`MomentumCascadeStrategy`** — 3+ same-direction candles with body expansion → continue. Pure candle geometry.
- **`CompressionBreakoutStrategy`** — 5-candle compression + expansion candle → enter micro-trend direction. Pure candle geometry.
- **`LateCandleSniperStrategy`** — Strong directional commitment on last candle (body ratio >0.6, close in outer 20%) → continue. Pure candle geometry.

#### 1.5 — Registered new strategies in scanner ✅

12 strategies total in `_build_strategy_engine()`. New strategies selectable via `/scanner strategy cascade|compression|sniper` or combos like `/scanner strategy cascade+sniper+compression`.

#### 1.6 — Wired up `min_agreement` config + Telegram command ✅

- `ScannerConfig.min_agreement = 2` (default)
- Passed through `eval_kwargs['min_agreement']` to strategy engine
- `/scanner agreement <n>` command added
- Scanner status display shows current agreement setting

---

### What Changed vs What Stayed

| Component | Action | Status |
|-----------|--------|--------|
| 9 existing strategies | **Kept** | ✅ |
| 3 new strategies | **Added** | ✅ |
| `StrategyEngine.evaluate()` | **Fixed** — enforces min 2/3 agreement | ✅ |
| `StrategyEngine.evaluate_single()` | **Kept** — tournament mode unaffected | ✅ |
| Voting / Tournament modes | **Kept** | ✅ |
| `can_place_trade()` | **Fixed** — only blocks on recovery step > 0 | ✅ |
| Scanner gatekeeper call | **Removed** — strategy engine handles quality | ✅ |
| Telegram gatekeeper | **Kept** — fully intact | ✅ |
| Martingale system | **Kept** — as-is | ✅ |
| ML / PatternAnalyzer / Scoring | **Kept** | ✅ |

---

### Phase 2: Validation (200+ trades on practice account)

After 200 trades, analyze:
- Overall win rate by `strategy_used`
- Win rate when 3/3 agree vs 2/3 agree
- Per-strategy standalone performance from fingerprints
- New strategies vs old strategies head-to-head
- Win rate by hour, by asset, by volatility regime

**Decision gate:**
- **>57%:** Deploy real money with minimum positions
- **52-57%:** Thin edge — refine candle filters, run another 200
- **<52%:** The strategies need further rework or OTC has no exploitable edge with these tools
