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
        TF_2M: 50,   # 50 x 2m = 100 minutes of data
        TF_5M: 84,   # 84 x 5m = 420 minutes → yields 28 synthetic 15m candles (84/3=28)
        TF_15M: 30,  # 30 x 15m = 450 minutes (>= 26 needed for indicator calc)
    }

    # Cache TTL (time-to-live) in seconds
    CACHE_TTL = 15  # 15 seconds - balances freshness vs API load

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

        For OTC forex pairs (like EURUSD-OTC), use the base name (EURUSD).
        For other OTC assets, keep the full name as-is since they may
        require the full identifier.

        Args:
            asset: Asset name (with or without OTC suffix)

        Returns:
            Asset name for candle API calls
        """
        asset_upper = asset.upper()

        # Standard forex OTC pairs - strip the -OTC suffix
        # These are pairs like EURUSD-OTC, GBPJPY-OTC, etc.
        forex_bases = [
            'EUR', 'USD', 'GBP', 'JPY', 'CHF', 'AUD', 'NZD', 'CAD',
            'SEK', 'NOK', 'DKK', 'SGD', 'HKD', 'MXN', 'ZAR', 'TRY',
            'PLN', 'HUF', 'CZK', 'ILS', 'THB', 'INR', 'CNY', 'KRW'
        ]

        # Check if it's a standard forex OTC pair
        base = asset_upper \
            .replace("-OTC", "") \
            .replace("-OP", "") \
            .replace("_OTC", "") \
            .strip()

        # If it looks like a forex pair (6 chars, both parts are currencies)
        if len(base) == 6:
            first_currency = base[:3]
            second_currency = base[3:]
            if first_currency in forex_bases and second_currency in forex_bases:
                return base

        # For non-forex OTC pairs, return the full name with -OTC
        # The API might need the full identifier
        if '-OTC' in asset_upper or '-OP' in asset_upper:
            return asset  # Keep original name

        return base

    @staticmethod
    def _synthesize_15m_from_5m(candles_5m: List[dict]) -> List[dict]:
        """
        Build synthetic 15-minute candles by aggregating groups of 3 × 5m candles.

        OTC pairs often lack native 15m data from the API because they are
        synthetic markets with short-term data only. This method creates
        equivalent 15m candles from the 5m data that is reliably available.

        Each synthetic 15m candle:
        - open  = first 5m candle's open
        - high  = max high across the 3 candles
        - low   = min low across the 3 candles
        - close = last 5m candle's close
        - volume = sum of volumes
        - at/from = timestamp of the first candle in the group

        Args:
            candles_5m: List of 5m candle dicts (need at least 6 for 2 synthetic candles)

        Returns:
            List of synthetic 15m candle dicts
        """
        if not candles_5m or len(candles_5m) < 3:
            return []

        synthetic = []
        # Process in groups of 3, starting from the end to keep alignment
        # (most recent candles are most important)
        aligned = candles_5m[len(candles_5m) % 3:]  # Trim front to make divisible by 3
        if not aligned:
            aligned = candles_5m

        for i in range(0, len(aligned) - 2, 3):
            chunk = aligned[i:i + 3]
            if len(chunk) < 3:
                break

            # Extract OHLCV from each candle (handle both dict key formats)
            def _get(c, *keys):
                for k in keys:
                    if k in c:
                        return float(c[k])
                return 0.0

            opens = [_get(c, 'open', 'o') for c in chunk]
            highs = [_get(c, 'max', 'high', 'h') for c in chunk]
            lows = [_get(c, 'min', 'low', 'l') for c in chunk]
            closes = [_get(c, 'close', 'c') for c in chunk]
            volumes = [_get(c, 'volume', 'v') for c in chunk]

            synthetic.append({
                'open': opens[0],
                'max': max(highs) if highs else 0,
                'min': min(lows) if lows else 0,
                'close': closes[-1],
                'volume': sum(volumes),
                'at': chunk[0].get('at', chunk[0].get('from', chunk[0].get('time', 0))),
                'from': chunk[0].get('from', chunk[0].get('at', chunk[0].get('time', 0))),
                'id': chunk[0].get('id', 0),
            })

        return synthetic

    async def get_mtf_bundle(
        self,
        asset: str,
        include_5m: bool = True,
        include_15m: bool = True
    ) -> MTFBundle:
        """
        Fetch multi-timeframe candle bundle for analysis.

        Always fetches 2m candles. Optionally fetches 5m and 15m
        if MTF is enabled and requested.

        15m candle fallback:
        If the API returns no valid 15m data (common for OTC pairs),
        synthetic 15m candles are built from 5m data (groups of 3).
        This ensures strategies and filters always have 15m context.

        Args:
            asset: Asset name (will be normalized to OTC)
            include_5m: Whether to fetch 5-minute candles
            include_15m: Whether to fetch 15-minute candles

        Returns:
            MTFBundle with available candle data
        """
        otc_asset = self.normalize_otc_asset(asset)
        base_asset = self.get_base_asset(asset)

        # Always fetch 2m (entry timeframe)
        entry_data = await self._fetch_candles(base_asset, self.TF_2M)

        # Fetch higher timeframes if enabled
        mid_data = None
        high_data = None

        if self.mtf_enabled:
            if include_5m:
                mid_data = await self._fetch_candles(base_asset, self.TF_5M)
            if include_15m:
                high_data = await self._fetch_candles(base_asset, self.TF_15M)

                # FALLBACK: If 15m fetch failed or returned invalid data,
                # synthesize from 5m candles (3 × 5m = 1 × 15m).
                # OTC pairs often lack native 15m data from the API.
                if (high_data is None or not high_data.is_valid) and mid_data and mid_data.is_valid:
                    synthetic_candles = self._synthesize_15m_from_5m(mid_data.candles)
                    if len(synthetic_candles) >= 10:
                        high_data = CandleData(
                            timeframe=self.TF_15M,
                            candles=synthetic_candles
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
        if cached is not None:
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
            last_candle_time = candles[-1].get('at', 0)
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
            from iqoptionapi.constants import ACTIVES as OP_ACTIVES
            if asset not in OP_ACTIVES:
                # Asset not in constants - silently return None
                return None
        except Exception:
            pass  # If we can't check, proceed anyway

        # Serialize: only one API candle fetch at a time
        async with self._api_lock:
            try:
                # Add timeout to prevent blocking on library hangs
                candles = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self.api.get_candles(asset, timeframe, count, time.time())
                    ),
                    timeout=15.0  # 15 second timeout for data fetch
                )
                return candles
            except asyncio.TimeoutError:
                print(f"   ⚠️ API Timeout: Failed to fetch data for {asset} within 15s")
                return None
            except Exception as e:
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

        # Check if cache is still fresh
        if cached.age_seconds > self.CACHE_TTL:
            self._cache_misses += 1
            return None

        self._cache_hits += 1
        return cached

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
        }

