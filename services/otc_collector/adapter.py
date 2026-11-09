"""Narrow wire parser. Never retains raw payloads, profiles, credentials, or orders."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, DecimalException, ROUND_FLOOR, localcontext
import json
from .protocol import ASSETS, PRODUCT, LIMITS, canonical, digest

MATH = Context(prec=34)
SOURCE_STAMP_SCHEMA = "broker_epoch_floor_ms_v2"
PERSONAL = frozenset({"profile", "authenticated", "ssid", "balances", "balance-changed",
                     "position-changed", "positions", "order", "option", "user-profile-client",
                     "users-availability", "result", "user-settings"})


class InvalidFrame(ValueError):
    """Error messages are fixed codes; no raw input can reach diagnostic logs."""


class WireDecimal(Decimal):
    """Exact JSON numeric value with its original numeric token kept in memory."""

    def __new__(cls, text):
        value = super().__new__(cls, text)
        value.wire_text = text
        return value


def integer(value, code):
    if type(value) is not int or value < 0:
        raise InvalidFrame(code)
    return value


def number(value, code):
    if type(value) not in (int, float, Decimal, WireDecimal):
        raise InvalidFrame(code)
    try:
        parsed = Decimal(str(value))
    except DecimalException as exc:
        raise InvalidFrame(code) from exc
    if not parsed.is_finite() or len(parsed.as_tuple().digits) > 34 or abs(parsed.adjusted()) > 100:
        raise InvalidFrame(code)
    return parsed


def epoch_details(value):
    """Map the broker's numeric epoch exactly; floor only derived millisecond metadata.

    The broker can send seconds, milliseconds, microseconds or nanoseconds with
    fractional milliseconds. Original digits and precision remain in lineage.
    Receiver UTC remains the causal timestamp and is never adjusted here.
    """
    parsed = number(value, "invalid_source_stamp")
    if parsed < 1_000_000_000:
        raise InvalidFrame("invalid_source_stamp")
    if parsed < 100_000_000_000:
        scale, unit = 3, "seconds"
    elif parsed < 100_000_000_000_000:
        scale, unit = 0, "milliseconds"
    elif parsed < 100_000_000_000_000_000:
        scale, unit = -3, "microseconds"
    else:
        scale, unit = -6, "nanoseconds"
    with localcontext(MATH):
        # Multiplication by a power of ten shifts the exponent without losing digits.
        exact_ms = parsed.scaleb(scale)
        if not 1_262_304_000_000 <= exact_ms <= 4_102_444_800_000:
            raise InvalidFrame("invalid_source_stamp")
        stamp_ms = int(exact_ms.to_integral_value(rounding=ROUND_FLOOR))
        fractional_ms = exact_ms - Decimal(stamp_ms)
        exact_ns = parsed.scaleb(scale + 6)
    exponent = parsed.as_tuple().exponent
    if type(exponent) is not int:
        raise InvalidFrame("invalid_source_stamp")
    metadata = {"source_stamp_schema": SOURCE_STAMP_SCHEMA,
                "broker_stamp_text": getattr(value, "wire_text", str(value)),
                "source_stamp_unit": {"seconds": "s", "milliseconds": "ms", "microseconds": "us", "nanoseconds": "ns"}[unit],
                "broker_stamp_unit": unit, "broker_stamp_decimal_exponent": exponent,
                "broker_stamp_resolution_ms": str(Decimal((0, (1,), exponent + scale))),
                "broker_stamp_ms_exact": str(exact_ms), "broker_stamp_fractional_ms": str(fractional_ms),
                "broker_stamp_ns_exact": str(exact_ns),
                "broker_stamp_ms_rounding": "floor"}
    return stamp_ms, metadata


def epoch(value):
    return epoch_details(value)[0]


def asset(value):
    if type(value) is not int or value not in ASSETS:
        raise InvalidFrame("outside_asset_scope")
    return ASSETS[value]


def product(value):
    if value != PRODUCT:
        raise InvalidFrame("wrong_product")
    return value


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidFrame("duplicate_json_field")
        result[key] = value
    return result


@dataclass(frozen=True)
class Receipt:
    session_id: str
    sequence: int
    received_at_ms: int
    monotonic_ns: int
    received_at_ns: int | None = None

    @property
    def frame_id(self):
        return f"{self.session_id}:{self.sequence:012d}"


class Adapter:
    def __init__(self):
        self.sync = None

    def clock_status(self, receipt):
        if self.sync is None:
            return "clock_unsynchronized", None
        broker_ms, received_ms, monotonic_ns = self.sync
        age = (receipt.monotonic_ns - monotonic_ns) // 1_000_000
        offset = broker_ms - received_ms
        if age < 0 or age > LIMITS["clock_sync_max_age_ms"]:
            return "clock_sync_stale", offset
        if abs(offset) > LIMITS["broker_offset_ms"]:
            return "broker_clock_offset", offset
        return "ok", offset

    def parse(self, raw, receipt):
        """Return sanitized receipt envelope, or None for discarded private/unknown frames."""
        try:
            msg = json.loads(raw, parse_float=WireDecimal, object_pairs_hook=_object_pairs,
                             parse_constant=lambda value: (_ for _ in ()).throw(InvalidFrame("nonfinite_json")))
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            if isinstance(exc, InvalidFrame):
                raise
            raise InvalidFrame("invalid_json") from exc
        if not isinstance(msg, dict) or not isinstance(msg.get("name"), str):
            raise InvalidFrame("invalid_envelope")
        name = msg["name"]
        if name in PERSONAL or name not in {"timeSync", "candles-generated", "candle-generated",
                                            "traders-mood-changed", "commission-changed", "api_option_init_all_result"}:
            return None
        body = msg.get("msg")
        if name == "timeSync":
            stamp, stamp_metadata = epoch_details(body)
            self.sync = stamp, receipt.received_at_ms, receipt.monotonic_ns
            status, offset = self.clock_status(receipt)
            return self.envelope(receipt, [], {"code": "clock_sync", "status": status,
                                              "broker_source_ms": stamp, "clock_offset_ms": offset,
                                              **stamp_metadata})
        if not isinstance(body, dict):
            raise InvalidFrame("invalid_body")
        status, offset = self.clock_status(receipt)
        lineage = {"wire_name": name, "received_at_ms": receipt.received_at_ms,
                   "received_at_ns": receipt.received_at_ns,
                   "monotonic_ns": receipt.monotonic_ns, "clock_offset_ms": offset,
                   "clock_status": status, "availability_basis": "callback_receiver_utc"}
        if name in {"candles-generated", "candle-generated"}:
            identity = asset(body.get("active_id"))
            # All candle sizes share these top-level quote values. Never iterate candles.
            if name == "candle-generated" and integer(body.get("size"), "invalid_quote_size") != 1:
                raise InvalidFrame("unsupported_quote_size")
            bid, ask = number(body.get("bid"), "invalid_bid"), number(body.get("ask"), "invalid_ask")
            if bid <= 0 or ask <= 0:
                raise InvalidFrame("negative_quote")
            if ask < bid:
                raise InvalidFrame("crossed_quote")
            stamp, stamp_metadata = epoch_details(body.get("at"))
            with localcontext(MATH):
                mid = (bid + ask) / Decimal(2)
                raw_delta_ns = None if receipt.received_at_ns is None else str(Decimal(receipt.received_at_ns) - Decimal(stamp_metadata["broker_stamp_ns_exact"]))
            meta = {**lineage, **stamp_metadata, "source_event_ms": stamp, "bid": str(bid), "ask": str(ask),
                    "raw_source_receiver_delta_ns": raw_delta_ns,
                    "source_receiver_delta_basis": "uncorrected_broker_vs_receiver_utc_clocks",
                    "product_basis": "explicit_assumed", "quote_semantics": "received_top_level_bid_ask_midpoint"}
            if offset is not None and abs((stamp - offset) - receipt.received_at_ms) > LIMITS["broker_offset_ms"]:
                meta["clock_status"] = "quote_source_age"
            events = [self.event(receipt, identity, "quote", "quote_samples", mid, meta)]
        elif name == "traders-mood-changed":
            identity = asset(body.get("asset_id"))
            for field in ("instrument", "instrument_type"):
                if field in body:
                    product(body[field])
            value = number(body.get("value"), "invalid_mood")
            if not 0 <= value <= 1:
                raise InvalidFrame("invalid_mood")
            meta = {**lineage, "product_basis": "recorded" if "instrument" in body or "instrument_type" in body else "subscription_scope_assumed",
                    "observed_semantics": "broker_call_fraction", "source_event_ms": None}
            events = [self.event(receipt, identity, "mood", "mood_samples", value, meta)]
        elif name == "commission-changed":
            identity = asset(body.get("active_id"))
            product(body.get("instrument_type"))
            commission = body.get("commission")
            if not isinstance(commission, dict) or set(commission) != {"value"}:
                raise InvalidFrame("unknown_commission_shape")
            percentage = number(commission["value"], "invalid_commission")
            if not 0 <= percentage <= 100:
                raise InvalidFrame("invalid_commission")
            with localcontext(MATH):
                payout = 1 - percentage / 100
            meta = {**lineage, "product_basis": "recorded", "source_event_ms": None,
                    "commission_percent": str(percentage), "observed_semantics": "net_profit_ratio_one_minus_commission_percent"}
            events = [self.event(receipt, identity, "payout", "commission-stream", payout, meta)]
        else:
            if body.get("isSuccessful") is not True or not isinstance(body.get("result"), dict):
                raise InvalidFrame("unsupported_offer_snapshot")
            turbo = body["result"].get("turbo")
            if not isinstance(turbo, dict) or not isinstance(turbo.get("actives"), dict):
                raise InvalidFrame("unsupported_offer_snapshot")
            events = []
            for active_id, identity in ASSETS.items():
                offer = turbo["actives"].get(str(active_id))
                if offer is None:
                    continue
                if not isinstance(offer, dict) or offer.get("name") not in {identity, "front." + identity}:
                    raise InvalidFrame("snapshot_asset_conflict")
                if offer.get("enabled") is not True or offer.get("is_suspended") is not False:
                    raise InvalidFrame("unsupported_offer_state")
                try:
                    percentage = number(offer["option"]["profit"]["commission"], "invalid_commission")
                except (KeyError, TypeError) as exc:
                    raise InvalidFrame("unsupported_offer_snapshot") from exc
                if not 0 <= percentage <= 100:
                    raise InvalidFrame("invalid_commission")
                with localcontext(MATH):
                    payout = 1 - percentage / 100
                meta = {**lineage, "product_basis": "recorded_turbo_snapshot", "source_event_ms": None,
                        "commission_percent": str(percentage), "observed_semantics": "net_profit_ratio_one_minus_commission_percent"}
                events.append(self.event(receipt, identity, "payout", "init-snapshot", payout, meta))
            if not events:
                raise InvalidFrame("snapshot_scope_missing")
        return self.envelope(receipt, events)

    @staticmethod
    def event(receipt, identity, kind, source, value, meta):
        observation = {"event_id": f"{receipt.frame_id}:{kind}:{identity}", "broker": "iqoption", "asset": identity,
                       "product": PRODUCT, "source": source, "kind": kind, "available_ms": receipt.received_at_ms,
                       "event_ms": receipt.received_at_ms, "value": str(value), "clock_id": "receiver_utc", "quality": "received"}
        meta["sanitized_sha256"] = digest({"observation": observation, "lineage": meta})
        return {"observation": observation, "lineage": meta}

    @staticmethod
    def envelope(receipt, events, health=None):
        return {"frame_id": receipt.frame_id, "session_id": receipt.session_id, "sequence": receipt.sequence,
                "received_at_ms": receipt.received_at_ms, "monotonic_ns": receipt.monotonic_ns,
                "received_at_ns": receipt.received_at_ns,
                "events": events, "health": health}


def subscriptions():
    operations = []
    for active_id in ASSETS:
        operations.extend([
            {"name": "subscribeMessage", "msg": {"name": "candles-generated", "params": {"routingFilters": {"active_id": str(active_id)}}}},
            {"name": "subscribeMessage", "msg": {"name": "traders-mood-changed", "params": {"routingFilters": {"instrument": PRODUCT, "asset_id": active_id}}}},
        ])
    operations.append({"name": "subscribeMessage", "msg": {"name": "commission-changed", "version": "1.0", "params": {"routingFilters": {"instrument_type": PRODUCT}}}})
    return operations


SNAPSHOT = {"name": "api_option_init_all", "msg": ""}


def allowed_outgoing(operation):
    if operation in subscriptions() or operation == SNAPSHOT:
        return True
    return (isinstance(operation, dict) and set(operation) == {"name", "msg"}
            and operation["name"] == "ssid" and isinstance(operation["msg"], str)
            and bool(operation["msg"]) and len(operation["msg"]) <= 4096)
