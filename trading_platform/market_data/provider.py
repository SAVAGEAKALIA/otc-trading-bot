"""
Market Data Provider for OTC Binary Options Trading.

Centralizes all candle fetching logic with:
- OTC-only asset normalization
- Multi-timeframe (MTF) bundle support (2m, 5m, 15m)
- Simple caching to reduce API calls
- Graceful degradation when data unavailable
"""

import time
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field


@dataclass
class CandleData:
    """Container for candle data from a single timeframe."""
    timeframe: int  # in seconds (120=2m, 300=5m, 900=15m)
    candles: List[dict]
    fetched_at: float = field(default_factory=time.time)

    @property
    def timeframe_label(self) -> str:
        """Human-readable timeframe label."""
        minutes = self.timeframe // 60
        return f"{minutes}m"

    @property
    def is_valid(self) -> bool:
        """Check if data exists and has minimum candles."""
        return self.candles is not None and len(self.candles) >= 10

    @property
    def age_seconds(self) -> float:
        """How old this data is in seconds."""
        return time.time() - self.fetched_at


def get_completed_candles(candles: list, min_required: int = 1) -> list:
    """
    Returns only fully closed candles, excluding the currently-forming candle.
    IQ Option's API returns the live/incomplete candle as the last element.
    Returns an empty list if fewer than min_required completed candles are available.

    This function is idempotent: if passed a list that has already had its
    forming candle removed (or contains only closed historical candles), it will not
    slice off a second closed candle.
    """
    if not candles:
        return []

    # Check if last candle is forming vs completed using timestamp comparison if available
    last_candle = candles[-1]
    is_forming = True

    if isinstance(last_candle, dict):
        c_start = float(last_candle.get('at', last_candle.get('from', 0)))
        if c_start > 0:
            # Infer timeframe interval from candle gap if >= 2 candles, else default to 120s (2m)
            tf = 120
            if len(candles) >= 2 and isinstance(candles[-2], dict):
                prev_start = float(candles[-2].get('at', candles[-2].get('from', 0)))
                if prev_start > 0 and c_start > prev_start:
                    tf = int(c_start - prev_start)

            # If current time >= c_start + tf, then last_candle is ALREADY completed!
            now = time.time()
            if now >= (c_start + tf):
                is_forming = False

    if is_forming:
        completed = candles[:-1]
    else:
        completed = candles

    if len(completed) < min_required:
        return []

    return completed



@dataclass
class MTFBundle:
    """
    Multi-Timeframe data bundle for analysis.

    Contains candle data for entry timeframe (2m) plus
    higher timeframes (5m, 15m) for context.
    """
    asset: str
    entry_tf: CandleData  # 2-minute candles (entry timeframe)
    mid_tf: Optional[CandleData] = None  # 5-minute candles (trend context)
    high_tf: Optional[CandleData] = None  # 15-minute candles (structure context)
    fetched_at: float = field(default_factory=time.time)

    @property
    def has_mtf_data(self) -> bool:
        """Check if higher timeframes are available."""
        return (self.mid_tf is not None and self.mid_tf.is_valid) or \
               (self.high_tf is not None and self.high_tf.is_valid)

    @property
    def has_full_mtf(self) -> bool:
        """Check if all timeframes are available."""
        return self.entry_tf.is_valid and \
               (self.mid_tf is not None and self.mid_tf.is_valid) and \
               (self.high_tf is not None and self.high_tf.is_valid)

    def get_status_summary(self) -> str:
        """Get a summary of available data."""
        parts = []
        if self.entry_tf.is_valid:
            parts.append(f"2m:{len(self.entry_tf.candles)}")
        if self.mid_tf and self.mid_tf.is_valid:
            parts.append(f"5m:{len(self.mid_tf.candles)}")
        if self.high_tf and self.high_tf.is_valid:
            parts.append(f"15m:{len(self.high_tf.candles)}")
        return f"MTF[{', '.join(parts)}]" if parts else "MTF[none]"


class MarketDataProvider:
    """
    Centralized market data provider for OTC trading.

    Responsibilities:
    - OTC-only asset normalization
    - Fetching candles for multiple timeframes
    - Simple caching to reduce redundant API calls
    - Graceful handling of missing data

    Usage:
        provider = MarketDataProvider(iq_api)
        bundle = await provider.get_mtf_bundle("EURUSD-OTC")

        # Access individual timeframes
        candles_2m = bundle.entry_tf.candles
        candles_5m = bundle.mid_tf.candles if bundle.mid_tf else None
    """

    # Timeframe constants (in seconds)
    TF_2M = 120
    TF_5M = 300
    TF_15M = 900

    # Default candle counts per timeframe
    DEFAULT_COUNTS = {
        TF_2M: 120,   # 120 x 2m = 240 minutes of data (LSTM requires 90 + 30 for indicator warmup)
        TF_5M: 84,   # 420 minutes → 27-28 complete clock-aligned 15m candles
        TF_15M: 30,  # 30 x 15m = 450 minutes (>= 26 needed for indicator calc)
    }

    # Cache TTL (time-to-live) in seconds
    CACHE_TTL = 15  # 15 seconds - balances freshness vs API load
    API_FETCH_TIMEOUT = 12
    PIPELINE_REVISION = "2026-07-28-socket-timeout-clock-mtf"

    def __init__(self, iq_api, mtf_enabled: bool = True, connection_checker=None):
        """
        Initialize the data provider.

        Args:
            iq_api: IQ Option API instance
            mtf_enabled: Whether to fetch 5m/15m data (can disable for speed)
            connection_checker: Optional callable that returns True if connected
        """
        self.api = iq_api
        self.mtf_enabled = mtf_enabled
        self.connection_checker = connection_checker

        # Simple cache: asset -> {timeframe -> CandleData}
        self._cache: Dict[str, Dict[int, CandleData]] = {}
        self._cache_hits = 0
        self._cache_misses = 0

        # CRITICAL: Serialize all API candle fetches.
        # The IQ Option API library's get_candles() uses a shared mutable
        # attribute (self.api.candles.candles_data = None) that gets
        # overwritten by concurrent calls. When 5 assets fetch in parallel,
        # they race on this shared state, causing Asset A to read Asset B's
        # candle data. This lock ensures only one fetch happens at a time.
        self._api_lock = asyncio.Lock()
        # A timeout on wait_for does not stop a thread submitted through
        # run_in_executor. Keep that future visible so a second candle call
        # cannot overlap and corrupt the IQ client's shared candles_data.
        self._api_inflight = None
        self._api_inflight_started_at = 0.0
        self._last_busy_notice_at = 0.0
        print(
            "   📡 Market-data pipeline: "
            f"{self.PIPELINE_REVISION} (fetch timeout {self.API_FETCH_TIMEOUT}s)"
        )

    def normalize_otc_asset(self, asset: str) -> str:
        """
        Normalize asset name to OTC format.

        This bot ONLY trades OTC markets. Regular pairs are
        converted to OTC format (e.g., EURUSD -> EURUSD-OTC).

        Args:
            asset: Raw asset name from signal

        Returns:
            Normalized OTC asset name (e.g., "EURUSD-OTC")
        """
        # Extract base name, removing any existing suffix
        base = asset.upper() \
            .replace("-OTC", "") \
            .replace("-OP", "") \
            .replace("_OTC", "") \
            .replace("OTC", "") \
            .strip()

        # Always return as -OTC format
        return f"{base}-OTC"

    def get_base_asset(self, asset: str) -> str:
        """
        Get asset name for API candle calls.

        Candle data must come from the same broker instrument that will be
        traded. ``EURUSD`` and ``EURUSD-OTC`` have different active IDs and
        can have different price streams, so never strip an OTC/OP suffix.

        Args:
            asset: Asset name (with or without OTC suffix)

        Returns:
            Asset name for candle API calls
        """
        asset_upper = asset.upper()

        base = asset_upper \
            .replace("-OTC", "") \
            .replace("-OP", "") \
            .replace("_OTC", "") \
            .strip()

        if asset_upper.endswith("-OTC") or asset_upper.endswith("_OTC"):
            return f"{base}-OTC"
        if asset_upper.endswith("-OP"):
            # iqoptionapi keeps this legacy alias lowercase in ACTIVES.
            return f"{base}-op"
        return base

    @staticmethod
    def _synthesize_15m_from_5m(candles_5m: List[dict]) -> List[dict]:
        """
        Build clock-aligned 15-minute candles from IQ Option 5m candles.

        Only complete groups at UTC offsets :00/:05/:10 are accepted. A
        partial group, a missing 5m candle, duplicate timestamps, and the
        currently-forming 15m bucket are not emitted. This is the same
        aggregation contract used by the causal MTF training pipeline.

        Each synthetic 15m candle:
        - open  = first 5m candle's open
        - high  = max high across the 3 candles
        - low   = min low across the 3 candles
        - close = last 5m candle's close
        - volume = sum of volumes
        - at/from = timestamp of the first candle in the group

        Args:
            candles_5m: IQ Option 5m candle dictionaries.

        Returns:
            List of synthetic 15m candle dicts
        """
        if not candles_5m or len(candles_5m) < 3:
            return []

        def _number(candle, *keys):
            for key in keys:
                if key in candle and candle[key] is not None:
                    return float(candle[key])
            raise ValueError(f"missing candle field: {keys}")

        def _timestamp_seconds(candle) -> int:
            value = _number(candle, "at", "from", "time")
            # IQ Option integrations may expose seconds, milliseconds, or
            # microseconds. Normalize without altering the candle boundary.
            while value > 5_000_000_000:
                value /= 1000.0
            return int(value)

        # Last duplicate wins, matching historical CSV normalization.
        normalized = {}
        for candle in candles_5m:
            if not isinstance(candle, dict):
                continue
            try:
                timestamp = _timestamp_seconds(candle)
            except (TypeError, ValueError):
                continue
            normalized[timestamp] = candle

        buckets: Dict[int, List[Tuple[int, dict]]] = {}
        for timestamp, candle in sorted(normalized.items()):
            bucket_start = timestamp - (timestamp % 900)
            buckets.setdefault(bucket_start, []).append((timestamp, candle))

        synthetic = []
        for bucket_start, timestamped in sorted(buckets.items()):
            expected = [
                bucket_start,
                bucket_start + 300,
                bucket_start + 600,
            ]
            timestamps = [item[0] for item in timestamped]
            if timestamps != expected:
                continue

            chunk = [item[1] for item in timestamped]
            try:
                opens = [_number(candle, "open", "o") for candle in chunk]
                highs = [
                    _number(candle, "max", "high", "h")
                    for candle in chunk
                ]
                lows = [
                    _number(candle, "min", "low", "l")
                    for candle in chunk
                ]
                closes = [_number(candle, "close", "c") for candle in chunk]
                volumes = [
                    _number(candle, "volume", "v")
                    if any(key in candle for key in ("volume", "v"))
                    else 0.0
                    for candle in chunk
                ]
            except (TypeError, ValueError):
                continue

            synthetic.append({
                "open": opens[0],
                "max": max(highs),
                "min": min(lows),
                "close": closes[-1],
                "volume": sum(volumes),
                "at": bucket_start,
                "from": bucket_start,
                "to": bucket_start + 900,
                "id": chunk[0].get("id", 0),
            })

        return synthetic

    async def get_mtf_bundle(
        self,
        asset: str,
        include_5m: bool = True,
        include_15m: bool = True,
        entry_count: Optional[int] = None,
    ) -> MTFBundle:
        """
        Fetch multi-timeframe candle bundle for analysis.

        Always fetches 2m candles. Optionally fetches 5m and 15m
        if MTF is enabled and requested.

        15m candles are always synthesized from the IQ Option 5m response.
        Native broker 15m rows are deliberately not mixed into this pipeline.

        Args:
            asset: Asset name (will be normalized to OTC)
            include_5m: Whether to fetch 5-minute candles
            include_15m: Whether to fetch 15-minute candles
            entry_count: Optional 2-minute candle count for a strategy with
                a longer warm-up requirement.

        Returns:
            MTFBundle with available candle data
        """
        otc_asset = self.normalize_otc_asset(asset)
        base_asset = self.get_base_asset(asset)

        # Always fetch 2m (entry timeframe)
        entry_data = await self._fetch_candles(
            base_asset, self.TF_2M, entry_count
        )

        # Fetch higher timeframes if enabled
        mid_data = None
        high_data = None

        if self.mtf_enabled:
            synthesis_source = None
            if include_5m:
                mid_data = await self._fetch_candles(base_asset, self.TF_5M)
                synthesis_source = mid_data
            if include_15m:
                # Even a caller that requests 15m without exposing 5m must use
                # the same IQ Option 5m source as training; never fall back to
                # a native 900-second feed.
                if synthesis_source is None:
                    synthesis_source = await self._fetch_candles(
                        base_asset, self.TF_5M
                    )
                if synthesis_source and synthesis_source.is_valid:
                    synthetic_candles = self._synthesize_15m_from_5m(
                        synthesis_source.candles
                    )
                    if len(synthetic_candles) >= 10:
                        high_data = CandleData(
                            timeframe=self.TF_15M,
                            candles=synthetic_candles,
                        )

        return MTFBundle(
            asset=otc_asset,
            entry_tf=entry_data,
            mid_tf=mid_data,
            high_tf=high_data
        )

    async def get_candles(
        self,
        asset: str,
        timeframe: int = TF_2M,
        count: Optional[int] = None
    ) -> Optional[List[dict]]:
        """
        Fetch candles for a single timeframe.

        This is the low-level method. Prefer get_mtf_bundle()
        for gatekeeper analysis.

        Args:
            asset: Asset name (will extract base name)
            timeframe: Timeframe in seconds (120, 300, 900)
            count: Number of candles (uses default if None)

        Returns:
            List of candle dicts or None if unavailable
        """
        base_asset = self.get_base_asset(asset)
        data = await self._fetch_candles(base_asset, timeframe, count)
        return data.candles if data.is_valid else None

    async def _fetch_candles(
        self,
        base_asset: str,
        timeframe: int,
        count: Optional[int] = None
    ) -> CandleData:
        """
        Internal method to fetch candles with caching.

        Args:
            base_asset: Base asset name (no -OTC suffix)
            timeframe: Timeframe in seconds
            count: Number of candles to fetch

        Returns:
            CandleData (may have empty candles list if fetch failed)
        """
        count = count or self.DEFAULT_COUNTS.get(timeframe, 50)

        # Check cache first
        cached = self._get_cached(base_asset, timeframe)
        if cached is not None and len(cached.candles) >= count:
            return cached

        # Check connection before fetching
        if self.connection_checker and not self.connection_checker():
            return CandleData(timeframe=timeframe, candles=[])

        # Fetch from API
        candles = await self._api_fetch(base_asset, timeframe, count)

        # DATA FRESHNESS CHECK:
        # If API returns data but it's fundamentally stale (e.g. from 1 hour ago),
        # treat it as empty to avoid "Stale Data" traps during analysis.
        if candles and len(candles) > 0:
            # IQ Option normally returns both fields, but historical and OTC
            # responses can expose only ``from``.  Do not accidentally skip
            # the freshness guard in that case.
            last_candle_time = candles[-1].get(
                'at', candles[-1].get('from', 0)
            )
            if last_candle_time > 0:
                data_age = time.time() - last_candle_time
                # Dynamic stale check: 120s for 2m, otherwise 2x timeframe
                stale_threshold = 120 if timeframe == self.TF_2M else max(180, timeframe * 2) 
                if data_age > stale_threshold:
                    print(f"   ⚠️ Data Abandoned: {base_asset} age={data_age:.0f}s (Threshold: {stale_threshold}s)")
                    candles = []

        # Create data object
        data = CandleData(
            timeframe=timeframe,
            candles=candles if candles else []
        )

        # Cache the result (even if empty, to avoid hammering API)
        self._set_cached(base_asset, timeframe, data)

        return data

    async def _api_fetch(
        self,
        asset: str,
        timeframe: int,
        count: int
    ) -> Optional[List[dict]]:
        """
        Fetch candles from IQ Option API.

        Runs in executor to avoid blocking the async loop.
        Pre-checks if asset exists to avoid library print spam.

        CRITICAL: Serialized via _api_lock because the IQ Option API
        library uses a shared mutable `candles_data` attribute that
        races when called concurrently from multiple coroutines.
        """
        loop = asyncio.get_event_loop()

        # Pre-check if asset exists in ACTIVES to avoid print spam from library
        try:
            from trading_platform.vendor.iqoptionapi.iqoptionapi.constants import ACTIVES as OP_ACTIVES
            if asset not in OP_ACTIVES:
                # Asset not in constants - silently return None
                return None
        except Exception:
            pass  # If we can't check, proceed anyway

        # Early exit if websocket is known to be dead to prevent hanging threads
        try:
            if not self.api.check_connect():
                if self.connection_checker:
                    self.connection_checker()
                return None
        except Exception:
            pass

        # Serialize: only one physical API candle fetch at a time. A timed
        # out executor call may still be running, so starting another call
        # would recreate the shared-state race the lock is meant to prevent.
        async with self._api_lock:
            if self._api_inflight is not None:
                if self._api_inflight.done():
                    self._api_inflight = None
                    self._api_inflight_started_at = 0.0
                else:
                    now = time.time()
                    if now - self._last_busy_notice_at >= 10:
                        elapsed = now - self._api_inflight_started_at
                        print(
                            "   ⚠️ Candle request still in progress "
                            f"({elapsed:.0f}s); deferring additional scanner fetches"
                        )
                        self._last_busy_notice_at = now
                    return None

            future = loop.run_in_executor(
                None,
                lambda: self.api.get_candles(asset, timeframe, count, time.time())
            )
            self._api_inflight = future
            self._api_inflight_started_at = time.time()
            try:
                # Shield preserves the future after a timeout; it must finish
                # before another thread is allowed to touch the shared API
                # candle response buffer.
                candles = await asyncio.wait_for(
                    asyncio.shield(future),
                    timeout=self.API_FETCH_TIMEOUT,
                )
                if self._api_inflight is future:
                    self._api_inflight = None
                    self._api_inflight_started_at = 0.0
                self._consecutive_timeouts = 0  # Reset on success
                return candles
            except asyncio.TimeoutError:
                self._consecutive_timeouts = getattr(self, '_consecutive_timeouts', 0) + 1
                print(f"   ⚠️ API Timeout ({self._consecutive_timeouts}/3): Failed to fetch data for {asset}")
                # This is an API-request timeout, not proof that the websocket
                # is dead. The connection manager remains the only component
                # allowed to reconnect the shared session.
                if self._consecutive_timeouts >= 3:
                    print(
                        "   ⚠️ Candle API is unresponsive; pausing new candle "
                        "requests until the in-flight call finishes"
                    )
                    self._consecutive_timeouts = 0
                return None
            except Exception as e:
                if self._api_inflight is future:
                    self._api_inflight = None
                    self._api_inflight_started_at = 0.0
                error_str = str(e).lower()
                # Silently ignore known non-critical errors
                if 'closed' in error_str or 'connection' in error_str:
                    print(f"   ⚠️ API Connection Warning: {e}")
                    if self.connection_checker:
                        # Notify connection manager effectively
                        self.connection_checker()
                elif 'not found' in error_str or 'consts' in error_str:
                    pass  # Asset not supported - silently skip
                return None

    def _get_cached(self, asset: str, timeframe: int) -> Optional[CandleData]:
        """Get cached data if still valid."""
        if asset not in self._cache:
            self._cache_misses += 1
            return None

        if timeframe not in self._cache[asset]:
            self._cache_misses += 1
            return None

        cached = self._cache[asset][timeframe]

        # A response normally includes the currently-forming bar.  A snapshot
        # taken before a boundary must never be reused after that boundary:
        # get_completed_candles() would then see the old partial OHLC as a
        # completed candle merely because wall-clock time has moved on.  Force
        # a new request at the boundary; if it times out, the caller receives
        # no data and skips the asset instead of trading stale OHLC values.
        if self._cache_crossed_candle_boundary(cached, timeframe):
            self._cache_misses += 1
            return None

        # Timeframe-specific TTLs
        ttl = self.CACHE_TTL
        if timeframe == self.TF_5M:
            ttl = 240  # 4 minutes for 5m candles
        elif timeframe == self.TF_15M:
            ttl = 840  # 14 minutes for 15m candles

        # Check if cache is still fresh
        if cached.age_seconds > ttl:
            self._cache_misses += 1
            return None

        self._cache_hits += 1
        return cached

    @staticmethod
    def _cache_crossed_candle_boundary(cached: CandleData, timeframe: int) -> bool:
        """Whether a cached snapshot could contain a now-closed partial bar."""
        if not cached.candles or timeframe <= 0:
            return False

        last_candle = cached.candles[-1]
        if not isinstance(last_candle, dict):
            return False

        try:
            candle_start = float(last_candle.get('at', last_candle.get('from', 0)))
        except (TypeError, ValueError):
            return False
        if candle_start <= 0:
            return False

        candle_end = candle_start + timeframe
        now = time.time()
        return cached.fetched_at < candle_end <= now

    def _set_cached(self, asset: str, timeframe: int, data: CandleData):
        """Store data in cache."""
        if asset not in self._cache:
            self._cache[asset] = {}
        self._cache[asset][timeframe] = data

    def clear_cache(self, asset: Optional[str] = None):
        """
        Clear cached data.

        Args:
            asset: Specific asset to clear, or None for all
        """
        if asset:
            base = self.get_base_asset(asset)
            self._cache.pop(base, None)
        else:
            self._cache.clear()

    def set_mtf_enabled(self, enabled: bool):
        """Enable or disable multi-timeframe fetching."""
        self.mtf_enabled = enabled
        print(f"📊 MTF data fetching {'enabled' if enabled else 'disabled'}")

    def get_status(self) -> Dict[str, Any]:
        """Get provider status and cache info."""
        cache_entries = sum(len(tfs) for tfs in self._cache.values())
        total = self._cache_hits + self._cache_misses
        return {
            'mtf_enabled': self.mtf_enabled,
            'cache_entries': cache_entries,
            'cache_ttl': self.CACHE_TTL,
            'cache_hits': self._cache_hits,
            'cache_misses': self._cache_misses,
            'cache_hit_rate': (self._cache_hits / total * 100) if total > 0 else 0.0,
            'api_request_in_flight': (
                self._api_inflight is not None and not self._api_inflight.done()
            ),
        }

