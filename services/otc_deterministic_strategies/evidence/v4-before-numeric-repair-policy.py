"""Frozen legacy thresholds, using only a closed causal candle prefix."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from .contracts import (ASSETS, POLICIES, Candle, InvalidInput, Offer, Quote,
                        Signal, integer, number, receiver_age_ms, validate_universe)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def clock_valid(received_ns, broker_at_receipt_ms, status):
    integer(received_ns, 'received_ns')
    integer(broker_at_receipt_ms, 'broker_at_receipt_ms')
    return status == 'ok' and abs(broker_at_receipt_ms * 1000000 - received_ns) <= 15000000000


def closed_prefix(candles, asset, decision_ns, broker_now_ns):
    """Validate causal finalized identities before selecting latest closed versions."""
    selected = {}
    identities = {}
    for item in candles:
        if not isinstance(item, Candle):
            raise InvalidInput('candle must implement Candle v1')
        integer(item.received_ns, 'candle.received_ns')
        if item.received_ns > decision_ns or item.asset != asset:
            continue
        integer(item.start_ms, 'candle.start_ms')
        integer(item.duration_ms, 'candle.duration_ms')
        if type(item.finalized) is not bool:
            raise InvalidInput('finalized must be boolean')
        if not item.finalized:
            continue
        identity = (item.start_ms, item.received_ns)
        prior_identity = identities.get(identity)
        if prior_identity is not None and prior_identity != item:
            raise InvalidInput('conflicting candle version at same receipt instant')
        identities[identity] = item
        if item.duration_ms != 120000:
            continue
        if not clock_valid(item.received_ns, item.broker_at_receipt_ms, item.clock_status):
            continue
        if item.start_ms % 120000 or item.broker_at_receipt_ms < item.start_ms + item.duration_ms:
            continue
        if (item.start_ms + item.duration_ms) * 1000000 > broker_now_ns:
            continue
        for name in ('open', 'high', 'low', 'close'):
            value = number(getattr(item, name), 'candle.' + name)
            if value <= 0:
                raise InvalidInput('nonpositive candle price')
        if not item.low <= min(item.open, item.close) <= max(item.open, item.close) <= item.high:
            raise InvalidInput('contradictory candle OHLC')
        prior = selected.get(item.start_ms)
        if prior is None or item.received_ns > prior.received_ns:
            selected[item.start_ms] = item
    result = sorted(selected.values(), key=lambda item: item.start_ms)[-29:]
    if len(result) < 29:
        return (), 'insufficient_causal_closed_candles'
    if any(right.start_ms - left.start_ms != 120000 for left, right in zip(result, result[1:])):
        return (), 'closed_candle_gap'
    if broker_now_ns - (result[-1].start_ms + 120000) * 1000000 > 120000000000:
        return (), 'stale_closed_candle'
    return tuple(result), None


def legacy_rsi(closes, period=14):
    """Preserve the source tag's exact seeding/smoothing, including overlap."""
    if len(closes) < period + 1:
        raise InvalidInput('insufficient RSI prefix')
    gains, losses = [], []
    for previous, current in zip(closes, closes[1:]):
        difference = current - previous
        gains.append(max(difference, 0.0))
        losses.append(max(-difference, 0.0))
    average_gain = sum(gains[-(period + 1):-1]) / period if len(gains) >= period + 1 else sum(gains[-period:]) / period
    average_loss = sum(losses[-(period + 1):-1]) / period if len(losses) >= period + 1 else sum(losses[-period:]) / period
    for gain, loss in zip(gains[-period:], losses[-period:]):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss == 0.0:
        return 100.0 if average_gain > 0.0 else 50.0
    ratio = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + ratio)


def legacy_stochastic(candles, period=14):
    high = max(item.high for item in candles[-period:])
    low = min(item.low for item in candles[-period:])
    return 50.0 if high == low else (candles[-1].close - low) / (high - low) * 100.0


def legacy_bb_position(closes):
    window = closes[-20:]
    middle = sum(window) / 20
    variance = sum((item - middle) ** 2 for item in window) / 20
    deviation = math.sqrt(variance)
    lower, upper = middle - 2 * deviation, middle + 2 * deviation
    return 0.5 if lower == upper else (closes[-1] - lower) / (upper - lower)


def legacy_adx(candles, period=14):
    tr_values, plus_values, minus_values = [], [], []
    for previous, current in zip(candles, candles[1:]):
        high_diff = current.high - previous.high
        low_diff = previous.low - current.low
        plus_values.append(high_diff if high_diff > low_diff and high_diff > 0 else 0.0)
        minus_values.append(low_diff if low_diff > high_diff and low_diff > 0 else 0.0)
        tr_values.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    atr = sum(tr_values[:period])
    plus = sum(plus_values[:period])
    minus = sum(minus_values[:period])
    dx = []
    for index in range(period, len(tr_values)):
        atr = atr - atr / period + tr_values[index]
        plus = plus - plus / period + plus_values[index]
        minus = minus - minus / period + minus_values[index]
        if atr == 0:
            continue
        plus_di, minus_di = plus / atr * 100.0, minus / atr * 100.0
        total = plus_di + minus_di
        dx.append(0.0 if total == 0 else abs(plus_di - minus_di) / total * 100.0)
    if not dx:
        return 0.0
    adx = sum(dx[:period]) / min(period, len(dx))
    for value in dx[period:]:
        adx = (adx * (period - 1) + value) / period
    return max(0.0, min(100.0, adx))


def mhi_rule(candles):
    cluster = candles[-3:]
    up = down = doji = 0
    body_total = 0.0
    for item in cluster:
        size = item.high - item.low
        ratio = abs(item.close - item.open) / size if size > 0 else 0.0
        body_total += ratio
        if size <= 0 or ratio <= 0.05:
            doji += 1
        elif item.close > item.open:
            up += 1
        else:
            down += 1
    if up == down:
        return None, 'mhi_color_tie', None
    direction = 'put' if up > down else 'call'
    rsi = number(legacy_rsi([item.close for item in candles]), 'calculated RSI')
    if not 0 <= rsi <= 100:
        raise InvalidInput('calculated RSI outside indicator range')
    if direction == 'call':
        if rsi > 65:
            return None, 'mhi_rsi_veto', None
        bonus = 12.0 if rsi < 32 else 5.0 if rsi < 45 else -15.0
    else:
        if rsi < 35:
            return None, 'mhi_rsi_veto', None
        bonus = 12.0 if rsi > 68 else 5.0 if rsi > 55 else -15.0
    average_body = body_total / 3
    body_bonus = 15.0 if average_body >= 0.6 else 10.0 if average_body >= 0.4 else 5.0 if average_body >= 0.2 else 0.0
    if doji > 1:
        body_bonus = max(0.0, body_bonus - 5.0)
    dominance = round(abs(up - down) / 3 * 20.0, 1)
    score = 45.0 + dominance + body_bonus + bonus
    return (direction, 'mhi_signal', score) if score >= 65.0 else (None, 'mhi_score_below65', score)


def exhaustion_rule(candles):
    closes = [item.close for item in candles]
    rsi = number(legacy_rsi(closes), 'calculated RSI')
    if not 30 <= rsi <= 70:
        return None, 'exhaustion_rsi_outside_calm_band', None
    bb = number(legacy_bb_position(closes), 'calculated BB position')
    direction = 'call' if bb < 0.10 else 'put' if bb > 0.90 else None
    if direction is None:
        return None, 'exhaustion_not_at_band_extreme', None
    stochastic = number(legacy_stochastic(candles), 'calculated stochastic')
    if (direction == 'call' and stochastic > 50) or (direction == 'put' and stochastic < 50):
        return None, 'exhaustion_stochastic_veto', None
    current = candles[-1]
    size = current.high - current.low
    if size < 1e-8:
        return None, 'exhaustion_degenerate_range', None
    if abs(current.close - current.open) / size > 0.60:
        return None, 'exhaustion_body_too_strong', None
    adx = number(legacy_adx(candles), 'calculated ADX')
    if adx > 40:
        return None, 'exhaustion_adx_above40', None
    return direction, 'exhaustion_signal', None


def decide(policy, asset, decision_ns, offer, quote, candles, *, allowed_assets=ASSETS):
    integer(decision_ns, 'decision_ns')
    validate_universe(allowed_assets)
    if policy not in POLICIES or asset not in allowed_assets:
        raise InvalidInput('unsupported policy/asset')
    def result(direction, reason, evidence=None, expiry=None, score=None):
        return Signal('otc_deterministic_signal_v1', policy, asset, decision_ns, direction,
                      reason, evidence, expiry, score)
    if not isinstance(offer, Offer) or not isinstance(quote, Quote):
        return result(None, 'missing_typed_offer_or_quote')
    if offer.asset != asset or quote.asset != asset or offer.product != 'turbo-option':
        return result(None, 'offer_or_quote_scope_mismatch')
    if type(offer.active) is not bool or offer.active is not True or offer.status != 'supported':
        return result(None, 'offer_unavailable')
    if not clock_valid(quote.received_ns, quote.broker_at_receipt_ms, quote.clock_status):
        return result(None, 'quote_clock_invalid')
    if not clock_valid(offer.received_ns, offer.broker_at_receipt_ms, offer.clock_status):
        return result(None, 'offer_clock_invalid')
    if offer.received_ns > decision_ns or quote.received_ns > decision_ns:
        return result(None, 'future_offer_or_quote')
    quote_age = receiver_age_ms(decision_ns, quote.received_ns)
    offer_age = receiver_age_ms(decision_ns, offer.received_ns)
    if quote_age > 5000 or offer_age > 600000:
        return result(None, 'stale_offer_or_quote')
    payout = number(offer.payout, 'payout')
    if not 0.80 <= payout <= 2.0:
        return result(None, 'payout_below_floor_or_invalid')
    if number(quote.price, 'quote.price') <= 0:
        return result(None, 'quote_price_invalid')
    integer(offer.expiry_ms, 'offer.expiry_ms')
    integer(offer.purchase_deadline_ms, 'offer.purchase_deadline_ms')
    broker_now_ns = quote.broker_at_receipt_ms * 1000000 + decision_ns - quote.received_ns
    purchase_deadline_ns = offer.purchase_deadline_ms * 1000000
    expiry_ns = offer.expiry_ms * 1000000
    if not broker_now_ns < purchase_deadline_ns < expiry_ns:
        return result(None, 'offer_purchase_cutoff_reached')
    holding_ns = expiry_ns - broker_now_ns
    if not 90000000000 <= holding_ns <= 150000000000:
        return result(None, 'offer_not_two_minute_request')
    prefix, error = closed_prefix(candles, asset, decision_ns, broker_now_ns)
    if error:
        return result(None, error)
    evidence = digest({'offer': asdict(offer), 'quote': asdict(quote),
                       'closed_candles': [asdict(item) for item in prefix]})
    direction, reason, score = mhi_rule(prefix) if policy == POLICIES[0] else exhaustion_rule(prefix)
    return result(direction, reason, evidence, offer.expiry_ms, score)
