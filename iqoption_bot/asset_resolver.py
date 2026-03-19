"""
Asset Resolver Module — Handles OTC asset lookup, validation, and trade placement.

Extracted from worker.py to reduce the god object. Contains:
- Asset ID cache management
- OTC pair filtering
- Asset validation and normalization
- Trade placement with -OTC/-op variant fallback
"""

import time
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .worker import APIWorker

logger = logging.getLogger(__name__)


class AssetResolver:
    """Manages OTC asset resolution, caching, and trade placement."""

    def __init__(self, worker: "APIWorker"):
        self._w = worker
        self.asset_id_cache: Dict[str, int] = {}

    @property
    def api(self):
        return self._w.api

    def initialize_cache(self):
        """Build asset name to ID cache from API's internal data."""
        try:
            print(f"   🔄 Fetching latest asset IDs from IQ Option...")
            try:
                self.api.update_ACTIVES_OPCODE()
                print(f"   ✅ Asset IDs updated from server")
            except Exception as e:
                print(f"   ⚠️ Could not update asset IDs from server: {e}")

            all_actives = self.api.get_all_ACTIVES_OPCODE()
            if all_actives:
                self.asset_id_cache = dict(all_actives)
                otc_count = sum(1 for k in self.asset_id_cache.keys() if 'OTC' in str(k).upper())
                print(f"   📊 Loaded {len(self.asset_id_cache)} asset IDs ({otc_count} OTC pairs)")

                otc_samples = [(k, v) for k, v in self.asset_id_cache.items() if 'OTC' in str(k).upper()][:5]
                if otc_samples:
                    print(f"   📋 Sample OTC IDs: {otc_samples}")
        except Exception as e:
            print(f"   ⚠️ Could not load asset IDs: {e}")
            self.asset_id_cache = {}

    def get_cached_otc_pairs(self) -> List[str]:
        """
        Get list of tradeable forex OTC pairs from the pre-loaded cache.
        Filters to only include standard forex OTC pairs.
        """
        forex_currencies = {
            'EUR', 'USD', 'GBP', 'JPY', 'CHF', 'AUD', 'NZD', 'CAD',
            'SEK', 'NOK', 'DKK', 'SGD', 'HKD', 'MXN', 'ZAR', 'TRY',
            'PLN', 'HUF', 'CZK', 'ILS', 'THB', 'INR', 'CNY', 'KRW'
        }

        otc_pairs = []
        for asset_name in self.asset_id_cache.keys():
            asset_upper = str(asset_name).upper()

            if '-OTC' not in asset_upper and not asset_upper.endswith('-OP'):
                continue

            base = asset_upper.replace('-OTC', '').replace('-OP', '').strip()

            if len(base) == 6:
                first_currency = base[:3]
                second_currency = base[3:]
                if first_currency in forex_currencies and second_currency in forex_currencies:
                    otc_pairs.append(asset_name)

        return otc_pairs

    def get_asset_id(self, asset_name: str) -> Optional[int]:
        """Get the numeric ID for an asset name. Only looks for -op and -OTC variants."""
        # Direct match (case-sensitive)
        if asset_name in self.asset_id_cache:
            return self.asset_id_cache[asset_name]

        # Case-insensitive match
        asset_lower = asset_name.lower()
        for key, val in self.asset_id_cache.items():
            if key.lower() == asset_lower:
                return val

        # Extract base and try -op/-OTC variants
        base = asset_name.upper().replace("-OTC", "").replace("-OP", "").replace("_OTC", "")

        for key, val in self.asset_id_cache.items():
            if key.lower() == f"{base.lower()}-op":
                return val

        for key, val in self.asset_id_cache.items():
            if key.lower() == f"{base.lower()}-otc":
                return val

        return None

    async def validate_and_get_asset(self, asset: str) -> Optional[str]:
        """
        Validate and normalize asset to OTC format.
        This bot ONLY trades OTC markets.
        """
        base = asset.upper().replace("-OTC", "").replace("-OP", "").replace("_OTC", "").replace("OTC", "").strip()
        otc_asset = f"{base}-OTC"

        if 'OTC' not in asset.upper() and '-op' not in asset.lower():
            print(f"   🔄 Converting {asset} → {otc_asset} (OTC mode only)")

        return otc_asset

    async def place_trade(self, asset: str, direction: str, amount: float, duration: int) -> Tuple[bool, Any]:
        """
        Trade placement that ONLY trades OTC markets (-OTC and -op variants).
        Strategy: Extract base name → try -OTC first → fallback to -op.
        """
        loop = asyncio.get_event_loop()
        import iqoptionapi.constants as OP_code

        # Extract base name and build OTC variants ONLY
        base = asset.upper().replace("-OTC", "").replace("-OP", "").replace("_OTC", "").replace("OTC", "").strip()
        otc_variant = f"{base}-OTC"
        op_variant = f"{base}-op"

        print(f"   🎯 OTC Trading Mode: Base={base}")
        print(f"   📋 Will try: {otc_variant}, {op_variant} (NO regular pairs)")

        assets_to_try = []

        if otc_variant in OP_code.ACTIVES:
            assets_to_try.append((otc_variant, OP_code.ACTIVES[otc_variant]))
        if op_variant in OP_code.ACTIVES:
            assets_to_try.append((op_variant, OP_code.ACTIVES[op_variant]))

        if not assets_to_try:
            otc_id = self.get_asset_id(otc_variant)
            op_id = self.get_asset_id(op_variant)
            if otc_id:
                assets_to_try.append((otc_variant, otc_id))
            if op_id:
                assets_to_try.append((op_variant, op_id))

        if not assets_to_try:
            print(f"   ❌ No OTC variant found for {base}")
            print(f"   ℹ️  This bot only trades OTC markets (-OTC or -op)")
            return False, f"No OTC variant found for {asset}. This bot only trades OTC markets."

        print(f"   📋 OTC Variants to try: {[(a, i) for a, i in assets_to_try]}")

        last_error = "Unknown error"

        for asset_variant, asset_id in assets_to_try:
            OP_code.ACTIVES[asset_variant] = asset_id

            print(f"\n   🎯 Trying: {asset_variant} (ID: {asset_id})")

            try:
                def buy_func(a=asset_variant):
                    return self.api.buy(amount, a, direction, duration)

                print(f"   📤 api.buy({amount}, '{asset_variant}', '{direction}', {duration})")
                result = await loop.run_in_executor(None, buy_func)
                print(f"   📥 Result: {result}")

                if isinstance(result, tuple) and len(result) >= 2:
                    success, order_id = result[0], result[1]

                    if success and order_id:
                        print(f"   ✅ Order placed: {order_id}")
                        return True, order_id

                    error_msg = str(order_id) if order_id else "Rejected"
                    last_error = error_msg

                    if any(kw in error_msg.lower() for kw in ['not available', 'suspended', 'closed', 'invalid']):
                        print(f"   ❌ {asset_variant} rejected: {error_msg}")
                        continue

                    print(f"   ⚠️ Failed: {error_msg}")

                elif result is None:
                    last_error = "No response"
                    print(f"   ⚠️ No response")
                else:
                    last_error = str(result)
                    print(f"   ⚠️ Unexpected: {result}")

            except Exception as e:
                last_error = str(e)
                error_lower = last_error.lower()
                if 'closed' in error_lower or 'connection' in error_lower:
                    self._w.is_connected = False
                    print(f"   ⚠️ Connection lost during trade: {e}")
                    return False, "Connection lost"
                print(f"   ⚠️ Exception: {e}")

        print(f"   ❌ Both -OTC and -op variants failed. Last error: {last_error}")
        return False, last_error

    async def resolve_asset_name(self, asset: str) -> str:
        """Simple pass-through - let place_trade handle -op/-OTC variant logic."""
        return asset
