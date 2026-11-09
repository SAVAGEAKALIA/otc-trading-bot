"""Typed practice-only order boundary. No network or account fallback."""
from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, localcontext
import hashlib
import json
import re


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError('invalid_' + name)
    return value


def number(value, name):
    if type(value) not in (int, float, str, Decimal):
        raise ValueError('invalid_' + name)
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('invalid_' + name) from None
    if not parsed.is_finite() or len(parsed.as_tuple().digits) > 34 or abs(parsed.adjusted()) > 100:
        raise ValueError('invalid_' + name)
    return parsed


def asset_name(value):
    if not isinstance(value, str):
        raise ValueError('invalid_asset')
    name = value.removeprefix('front.').upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9/]{1,31}-OTC', name):
        raise ValueError('invalid_asset')
    return name


@dataclass(frozen=True)
class PracticeBalance:
    balance_id: int
    balance_type: int
    currency: str
    amount: Decimal
    received_ns: int

    def validate(self, now_ns):
        if type(self.balance_type) is not int or self.balance_type != 4:
            raise ValueError('practice_balance_required')
        if integer(self.balance_id, 'balance_id') == 0 or self.currency != 'USD':
            raise ValueError('verified_usd_practice_balance_required')
        age = integer(now_ns, 'now_ns') - integer(self.received_ns, 'balance_received_ns')
        if not 0 <= age <= 60_000_000_000 or number(self.amount, 'balance_amount') < 1:
            raise ValueError('practice_balance_stale_or_insufficient')


def select_practice(balances, received_ns):
    if not isinstance(balances, list):
        raise ValueError('unsupported_balance_response')
    matches = [b for b in balances if isinstance(b, dict) and type(b.get('type')) is int and b['type'] == 4]
    if len(matches) != 1:
        raise ValueError('unique_practice_balance_required')
    b = matches[0]
    result = PracticeBalance(integer(b.get('id'), 'balance_id'), 4, b.get('currency'),
                             number(b.get('amount'), 'balance_amount'), integer(received_ns, 'received_ns'))
    result.validate(received_ns)
    return result


@dataclass(frozen=True)
class Offer:
    active_id: int
    asset: str
    enabled: bool
    suspended: bool
    payout: Decimal
    first_expiry_s: int
    step_s: int
    count: int
    schedules: tuple
    received_ns: int


@dataclass(frozen=True)
class Sample:
    value: Decimal
    received_ns: int


def parse_offer(active_id, raw, received_ns):
    if not isinstance(raw, dict):
        raise ValueError('unsupported_offer')
    aid = integer(int(active_id), 'active_id') if isinstance(active_id, str) and active_id.isdecimal() else integer(active_id, 'active_id')
    name = asset_name(raw.get('name'))
    if type(raw.get('enabled')) is not bool or type(raw.get('is_suspended')) is not bool:
        raise ValueError('explicit_offer_state_required')
    option = raw.get('option')
    if not isinstance(option, dict) or option.get('expiration_times') != [60]:
        raise ValueError('unsupported_turbo_expiry_contract')
    commission = number(option.get('profit', {}).get('commission'), 'commission')
    if not 0 <= commission <= 100:
        raise ValueError('invalid_commission')
    first = integer(option.get('start_time'), 'first_expiry')
    step = integer(option.get('exp_time'), 'expiry_step')
    count = integer(option.get('count'), 'expiry_count')
    if step != 60 or not 1 <= count <= 10 or first % 60 or not 1_262_304_000 <= first <= 4_102_444_800:
        raise ValueError('unsupported_turbo_expiry_contract')
    schedules = raw.get('schedule')
    if not isinstance(schedules, list) or not schedules or len(schedules) > 256:
        raise ValueError('explicit_offer_schedule_required')
    spans = []
    for span in schedules:
        if not isinstance(span, list) or len(span) != 2:
            raise ValueError('invalid_offer_schedule')
        start, end = integer(span[0], 'schedule_start'), integer(span[1], 'schedule_end')
        if start >= end:
            raise ValueError('invalid_offer_schedule')
        spans.append((start, end))
    with localcontext(Context(prec=200)):
        payout=1-commission/100
    return Offer(aid, name, raw['enabled'], raw['is_suspended'], payout,
                 first, step, count, tuple(spans), integer(received_ns, 'received_ns'))


def offered_expiry(offer, now_ns, broker_ns):
    if not isinstance(offer, Offer):
        raise ValueError('typed_offer_required')
    integer(offer.active_id, 'active_id')
    asset_name(offer.asset)
    if type(offer.count) is not int or not 1 <= offer.count <= 10 or type(offer.step_s) is not int or offer.step_s != 60:
        raise ValueError('unsupported_turbo_expiry_contract')
    integer(offer.first_expiry_s, 'first_expiry')
    if offer.first_expiry_s % 60 or not isinstance(offer.schedules, tuple) or not offer.schedules:
        raise ValueError('unsupported_turbo_expiry_contract')
    for span in offer.schedules:
        if not isinstance(span,tuple) or len(span)!=2 or integer(span[0],'schedule_start')>=integer(span[1],'schedule_end'):
            raise ValueError('invalid_offer_schedule')
    age = integer(now_ns, 'now_ns') - integer(offer.received_ns, 'offer_received_ns')
    if type(offer.enabled) is not bool or type(offer.suspended) is not bool or not offer.enabled or offer.suspended:
        raise ValueError('offer_not_active')
    if not 0 <= age <= 30_000_000_000 or not Decimal('.80') <= number(offer.payout, 'payout') <= 1:
        raise ValueError('offer_stale_or_low_payout')
    broker_ns = integer(broker_ns, 'broker_ns')
    options = [offer.first_expiry_s + i * offer.step_s for i in range(offer.count)]
    valid = [expiry for expiry in options if 90_000_000_000 <= expiry * 1_000_000_000 - broker_ns <= 150_000_000_000
             and any(start * 1_000_000_000 <= broker_ns < end * 1_000_000_000 and expiry <= end
                     for start, end in offer.schedules)]
    if not valid:
        raise ValueError('no_offered_two_minute_expiry')
    return min(valid, key=lambda expiry: (abs(expiry * 1_000_000_000 - broker_ns - 120_000_000_000), expiry))


def order_payload(balance, offer, direction, expiry_s, request_id, now_ns, broker_ns):
    if not isinstance(balance, PracticeBalance):
        raise ValueError('typed_practice_balance_required')
    balance.validate(now_ns)
    if direction not in ('call', 'put') or not isinstance(request_id, str) or not re.fullmatch(r'practice-[0-9a-f]{32}', request_id):
        raise ValueError('invalid_order_command')
    if type(expiry_s) is not int or expiry_s != offered_expiry(offer, now_ns, broker_ns):
        raise ValueError('order_expiry_not_offered')
    return {'name': 'sendMessage', 'request_id': request_id, 'msg': {
        'name': 'binary-options.open-option', 'version': '1.0', 'body': {
            'price': 1, 'active_id': integer(offer.active_id, 'active_id'), 'expired': expiry_s,
            'direction': direction, 'option_type_id': 3, 'user_balance_id': balance.balance_id}}}


def normalized_settlement(record, order):
    """Require actual broker amount, winning gross cash and exact order identity."""
    if not isinstance(record, dict) or str(record.get('id')) != str(order['broker_order_id']):
        raise ValueError('settlement_order_identity_mismatch')
    status = record.get('win')
    if status not in ('win', 'loose', 'lose', 'loss', 'equal', 'refund', 'void'):
        raise ValueError('settlement_not_final')
    stake = number(record.get('amount'), 'settlement_stake')
    gross = number(record.get('win_amount'), 'settlement_gross_cash')
    if stake != 1 or gross < 0:
        raise ValueError('settlement_stake_or_cash_mismatch')
    if status in ('loose', 'lose', 'loss') and gross != 0:
        raise ValueError('loss_cash_mismatch')
    if status in ('equal', 'refund', 'void') and gross != stake:
        raise ValueError('refund_cash_mismatch')
    if status == 'win' and gross <= stake:
        raise ValueError('win_cash_mismatch')
    for field in ('user_balance_id', 'balance_id'):
        if field in record and record[field] != order['balance_id']:
            raise ValueError('settlement_balance_mismatch')
    if 'active_id' in record and record['active_id'] != order['active_id']:
        raise ValueError('settlement_asset_mismatch')
    expiry = record.get('exp_time', record.get('expiration_time', record.get('expired')))
    if expiry is not None and number(expiry, 'settlement_expiry') not in (Decimal(order['expiry_s']), Decimal(order['expiry_s'] * 1000)):
        raise ValueError('settlement_expiry_mismatch')
    with localcontext(Context(prec=200)):
        pnl=gross-stake
    return {'status': status, 'stake': str(stake), 'gross_return': str(gross),
            'net_pnl': str(pnl), 'unit_return': str(pnl),
            'broker_order_id': str(order['broker_order_id']),
            'strike': record.get('open_value', record.get('value')),
            'terminal_price': record.get('close_value'),
            'expiry_verified': expiry is not None,
            'accepted_contract_fields_complete': expiry is not None and record.get('open_value', record.get('value')) is not None
                and record.get('close_value') is not None,
            'broker_evidence': record, 'broker_evidence_sha256': digest(record),
            'cash_basis': 'broker_win_amount_minus_broker_amount', 'separately_charged_fees_verified': False}
