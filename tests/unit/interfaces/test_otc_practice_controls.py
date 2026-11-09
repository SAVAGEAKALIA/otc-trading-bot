"""Practice Telegram controls cannot change account, size, models or risk gates."""
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock
from trading_platform.legacy.iqoption_bot.bot import OTCTradingBot

class Controls(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.bot=OTCTradingBot({'account_type':'PRACTICE','admin_ids':[1]})
  self.bot.api_worker=SimpleNamespace(trading_enabled=True)
  self.owner=SimpleNamespace(sender_id=1)
 async def test_pause_and_resume_change_actual_order_admission(self):
  await self.bot.commands.handle(self.owner,'pause','test')
  self.assertFalse(self.bot.api_worker.trading_enabled);self.assertTrue(self.bot.paused)
  await self.bot.commands.handle(self.owner,'resume','')
  self.assertTrue(self.bot.api_worker.trading_enabled);self.assertFalse(self.bot.paused)
 async def test_unauthorized_controls_cannot_mutate(self):
  for command in ('pause','resume','start','stop','scanner','telegram'):
   reply=await self.bot.commands.handle(SimpleNamespace(sender_id=2),command,'off')
   self.assertIn('denied',reply.lower());self.assertTrue(self.bot.api_worker.trading_enabled)
 async def test_switch_is_read_only(self):
  self.bot.iq_api=MagicMock();self.bot.iq_api.get_balance.return_value=1000;self.bot.iq_api.get_balance_mode.return_value='PRACTICE'
  await self.bot.commands.handle(self.owner,'account','switch')
  self.bot.iq_api.change_balance.assert_not_called()
 async def test_removed_mutations_and_scanner_ml_are_unavailable(self):
  for cmd,args in [('martingale','on'),('sizing','fixed 100'),('reset','all'),('weights','auto'),('threshold','0')]:
   reply=await self.bot.commands.handle(self.owner,cmd,args);self.assertIn('Unavailable',reply)
  self.assertEqual(await self.bot.commands.handle(self.owner,'scanner','ml on'),'Use /scanner on or /scanner off.')
 async def test_notification_has_delivery_receipt(self):
  self.bot.telegram.client=AsyncMock();self.bot.telegram.client.send_message.return_value=SimpleNamespace(id=321)
  self.bot.telegram.is_running=True
  output=io.StringIO()
  with contextlib.redirect_stdout(output):await self.bot.telegram.send_notification('test')
  self.assertIn('TELEGRAM_NOTIFY delivered id=321',output.getvalue())
 def test_real_deployment_rejected_before_connect(self):
  with self.assertRaises(ValueError):OTCTradingBot({'account_type':'REAL'})
 def test_dry_run_is_retained(self):
  self.assertTrue(OTCTradingBot({'account_type':'PRACTICE','dry_run':True}).dry_run)
if __name__=='__main__':unittest.main()
