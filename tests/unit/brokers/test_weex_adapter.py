import asyncio
import base64
import hmac
import hashlib
import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from trading_platform.brokers.weex.api import WeexAdapter

def test_weex_adapter_initialization():
    adapter = WeexAdapter(api_key="test_key", api_secret="test_secret", passphrase="test_passphrase")
    assert adapter.api_key == "test_key"
    assert adapter.api_secret == "test_secret"
    assert adapter.passphrase == "test_passphrase"

def test_generate_signature():
    adapter = WeexAdapter(api_key="key", api_secret="secret")
    timestamp = "1620000000000"
    method = "GET"
    path = "/api/v1/test"
    body = '{"foo":"bar"}'
    
    # Expected manual HMAC calculation
    message = f"{timestamp}{method}{path}{body}"
    mac = hmac.new(
        b"secret",
        message.encode("utf-8"),
        digestmod=hashlib.sha256
    )
    expected_sig = base64.b64encode(mac.digest()).decode()
    
    sig = adapter._generate_signature(timestamp, method, path, body)
    assert sig == expected_sig

@pytest.mark.asyncio
@patch("aiohttp.ClientSession.request")
async def test_weex_adapter_get_balance_futures(mock_request):
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "code": "0",
        "msg": "success",
        "data": {
            "USDT": {"available": "1500.50"}
        }
    }
    # aiohttp session.request returns a context manager
    mock_request.return_value.__aenter__.return_value = mock_response
    
    adapter = WeexAdapter(api_key="key", api_secret="secret")
    balance = await adapter.get_balance(market_type="futures")
    
    assert "USDT" in balance
    assert balance["USDT"] == Decimal("1500.50")
    
    # Check that it called the correct endpoint
    mock_request.assert_called_once()
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/v1/mix/account/account"
    
    await adapter.close()

@pytest.mark.asyncio
@patch("aiohttp.ClientSession.request")
async def test_weex_adapter_place_order_spot(mock_request):
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "code": "0",
        "msg": "success",
        "data": {"orderId": "12345"}
    }
    mock_request.return_value.__aenter__.return_value = mock_response
    
    adapter = WeexAdapter(api_key="key", api_secret="secret")
    result = await adapter.place_order(
        symbol="BTC_USDT",
        side="buy",
        quantity=Decimal("0.1"),
        price=Decimal("60000"),
        market_type="spot",
        client_oid="my_id_1"
    )
    
    assert result == {"orderId": "12345"}
    
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/api/v1/spot/order/placeOrder"
    
    body = kwargs.get("json")
    assert body["symbol"] == "BTC_USDT"
    assert body["clientOid"] == "my_id_1"
    assert body["sz"] == "0.1"
    
    await adapter.close()
