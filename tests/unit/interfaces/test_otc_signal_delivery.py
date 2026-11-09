"""Signal ingestion must not start catalogue threads or ingest bot receipts."""
import asyncio
import contextlib
from copy import deepcopy
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from trading_platform.brokers.iqoption.practice import PracticeExecution
from trading_platform.legacy.iqoption_bot.telegram_interface import TelegramInterface
from trading_platform.legacy.iqoption_bot.worker import APIWorker
from tests.unit.brokers.test_iqoption_practice import Broker, NOW


class CatalogueTrapBroker(Broker):
    def __init__(self):
        super().__init__()
        self.catalogue_calls = 0

    def get_all_open_time(self):
        self.catalogue_calls += 1
        raise AssertionError('unsupported catalogue starts reconnect threads')


class Client:
    def __init__(self):
        self.handlers = []

    def on(self, builder):
        def register(handler):
            self.handlers.append((builder, handler))
            return handler
        return register


class SignalDeliveryGates(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.api = CatalogueTrapBroker()
        self.guard = PracticeExecution(self.api, Path(self.tmp.name)/'orders.sqlite3')
        self.worker = object.__new__(APIWorker)
        self.worker.api = self.api
        self.worker.asset_resolver = SimpleNamespace(execution_adapter=SimpleNamespace(practice=self.guard))
        self.worker.session_manager = None
        self.worker.config = {}
        self.clock = patch('time.time_ns', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    async def test_telegram_asset_lookup_uses_actual_eligible_turbo_offer(self):
        self.assertEqual(await self.worker.get_available_assets(), {'turbo': {'USDNGN-OTC': {'open': True}}})
        self.assertEqual(self.api.catalogue_calls, 0)
        self.assertEqual(self.api.sent, [])

    async def test_closed_low_payout_non_otc_and_expired_offers_are_absent(self):
        original = deepcopy(self.api.offer)
        for change in ({'enabled': False}, {'is_suspended': True}, {'name': 'front.USDNGN'}, {'schedule': []}):
            self.api.offer = {**deepcopy(original), **change}
            self.assertEqual(await self.worker.get_available_assets(), {'turbo': {}})
        self.api.offer = deepcopy(original)
        self.api.offer['option']['profit']['commission'] = 21
        self.assertEqual(await self.worker.get_available_assets(), {'turbo': {}})
        self.assertEqual(self.api.catalogue_calls, 0)

    async def test_snapshot_failure_does_not_start_catalogue_or_invent_assets(self):
        self.api.get_all_init = lambda: None
        self.assertEqual(await self.worker.get_available_assets(), {})
        self.assertEqual(self.api.catalogue_calls, 0)

    def telegram(self):
        bot = SimpleNamespace(config={'channel_name': 'me'}, telegram_signals_enabled=True, scheduled_trades=[])
        interface = TelegramInterface(bot)
        interface.client = Client()
        interface.process_signal = AsyncMock()
        interface._setup_event_handlers()
        return interface

    async def test_notification_and_outgoing_trade_text_cannot_reenter_signal_route(self):
        interface = self.telegram()
        builder, handler = interface.client.handlers[1]
        self.assertTrue(builder.incoming)
        self.assertFalse(builder.outgoing)
        for text in ('CALL USDNGN-OTC 2M', 'Trade placed USDNGN-OTC', '/status'):
            await handler(SimpleNamespace(out=True, message=SimpleNamespace(message=text)))
        self.assertEqual(interface.bot.scheduled_trades, [])
        interface.process_signal.assert_not_awaited()

    async def test_incoming_channel_signal_still_reaches_processing(self):
        interface = self.telegram()
        handler = interface.client.handlers[1][1]
        message = 'CALL USDNGN-OTC 2M'
        await handler(SimpleNamespace(out=False, message=SimpleNamespace(message=message)))
        await asyncio.gather(*interface.bot.scheduled_trades)
        interface.process_signal.assert_awaited_once_with(message)

    async def test_channel_disabled_stops_signal_ingestion(self):
        interface = self.telegram()
        interface.bot.telegram_signals_enabled = False
        await interface.client.handlers[1][1](SimpleNamespace(out=False, message=SimpleNamespace(message='CALL USDNGN-OTC')))
        self.assertEqual(interface.bot.scheduled_trades, [])

    async def test_unavailable_payout_is_visible_and_releases_scanner_slot(self):
        worker = self.worker
        worker.is_connected = True
        worker.use_gatekeeper = False
        worker.gatekeeper_scanner = MagicMock()
        worker.notification_callback = AsyncMock()
        worker.pending_execution_count = 1
        worker._validate_and_get_asset = AsyncMock(return_value='USDNGN-OTC')
        worker._get_payout = AsyncMock(return_value=None)
        worker._place_trade = AsyncMock()
        worker.logger = MagicMock()
        worker.api.get_balance = lambda: 1000
        request = SimpleNamespace(
            signal=SimpleNamespace(asset='USDNGN-OTC', direction='call', duration=2, entry_time=None),
            source='scanner', martingale_step=0, skip_gatekeeper=True,
            indicators={'trend': 'bullish'}, indicators_5m=None, indicators_15m=None,
            martingale_series_id=None,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            await worker._execute_trade(request)
        worker.notification_callback.assert_awaited_once()
        self.assertIn('live payout is unavailable', worker.notification_callback.await_args.args[0])
        worker._place_trade.assert_not_awaited()
        self.assertEqual(worker.pending_execution_count, 0)

    async def test_late_connection_fault_never_reconnects_or_sends_order(self):
        for health in (False, RuntimeError('socket lost')):
            with self.subTest(health=type(health).__name__):
                worker = self.worker
                worker.is_connected = True
                worker.use_gatekeeper = False
                worker.gatekeeper_scanner = MagicMock()
                worker.notification_callback = AsyncMock()
                worker.pending_execution_count = 1
                worker._validate_and_get_asset = AsyncMock(return_value='USDNGN-OTC')
                worker._get_payout = AsyncMock(return_value=.85)
                worker._place_trade = AsyncMock()
                worker._schedule_platform_shadow = MagicMock(return_value=None)
                worker.logger = MagicMock()
                worker.logger.get_win_rate.return_value = .5
                worker.api.get_balance = lambda: 1000
                worker.api.connect = MagicMock()
                worker.api.check_connect = MagicMock(side_effect=health) if isinstance(health, Exception) else MagicMock(return_value=health)
                worker.sizer = MagicMock()
                worker.sizer.calculate_size.return_value = 1
                worker.allowed_trade_durations = (2,)
                request = SimpleNamespace(
                    signal=SimpleNamespace(asset='USDNGN-OTC', direction='call', duration=2, entry_time=None),
                    source='scanner', martingale_step=0, skip_gatekeeper=True,
                    indicators={'trend': 'bullish'}, indicators_5m=None, indicators_15m=None,
                    martingale_series_id=None,
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    await worker._execute_trade(request)
                worker.api.connect.assert_not_called()
                worker._place_trade.assert_not_awaited()
                self.assertFalse(worker.is_connected)
                self.assertEqual(worker.pending_execution_count, 0)
                worker.notification_callback.assert_awaited_once()
                self.assertIn('connection lost before submission', worker.notification_callback.await_args.args[0])


if __name__ == '__main__':
    unittest.main()
