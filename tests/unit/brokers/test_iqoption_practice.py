"""Regression gates for the actual restored bot's order boundary."""
import asyncio
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from trading_platform.brokers.iqoption.execution import BinaryDirection, BinaryOrderCommand, IQOptionBinaryExecutionAdapter
from trading_platform.brokers.iqoption.practice import PracticeExecution
from trading_platform.vendor.iqoptionapi.iqoptionapi.expiration import get_expiration_time

NOW = (time.time_ns() // 60_000_000_000) * 60_000_000_000 + 20_000_000_000

class Broker:
    def __init__(self):
        self.sent = []
        self.ack = (True, 123)
        self.selected = 4
        self.balances = [{'id': 4, 'type': 4, 'currency': 'USD', 'amount': 1000}]
        self.offer = {'name': 'front.USDNGN-OTC', 'enabled': True, 'is_suspended': False,
            'schedule': [[NOW//1_000_000_000-3600, NOW//1_000_000_000+3600]],
            'option': {'expiration_times': [60], 'start_time': NOW//1_000_000_000//60*60+60,
                       'exp_time': 60, 'count': 5, 'profit': {'commission': 15}}}
        self.closed = []
    def get_balances(self): return {'msg': deepcopy(self.balances)}
    def get_balance_id(self): return self.selected
    def get_server_timestamp(self): return NOW/1_000_000_000
    def get_all_init(self): return {'isSuccessful': True, 'result': {'turbo': {'actives': {'1865': deepcopy(self.offer)}}}}
    def buy_by_raw_expirations(self, *args, **kwargs):
        self.sent.append(args)
        if isinstance(self.ack, Exception): raise self.ack
        return self.ack
    def get_optioninfo(self, limit, **kwargs): return {'isSuccessful': True, 'result': {'closed_options': deepcopy(self.closed)}}
    def get_optioninfo_v2(self, *args, **kwargs): raise AssertionError('unhandled legacy options stream is not a settlement source')

class PracticeGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.broker = Broker()
        self.guard = PracticeExecution(self.broker, Path(self.tmp.name)/'orders.sqlite3')
        self.command = BinaryOrderCommand('USDNGN-OTC', BinaryDirection.CALL, Decimal('1'), 2, {'strategy':'test'})
        self.clock = patch('time.time_ns', return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
    def test_accepts_exact_offered_expiry_and_stake(self):
        self.assertEqual(self.guard.submit(self.command), (True,123))
        self.assertEqual(self.broker.sent[0][:4], (1.0,'USDNGN-OTC','call','turbo'))
        order=self.guard.order(123);self.assertEqual(self.broker.sent[0][4],order['expiry_s'])
        self.assertEqual(order['balance_id'],4);self.assertEqual(order['payout'],'0.85')
    def test_unknown_never_retries_after_restart(self):
        for ack in (None,(False,None),(True,None),TimeoutError('late')):
            with self.subTest(ack=str(ack)):
                guard=PracticeExecution(self.broker,Path(self.tmp.name)/('case'+str(len(self.broker.sent))+'.sqlite3'))
                self.broker.ack=ack;guard.submit(self.command)
                count=len(self.broker.sent)
                restarted=PracticeExecution(self.broker,guard.path)
                self.assertFalse(restarted.submit(self.command)[0]);self.assertEqual(len(self.broker.sent),count)
                self.assertEqual(restarted.status()['unknown'],1)
    def test_accepted_blocks_second_instance(self):
        self.guard.submit(self.command)
        other=PracticeExecution(self.broker,self.guard.path)
        self.assertFalse(other.submit(self.command)[0]);self.assertEqual(len(self.broker.sent),1)
    def test_real_wrong_selected_duplicate_or_unknown_balance_rejected(self):
        cases=[[],[{'id':1,'type':1,'currency':'USD','amount':100}],self.broker.balances*2,
               [{'id':4,'type':True,'currency':'USD','amount':100}], [{'id':4,'type':4,'currency':'EUR','amount':100}]]
        for value in cases:
            self.broker.balances=value;self.assertFalse(self.guard.submit(self.command)[0])
        self.broker.balances=[{'id':4,'type':4,'currency':'USD','amount':100}];self.broker.selected=1
        self.assertFalse(self.guard.submit(self.command)[0]);self.assertFalse(self.broker.sent)
    def test_offer_state_payout_schedule_and_exact_symbol(self):
        original=deepcopy(self.broker.offer)
        cases=[{'enabled':False},{'is_suspended':True},{'enabled':1},{'is_suspended':None},{'schedule':[]},
               {'name':'front.USDNGN'}, {'name':'front.EURUSD-OTC'}]
        for changes in cases:
            self.broker.offer={**original,**changes};self.assertFalse(self.guard.submit(self.command)[0])
        self.broker.offer=deepcopy(original);self.broker.offer['option']['profit']['commission']=30
        self.assertFalse(self.guard.submit(self.command)[0]);self.assertFalse(self.broker.sent)
    def test_fixed_budget_and_pause(self):
        for amount,duration in [('2',2),('1',1),('NaN',2)]:
            c=BinaryOrderCommand('USDNGN-OTC',BinaryDirection.PUT,Decimal(amount),duration)
            self.assertFalse(self.guard.submit(c)[0])
        self.guard.enabled=lambda:False
        self.assertFalse(self.guard.submit(self.command)[0]);self.assertFalse(self.broker.sent)
    def test_pending_settlement_cannot_be_guessed(self):
        self.guard.submit(self.command)
        self.assertEqual(self.guard.settle(123),('pending',0.0));self.assertEqual(self.guard.status()['pending'],1)
    def settled_row(self,status='win',cash='1.85'):
        return {'id':[123],'amount':1,'win_amount':cash,'win':status,'active_id':1865,
                'user_balance_id':4,'exp_time':self.guard.order(123)['expiry_s'], 'open_value':100,'close_value':101}
    def test_verified_settlement_and_duplicate_are_idempotent(self):
        self.guard.submit(self.command);self.broker.closed=[self.settled_row()]
        self.assertEqual(self.guard.settle(123),('win',.85));self.assertEqual(self.guard.settle(123),('win',.85))
        self.assertEqual(self.guard.status()['net_pnl'],'0.85');self.assertEqual(self.guard.status()['pending'],0)
    def test_real_history_response_envelope(self):
        self.guard.submit(self.command)
        self.broker.closed=[self.settled_row()]
        original=self.broker.get_optioninfo
        self.broker.get_optioninfo=lambda *a,**kw:{'name':'api_game_getoptions_result','msg':original(*a,**kw)}
        self.assertEqual(self.guard.settle(123),('win',.85))

    def test_contradictory_settlement_blocks(self):
        self.guard.submit(self.command);r=self.settled_row();self.broker.closed=[r,{**r,'win_amount':2}]
        with self.assertRaises(ValueError):self.guard.settle(123)
        self.assertEqual(self.guard.status()['pending'],1)
    def test_wrong_cash_balance_stake_expiry_blocks(self):
        self.guard.submit(self.command);r=self.settled_row()
        for changes in ({'amount':2},{'win_amount':0},{'user_balance_id':1},{'exp_time':r['exp_time']+60}):
            self.broker.closed=[{**r,**changes}]
            with self.assertRaises(ValueError):self.guard.settle(123)
        self.assertEqual(self.guard.status()['pending'],1)
    def test_broker_expiry_ignores_host_clock(self):
        expected=get_expiration_time(NOW/1_000_000_000,2)
        with patch('time.time',return_value=0):self.assertEqual(get_expiration_time(NOW/1_000_000_000,2),expected)
    def test_actual_adapter_uses_guard_once(self):
        adapter=IQOptionBinaryExecutionAdapter(self.broker,ledger_path=str(Path(self.tmp.name)/'adapter.sqlite3'))
        result=asyncio.run(adapter.place_binary_order(self.command));self.assertTrue(result.accepted)
        result=asyncio.run(adapter.place_binary_order(self.command));self.assertFalse(result.accepted)
        self.assertEqual(len(self.broker.sent),1)

    def test_wire_uses_verified_balance_even_if_global_switches(self):
        from types import SimpleNamespace
        from trading_platform.vendor.iqoptionapi.iqoptionapi.ws.chanels.buyv3 import Buyv3_by_raw_expired
        from trading_platform.vendor.iqoptionapi.iqoptionapi.ws.chanels.api_game_getoptions import Get_options
        from trading_platform.vendor.iqoptionapi.iqoptionapi import global_value
        sent=[]
        api=SimpleNamespace(send_websocket_request=lambda *args:sent.append(args))
        with patch.object(global_value,'balance_id',1):
            Buyv3_by_raw_expired(api)(1,1865,'call','turbo',NOW//1_000_000_000+120,'practice-test',user_balance_id=4)
            Get_options(api)(100,user_balance_id=4)
        self.assertEqual(sent[0][1]['body']['user_balance_id'],4)
        self.assertEqual(sent[1][0],'api_game_getoptions')
        self.assertEqual(sent[1][1]['user_balance_id'],4)
    def test_concurrent_instances_reserve_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        other=PracticeExecution(self.broker,self.guard.path)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda g:g.submit(self.command),[self.guard,other]))
        self.assertEqual(sum(r[0] for r in results),1)
        self.assertEqual(len(self.broker.sent),1)
    def test_pause_after_read_prevents_submission(self):
        original=self.broker.get_balances
        calls=[]
        def balance():
            calls.append(1)
            if len(calls)==2:self.guard.enabled=lambda:False
            return original()
        self.broker.get_balances=balance
        self.assertFalse(self.guard.submit(self.command)[0]);self.assertEqual(self.broker.sent,[])

if __name__=='__main__':unittest.main()
