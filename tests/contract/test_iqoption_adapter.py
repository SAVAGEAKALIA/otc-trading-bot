"""Contract tests for restored practice-only binary adapter."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from trading_platform.application.ports import BinaryExecutionPort
from trading_platform.brokers.iqoption.execution import IQOptionBinaryExecutionAdapter
from trading_platform.legacy.iqoption_bot.asset_resolver import AssetResolver
from tests.unit.brokers.test_iqoption_practice import Broker, BinaryOrderCommand, BinaryDirection, Decimal


def test_adapter_port(tmp_path):
    adapter=IQOptionBinaryExecutionAdapter(Broker(),ledger_path=str(tmp_path/'ledger.sqlite3'))
    assert isinstance(adapter,BinaryExecutionPort)


def test_asset_resolver_preserves_typed_command():
    worker=type('Worker',(),{'api':Broker(),'execution_context':{'strategy':'fixed'}})()
    execution=AsyncMock()
    execution.place_binary_order.return_value.accepted=True
    execution.place_binary_order.return_value.order_id=555
    resolver=AssetResolver(worker,execution_adapter=execution)
    assert asyncio.run(resolver.place_trade('USDNGN-OTC','call',1.0,2))==(True,555)
    command=execution.place_binary_order.await_args.args[0]
    assert command==BinaryOrderCommand('USDNGN-OTC',BinaryDirection.CALL,Decimal('1'),2,{'strategy':'fixed'})
