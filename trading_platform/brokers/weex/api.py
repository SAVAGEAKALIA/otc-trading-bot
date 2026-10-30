import asyncio
import base64
import hmac
import hashlib
import json
import time
from decimal import Decimal
from typing import Any, Mapping, Optional
from urllib.parse import urlencode

import aiohttp


class WeexAdapter:
    """
    Weex Broker Adapter.
    Implements REST API interactions with HMAC-SHA256 signing for Spot and Futures.
    """
    BASE_URL = "https://api.weex.com"

    def __init__(self, api_key: str, api_secret: str, passphrase: str = "") -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                base_url=self.BASE_URL,
                headers={"Content-Type": "application/json"}
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """
        Generates HMAC-SHA256 signature for WEEX API requests.
        Payload: timestamp + method + request_path + body
        """
        message = f"{timestamp}{method.upper()}{request_path}{body}"
        mac = hmac.new(
            bytes(self.api_secret, encoding="utf8"),
            bytes(message, encoding="utf-8"),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()

    async def _dispatch_request(self, method: str, endpoint: str, params: dict = None, body: dict = None) -> Any:
        session = await self._get_session()
        timestamp = str(int(time.time() * 1000))
        
        request_path = endpoint
        if params:
            request_path += "?" + urlencode(params)
            
        body_str = json.dumps(body) if body else ""
        
        signature = self._generate_signature(timestamp, method, request_path, body_str)
        
        headers = {
            "WEEX-ACCESS-KEY": self.api_key,
            "WEEX-ACCESS-SIGN": signature,
            "WEEX-ACCESS-TIMESTAMP": timestamp,
            "WEEX-ACCESS-PASSPHRASE": self.passphrase,
        }

        async with session.request(method, endpoint, params=params, json=body, headers=headers) as response:
            data = await response.json()
            if str(data.get("code", "0")) != "0":
                raise RuntimeError(f"WEEX API Error [{data.get('code')}]: {data.get('msg')}")
            return data.get("data")

    async def get_balance(self, market_type: str = "futures") -> Mapping[str, Decimal]:
        """
        Fetches account balance. Supports 'spot' and 'futures'.
        """
        if market_type.lower() == "spot":
            endpoint = "/api/v1/spot/account/assets"
        else:
            endpoint = "/api/v1/mix/account/account"
            
        data = await self._dispatch_request("GET", endpoint)
        
        balances = {}
        if market_type.lower() == "spot":
            # Spot usually returns a list of assets
            for item in data:
                asset = item.get("coinName") or item.get("asset")
                available = item.get("available")
                if asset and available:
                    balances[asset] = Decimal(str(available))
        else:
            # Futures usually returns a dictionary or a list of margin accounts
            if isinstance(data, dict):
                # E.g. {"USDT": {"available": "100.0", ...}}
                for asset, info in data.items():
                    if isinstance(info, dict) and "available" in info:
                        balances[asset] = Decimal(str(info["available"]))
            elif isinstance(data, list):
                for item in data:
                    asset = item.get("marginCoin")
                    available = item.get("available")
                    if asset and available:
                        balances[asset] = Decimal(str(available))
                        
        return balances

    async def place_order(
        self, symbol: str, side: str, quantity: Decimal, price: Decimal, market_type: str = "futures", client_oid: str = ""
    ) -> Mapping[str, Any]:
        """
        Places a limit order on the specified market.
        Supports idempotency via client_oid.
        """
        if market_type.lower() == "spot":
            endpoint = "/api/v1/spot/order/placeOrder"
            payload = {
                "symbol": symbol,
                "side": side.lower(),
                "orderType": "limit",
                "sz": str(quantity),
                "px": str(price),
                "clientOid": client_oid
            }
        else:
            endpoint = "/api/v1/mix/order/placeOrder"
            payload = {
                "symbol": symbol,
                "marginCoin": "USDT",
                "side": side.lower(), # e.g. "open_long", "close_long"
                "orderType": "limit",
                "size": str(quantity),
                "price": str(price),
                "clientOid": client_oid
            }

        # Filter out empty client_oids
        if not client_oid:
            payload.pop("clientOid", None)
            
        return await self._dispatch_request("POST", endpoint, body=payload)
