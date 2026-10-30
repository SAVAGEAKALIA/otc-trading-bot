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
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple, List, TYPE_CHECKING

from trading_platform.brokers.iqoption.execution import (
    BinaryDirection,
    BinaryOrderCommand,
    IQOptionBinaryExecutionAdapter,
)

if TYPE_CHECKING:
    from .worker import APIWorker

logger = logging.getLogger(__name__)


class AssetResolver:
    """Manages OTC asset resolution, caching, and trade placement."""

    def __init__(self, worker: "APIWorker", execution_adapter=None):
        self._w = worker
        self.asset_id_cache: Dict[str, int] = {}
        self.execution_adapter = execution_adapter or IQOptionBinaryExecutionAdapter(
            self.api,
            asset_id_lookup=self.get_asset_id,
            on_connection_lost=self._mark_connection_lost,
        )

    def _mark_connection_lost(self) -> None:
        self._w.is_connected = False

    @property
    def api(self):
        return self._w.api

    def initialize_cache(self):
        """Build asset name to ID cache from API's internal data."""
        try:
            print(f"   🔄 Fetching latest binary OTC asset IDs from IQ Option...")
            try:
                self.api.update_binary_ACTIVES_OPCODE()
                print(f"   ✅ Binary asset IDs updated from server")
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

        # IQ Option exposes some instruments under both ``-OTC`` and ``-op``.
        # They are execution aliases for the same underlying pair, not separate
        # analysis opportunities.  Keep one deterministic preferred symbol so a
        # scan cannot evaluate and log the same market twice.
        otc_pairs: Dict[str, tuple[int, str]] = {}
        for asset_name in self.asset_id_cache.keys():
            asset_upper = str(asset_name).upper()

            if '-OTC' not in asset_upper and not asset_upper.endswith('-OP'):
                continue

            base = asset_upper.replace('-OTC', '').replace('-OP', '').strip()

            if len(base) == 6:
                first_currency = base[:3]
                second_currency = base[3:]
                if first_currency in forex_currencies and second_currency in forex_currencies:
                    preference = 0 if asset_upper.endswith("-OTC") else 1
                    current = otc_pairs.get(base)
                    if current is None or preference < current[0]:
                        otc_pairs[base] = (preference, str(asset_name))

        return [entry[1] for _, entry in sorted(otc_pairs.items())]

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
        Preserve the legacy tuple API while delegating execution to the adapter.
        """
        command = BinaryOrderCommand(
            asset=asset,
            direction=BinaryDirection(direction.lower()),
            amount=Decimal(str(amount)),
            duration_minutes=duration,
        )
        result = await self.execution_adapter.place_binary_order(command)
        if result.accepted:
            return True, result.order_id
        return False, result.error or "Unknown error"

    async def resolve_asset_name(self, asset: str) -> str:
        """Simple pass-through - let place_trade handle -op/-OTC variant logic."""
        return asset
