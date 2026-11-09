"""Durable practice admission for the restored bot's existing execution route."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from decimal import Decimal

from .practice_contract import (
    canonical, normalized_settlement, number, offered_expiry, parse_offer,
    select_practice,
)


class PracticeExecution:
    def __init__(self, api, path, enabled=lambda: True):
        self.api = api
        self.path = str(path)
        self.enabled = enabled
        self.lock = threading.RLock()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS practice_orders (
                request_id TEXT PRIMARY KEY, created_ns INTEGER NOT NULL,
                state TEXT NOT NULL, asset TEXT NOT NULL, active_id INTEGER NOT NULL,
                balance_id INTEGER NOT NULL, expiry_s INTEGER NOT NULL,
                payout TEXT NOT NULL, broker_order_id TEXT UNIQUE, evidence TEXT NOT NULL,
                net_pnl TEXT, settlement TEXT)''')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_position ON practice_orders ((1)) WHERE state IN ('SUBMITTING','ACCEPTED','UNKNOWN')")
        os.chmod(self.path, 0o600)

    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def status(self):
        with self.db() as db:
            rows = db.execute('SELECT state,net_pnl FROM practice_orders').fetchall()
        pending = sum(r['state'] in ('SUBMITTING', 'ACCEPTED', 'UNKNOWN') for r in rows)
        pnl = sum((Decimal(r['net_pnl']) for r in rows if r['net_pnl'] is not None), Decimal(0))
        return {'orders': len(rows), 'pending': pending, 'net_pnl': str(pnl),
                'unknown': sum(r['state'] in ('SUBMITTING', 'UNKNOWN') for r in rows)}

    def broker_ns(self):
        stamp = number(self.api.get_server_timestamp(), 'server_timestamp')
        now = time.time_ns()
        value = int(stamp * 1_000_000_000)
        if abs(value - now) > 5_000_000_000:
            raise ValueError('broker_clock_stale_or_skewed')
        return value

    def balance(self):
        raw = self.api.get_balances()
        result = select_practice(raw.get('msg') if isinstance(raw, dict) else None, time.time_ns())
        if self.api.get_balance_id() != result.balance_id:
            raise ValueError('selected_balance_is_not_practice')
        return result

    def offers(self):
        started = time.monotonic()
        raw = self.api.get_all_init()
        if time.monotonic() - started > 5 or not isinstance(raw, dict) or raw.get('isSuccessful') is not True:
            raise ValueError('fresh_offer_snapshot_required')
        received = time.time_ns()
        result = {}
        for aid, item in raw.get('result', {}).get('turbo', {}).get('actives', {}).items():
            try:
                offer = parse_offer(aid, item, received)
                if offer.asset in result:
                    raise RuntimeError('conflicting_offer_identity')
                result[offer.asset] = offer
            except ValueError:
                continue
        return result

    def active_symbols(self):
        with self.lock:
            broker = self.broker_ns()
            offers = self.offers()
            names = []
            for name, offer in offers.items():
                try:
                    offered_expiry(offer, time.time_ns(), broker)
                    names.append(name)
                except ValueError:
                    pass
            return sorted(names)

    def submit(self, command):
        """Reserve before sending once. Uncertain responses retain the position."""
        with self.lock:
            if not self.enabled():
                return False, 'Trading paused or dry run'
            if command.amount != Decimal('1') or command.duration_minutes != 2:
                return False, 'Practice deployment requires fixed USD1 and 2m duration'
            if self.status()['pending']:
                return False, 'Pending practice order requires reconciliation'
            try:
                balance = self.balance()
                offers = self.offers()
                offer = offers.get(command.asset.upper())
                if offer is None:
                    raise ValueError('exact_otc_offer_required')
                broker = self.broker_ns()
                expiry = offered_expiry(offer, time.time_ns(), broker)
                # Recheck the selected balance and pause after blocking reads.
                balance = self.balance()
                if not self.enabled():
                    return False, 'Trading paused or dry run'
                broker = self.broker_ns()
                if expiry != offered_expiry(offer, time.time_ns(), broker):
                    raise ValueError('expiry_changed_before_submission')
            except (ValueError, RuntimeError, TimeoutError) as exc:
                return False, str(exc)
            request = 'practice-' + uuid.uuid4().hex
            now = time.time_ns()
            evidence = {'strategy': command.metadata or {}, 'broker_ns': broker,
                        'offer_received_ns': offer.received_ns, 'stake': '1',
                        'account': 'PRACTICE', 'balance_type': 4, 'currency': 'USD'}
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                today = (now // 86_400_000_000_000) * 86_400_000_000_000
                daily = db.execute('SELECT net_pnl FROM practice_orders WHERE created_ns>=?', (today,)).fetchall()
                daily_pnl = sum((Decimal(r[0]) for r in daily if r[0] is not None), Decimal(0))
                if len(daily) >= 100 or daily_pnl <= -20:
                    return False, 'Daily practice research budget reached'
                try:
                    db.execute('INSERT INTO practice_orders VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL)',
                               (request, now, 'SUBMITTING', offer.asset, offer.active_id,
                                balance.balance_id, expiry, str(offer.payout), None, canonical(evidence)))
                except sqlite3.IntegrityError:
                    return False, 'Another practice order is pending'
            # Use the actual offer expiry; no aliases or submission retries.
            from trading_platform.vendor.iqoptionapi.iqoptionapi import constants
            constants.ACTIVES[offer.asset] = offer.active_id
            try:
                result = self.api.buy_by_raw_expirations(1.0, offer.asset, command.direction.value, 'turbo', expiry, request_id=request, user_balance_id=balance.balance_id)
            except Exception:
                result = None
            accepted = isinstance(result, tuple) and len(result) == 2 and result[0] is True
            oid = result[1] if isinstance(result, tuple) and len(result) == 2 else None
            valid_id = (type(oid) is int and oid > 0) or (isinstance(oid, str) and oid.isdecimal() and int(oid) > 0)
            rejected = isinstance(result, tuple) and len(result) == 2 and result[0] is False and isinstance(oid, str) and bool(oid) and not oid.isdecimal()
            state = 'ACCEPTED' if accepted and valid_id else ('REJECTED' if rejected else 'UNKNOWN')
            evidence['ack'] = {'state': state, 'broker_order_id': str(oid) if valid_id else None}
            with self.db() as db:
                db.execute('UPDATE practice_orders SET state=?,broker_order_id=?,evidence=? WHERE request_id=?',
                           (state, str(oid) if state == 'ACCEPTED' else None, canonical(evidence), request))
            print(f'PRACTICE_ORDER state={state} asset={offer.asset} expiry={expiry} request={request}', flush=True)
            return (True, oid) if state == 'ACCEPTED' else (False, 'Broker rejected' if state == 'REJECTED' else 'UNKNOWN: trading halted pending broker reconciliation')

    def pending_orders(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM practice_orders WHERE state='ACCEPTED'")]

    def order(self, order_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM practice_orders WHERE broker_order_id=?', (str(order_id),)).fetchone()
        return dict(row) if row else None

    def settle(self, order_id):
        with self.lock:
            order = self.order(order_id)
            if order is None:
                return 'pending', 0.0
            if order['state'] == 'SETTLED':
                saved = json.loads(order['settlement'])
                return self._result(saved)
            balance = self.balance()
            if balance.balance_id != order['balance_id']:
                raise ValueError('settlement_practice_identity_mismatch')
            response = self.api.get_optioninfo(100, user_balance_id=order["balance_id"])
            response = response.get('msg', response) if isinstance(response, dict) else response
            rows = response.get('result', {}).get('closed_options', []) if isinstance(response, dict) and response.get('isSuccessful') is True else []
            matches = []
            for row in rows:
                candidate = dict(row)
                rid = candidate.get('id')
                if isinstance(rid, list) and len(rid) == 1:
                    candidate['id'] = rid[0]
                if str(candidate.get('id')) == str(order_id):
                    matches.append(candidate)
            if not matches:
                return 'pending', 0.0
            if len({canonical(r) for r in matches}) != 1:
                raise ValueError('conflicting_settlement_evidence')
            settled = normalized_settlement(matches[0], order)
            with self.db() as db:
                db.execute("UPDATE practice_orders SET state='SETTLED',net_pnl=?,settlement=? WHERE broker_order_id=?",
                           (settled['net_pnl'], canonical(settled), str(order_id)))
            print(f'PRACTICE_SETTLEMENT order={order_id} pnl={settled["net_pnl"]}', flush=True)
            return self._result(settled)

    @staticmethod
    def _result(settled):
        pnl = Decimal(settled['net_pnl'])
        return ('win' if pnl > 0 else 'lose' if pnl < 0 else 'tie', float(pnl))
