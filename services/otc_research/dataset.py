"""Causal, receipt-indexed quote-proxy dataset. Standard library only.

The output describes research prices, never accepted contracts or account cash.
See README.md for clock, source, deadline, and decimal policies.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from decimal import Context, Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
import json
import re
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """An input cannot safely be interpreted under this boundary."""


KINDS = ("quote", "mood", "payout")
DECIMAL_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
OBS_REQUIRED = frozenset(("event_id", "broker", "asset", "product", "source", "kind", "available_ms", "event_ms", "value", "clock_id"))
OPP_REQUIRED = frozenset(("opportunity_id", "broker", "asset", "product", "clock_id", "decision_ms", "expiry_ms", "latest_entry_ms", "expiry_basis", "acceptance_delay_ms", "evidence_class"))
CONFIG_FIELDS = frozenset(("source_priority", "max_age_ms", "max_entry_wait_ms", "max_settlement_wait_ms", "lookback_ms", "tie_rule"))
ARITHMETIC = Context(prec=34, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999)


def _fields(raw: Any, required: frozenset, optional: frozenset, what: str) -> None:
    if not isinstance(raw, dict) or set(raw) - required - optional or required - set(raw):
        raise ContractError(f"{what}: missing or unknown fields")


def _str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractError(f"{what}: expected nonempty string without surrounding whitespace")
    return value


def _int(value: Any, what: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ContractError(f"{what}: expected integer >= {minimum}")
    return value


def _number(value: Any, what: str) -> Decimal:
    if not isinstance(value, str) or not DECIMAL_PATTERN.fullmatch(value):
        raise ContractError(f"{what}: expected finite decimal string")
    try:
        parsed = Decimal(value)
    except DecimalException as exc:
        raise ContractError(f"{what}: invalid decimal") from exc
    if not parsed.is_finite():
        raise ContractError(f"{what}: nonfinite decimal")
    return parsed


def _text(value: Decimal | None) -> str | None:
    # No binary float conversion and no normalization under ambient precision.
    return None if value is None else str(value)


@dataclass(frozen=True)
class Config:
    priorities: dict[str, tuple[str, ...]]
    max_age: dict[str, int]
    entry_wait: int
    settlement_wait: int
    lookback: int
    tie_rule: str
    terminal_policy: str

    @classmethod
    def parse(cls, raw: Any) -> "Config":
        _fields(raw, CONFIG_FIELDS, frozenset(("terminal_policy",)), "config")
        priorities, ages = raw["source_priority"], raw["max_age_ms"]
        if not isinstance(priorities, dict) or set(priorities) != set(KINDS):
            raise ContractError("source_priority: all and only quote/mood/payout required")
        if not isinstance(ages, dict) or set(ages) != set(KINDS):
            raise ContractError("max_age_ms: all and only quote/mood/payout required")
        parsed_priority = {}
        for kind in KINDS:
            names = priorities[kind]
            if not isinstance(names, list):
                raise ContractError(f"source_priority.{kind}: expected list")
            parsed_names = tuple(_str(name, "source name") for name in names)
            if len(set(parsed_names)) != len(parsed_names):
                raise ContractError(f"source_priority.{kind}: duplicate source")
            parsed_priority[kind] = parsed_names
        if raw["tie_rule"] not in ("full_refund", "loss"):
            raise ContractError("tie_rule: explicit full_refund or loss required")
        terminal_policy = raw.get("terminal_policy", "exact_source")
        if terminal_policy not in ("exact_source", "last_received_before"):
            raise ContractError("terminal_policy: unknown policy")
        return cls(parsed_priority, {k: _int(ages[k], f"max_age_ms.{k}", 1) for k in KINDS},
                   _int(raw["max_entry_wait_ms"], "max_entry_wait_ms"),
                   _int(raw["max_settlement_wait_ms"], "max_settlement_wait_ms"),
                   _int(raw["lookback_ms"], "lookback_ms", 1), raw["tie_rule"], terminal_policy)


@dataclass(frozen=True)
class Observation:
    event_id: str
    broker: str
    asset: str
    product: str
    source: str
    kind: str
    available_ms: int | None
    event_ms: int
    value: Decimal
    clock_id: str
    quality: str

    @property
    def scope(self) -> tuple[str, str, str]:
        return self.broker, self.product, self.clock_id

    @property
    def stream(self) -> tuple[str, str, str, str, str, str]:
        return (*self.scope, self.asset, self.kind, self.source)

    @classmethod
    def parse(cls, raw: Any) -> "Observation":
        _fields(raw, OBS_REQUIRED, frozenset(("quality",)), "observation")
        values = {key: _str(raw[key], key) for key in ("event_id", "broker", "asset", "product", "source", "kind", "clock_id")}
        if values["kind"] not in KINDS:
            raise ContractError("observation: unknown kind")
        event = _int(raw["event_ms"], "event_ms")
        arrival = None if raw["available_ms"] is None else _int(raw["available_ms"], "available_ms")
        quality = raw.get("quality", "received")
        if quality not in ("received", "bucket_only"):
            raise ContractError("observation: unknown quality")
        value = _number(raw["value"], "observation.value")
        if values["kind"] == "quote" and value <= 0:
            raise ContractError("quote: price must be positive")
        if values["kind"] == "mood" and not 0 <= value <= 1:
            raise ContractError("mood: fraction must be in [0, 1]")
        if values["kind"] == "payout" and not 0 <= value <= 2:
            raise ContractError("payout: net ratio must be in [0, 2]")
        if arrival is not None and arrival < event:
            raise ContractError("observation: receipt precedes source event in normalized clock")
        return cls(**values, available_ms=arrival, event_ms=event, value=value, quality=quality)


@dataclass(frozen=True)
class Opportunity:
    opportunity_id: str
    broker: str
    asset: str
    product: str
    clock_id: str
    decision_ms: int
    expiry_ms: int
    latest_entry_ms: int
    expiry_basis: str
    acceptance_delay_ms: int
    evidence_class: str
    direction: str | None

    @property
    def scope(self) -> tuple[str, str, str]:
        return self.broker, self.product, self.clock_id

    @classmethod
    def parse(cls, raw: Any) -> "Opportunity":
        _fields(raw, OPP_REQUIRED, frozenset(("direction",)), "opportunity")
        values = {key: _str(raw[key], key) for key in ("opportunity_id", "broker", "asset", "product", "clock_id")}
        times = {key: _int(raw[key], key) for key in ("decision_ms", "expiry_ms", "latest_entry_ms", "acceptance_delay_ms")}
        if times["expiry_ms"] <= times["decision_ms"]:
            raise ContractError("opportunity: expiry must be after decision")
        if not times["decision_ms"] <= times["latest_entry_ms"] < times["expiry_ms"]:
            raise ContractError("opportunity: entry cutoff must be at/after decision and before expiry")
        if raw["expiry_basis"] not in ("broker_offer", "hypothetical"):
            raise ContractError("opportunity: unknown expiry_basis")
        if raw["evidence_class"] != "received_price_proxy":
            raise ContractError("opportunity: only received_price_proxy is supported")
        direction = raw.get("direction")
        if direction not in (None, "call", "put"):
            raise ContractError("opportunity: invalid direction")
        return cls(**values, **times, expiry_basis=raw["expiry_basis"], evidence_class=raw["evidence_class"], direction=direction)


class Stream:
    """Stable availability order; ties use source event time, then identity."""
    def __init__(self, events: list[Observation]):
        self.events = tuple(sorted(events, key=lambda e: (e.available_ms, e.event_ms, e.event_id)))
        self.receipts = tuple(e.available_ms for e in self.events)

    def asof(self, cutoff: int, max_age: int, kind: str) -> Observation | None:
        position = bisect_right(self.receipts, cutoff)
        # Arrival can be out of event-time order. Never assume an old arrival's
        # source timestamp is fresh, or stop before a previous fresh arrival.
        oldest_receipt = bisect_left(self.receipts, cutoff - max_age)
        for cursor in range(position - 1, oldest_receipt - 1, -1):
            event = self.events[cursor]
            if cutoff - max_age <= event.event_ms <= cutoff:
                return event
        return None

    def window(self, earliest: int, latest: int):
        return self.events[bisect_left(self.receipts, earliest):bisect_right(self.receipts, latest)]


class Index:
    def __init__(self, observations: list[dict], config: Config):
        self.config = config
        streams = defaultdict(list)
        identities, conflicts, mood_debuts = {}, {}, {}
        self.audit = {"input": len(observations), "unique": 0, "duplicate": 0, "indexed": 0,
                      "ignored_unknown_source": 0, "ignored_missing_receipt": 0, "ignored_bucket_only": 0}
        for raw in observations:
            event = Observation.parse(raw)
            if (config.terminal_policy == "last_received_before" and event.clock_id == "receiver_utc"
                    and event.available_ms is not None and event.event_ms != event.available_ms):
                raise ContractError("receiver_utc experiment requires event_ms == available_ms")
            fingerprint = json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if event.event_id in identities:
                if identities[event.event_id] != fingerprint:
                    raise ContractError(f"event_id collision: {event.event_id}")
                self.audit["duplicate"] += 1
                continue
            identities[event.event_id] = fingerprint
            self.audit["unique"] += 1
            conflict_key = (*event.stream, event.event_ms)
            if conflict_key in conflicts and conflicts[conflict_key] != event.value:
                raise ContractError(f"same-source event-time value conflict: {event.event_id}")
            conflicts[conflict_key] = event.value
            if event.source not in config.priorities[event.kind]:
                self.audit["ignored_unknown_source"] += 1
            elif event.available_ms is None:
                self.audit["ignored_missing_receipt"] += 1
            elif event.quality != "received":
                self.audit["ignored_bucket_only"] += 1
            else:
                streams[event.stream].append(event)
                self.audit["indexed"] += 1
                if event.kind == "mood":
                    key = (event.scope, event.asset)
                    mood_debuts[key] = min(event.available_ms, mood_debuts.get(key, event.available_ms))
        self.streams = {key: Stream(events) for key, events in streams.items()}
        self.mood_universe = defaultdict(list)
        for (scope, asset), receipt in mood_debuts.items():
            self.mood_universe[scope].append((receipt, asset))
        for scope in self.mood_universe:
            self.mood_universe[scope].sort()
        self.mood_universe_receipts = {scope: [receipt for receipt, _ in values] for scope, values in self.mood_universe.items()}

    def asof(self, scope: tuple, asset: str, kind: str, cutoff: int) -> Observation | None:
        for source in self.config.priorities[kind]:
            stream = self.streams.get((*scope, asset, kind, source))
            if stream:
                event = stream.asof(cutoff, self.config.max_age[kind], kind)
                if event is not None:
                    # A current nonpositive payout is an authoritative stop,
                    # never permission to resurrect an earlier profitable offer.
                    return None if kind == "payout" and event.value <= 0 else event
        return None

    def market_moods(self, opportunity: Opportunity) -> list[Observation]:
        scope, cutoff = opportunity.scope, opportunity.decision_ms
        universe = self.mood_universe.get(scope, [])
        end = bisect_right(self.mood_universe_receipts.get(scope, []), cutoff)
        # Membership is causal and mood-derived, independent of quotes/labels.
        known_assets = sorted(asset for _, asset in universe[:end])
        return [event for asset in known_assets if (event := self.asof(scope, asset, "mood", cutoff)) is not None]

    def entry(self, opportunity: Opportunity) -> Observation | None:
        earliest = opportunity.decision_ms + opportunity.acceptance_delay_ms
        latest = min(earliest + self.config.entry_wait, opportunity.latest_entry_ms, opportunity.expiry_ms - 1)
        candidates = []
        for rank, source in enumerate(self.config.priorities["quote"]):
            stream = self.streams.get((*opportunity.scope, opportunity.asset, "quote", source))
            if stream:
                eligible = [event for event in stream.window(earliest, latest)
                            if event.event_ms >= earliest
                            and event.available_ms - event.event_ms <= self.config.max_age["quote"]]
                if eligible:
                    first_receipt = min(event.available_ms for event in eligible)
                    batch = [event for event in eligible if event.available_ms == first_receipt]
                    # The complete receipt batch is visible atomically. Its newest
                    # source tick is the current quote at modeled acceptance.
                    event = max(batch, key=lambda item: (item.event_ms, item.event_id))
                    candidates.append((event.available_ms, rank, -event.event_ms, event.event_id, event))
        return min(candidates)[-1] if candidates else None

    def terminal(self, opportunity: Opportunity) -> Observation | None:
        expiry = opportunity.expiry_ms
        if self.config.terminal_policy == "last_received_before":
            return self.asof(opportunity.scope, opportunity.asset, "quote", expiry)
        for source in self.config.priorities["quote"]:
            stream = self.streams.get((*opportunity.scope, opportunity.asset, "quote", source))
            if stream:
                for event in stream.window(expiry, expiry + self.config.settlement_wait):
                    if event.event_ms == expiry:
                        return event
        return None


def _decision_row(index: Index, opportunity: Opportunity) -> dict:
    decision = opportunity.decision_ms
    quote = index.asof(opportunity.scope, opportunity.asset, "quote", decision)
    payout = index.asof(opportunity.scope, opportunity.asset, "payout", decision)
    reasons = []
    if quote is None:
        reasons.append("missing_fresh_decision_quote")
    if payout is None:
        reasons.append("missing_positive_decision_payout")
    modeled_entry = decision + opportunity.acceptance_delay_ms
    if modeled_entry > opportunity.latest_entry_ms or modeled_entry >= opportunity.expiry_ms:
        reasons.append("no_entry_window_at_decision")
    row = {"opportunity_id": opportunity.opportunity_id, "decision_ms": decision,
           "expiry_ms": opportunity.expiry_ms, "expiry_basis": opportunity.expiry_basis,
           "terminal_policy": index.config.terminal_policy,
           "evidence_class": "received_price_proxy", "return_basis": "quote_proxy",
           "executable_edge_eligible": False, "features": None,
           "status": "ineligible" if reasons else "unresolved", "reason_codes": reasons,
           "label": None, "modeled_strike": None, "terminal_quote": None, "unit_pnl": None,
           "training_eligible": False,
           "lineage": {"decision_quote": quote.event_id if quote else None,
                       "payout": payout.event_id if payout else None, "lookback_quote": None,
                       "own_mood": None, "market_mood": [], "modeled_strike": None, "terminal_quote": None}}
    if reasons:
        return row
    baseline = index.asof(opportunity.scope, opportunity.asset, "quote", decision - index.config.lookback)
    mood = index.asof(opportunity.scope, opportunity.asset, "mood", decision)
    market = index.market_moods(opportunity)
    with localcontext(ARITHMETIC):
        relative_return = quote.value / baseline.value - 1 if baseline else None
        market_mean = sum((event.value for event in market), Decimal(0)) / len(market) if market else None
    row["features"] = {"last_quote": _text(quote.value), "return_lookback": _text(relative_return),
                       "own_mood": _text(mood.value) if mood else None,
                       "market_mood": _text(market_mean), "payout": _text(payout.value),
                       "quote_age_ms": decision - quote.event_ms,
                       "mood_age_ms": decision - mood.event_ms if mood else None,
                       "payout_age_ms": decision - payout.event_ms,
                       "own_mood_missing": mood is None, "market_mood_missing": not market,
                       "market_mood_count": len(market), "return_lookback_missing": baseline is None}
    row["lineage"].update(lookback_quote=baseline.event_id if baseline else None,
                          own_mood=mood.event_id if mood else None,
                          market_mood=[event.event_id for event in market])
    return row


def _resolve(index: Index, opportunity: Opportunity, row: dict) -> None:
    if row["status"] == "ineligible":
        return
    strike, terminal = index.entry(opportunity), index.terminal(opportunity)
    if strike is not None and terminal is not None and (terminal.event_ms < strike.event_ms or terminal.available_ms < strike.available_ms):
        row["reason_codes"].append("terminal_quote_precedes_modeled_entry")
        terminal = None
    if strike is None:
        row["reason_codes"].append("missing_entry_quote")
    else:
        row["modeled_strike"] = _text(strike.value)
        row["lineage"]["modeled_strike"] = strike.event_id
    if terminal is None:
        row["reason_codes"].append("missing_exact_expiry_quote" if index.config.terminal_policy == "exact_source" else "missing_fresh_pre_expiry_quote")
    else:
        row["terminal_quote"] = _text(terminal.value)
        row["lineage"]["terminal_quote"] = terminal.event_id
    if strike is None or terminal is None:
        return
    label = "up" if terminal.value > strike.value else "down" if terminal.value < strike.value else "tie"
    row.update(status="resolved", label=label, training_eligible=True)
    if opportunity.direction is not None:
        if label == "tie":
            pnl = Decimal(0) if index.config.tie_rule == "full_refund" else Decimal(-1)
        elif (opportunity.direction == "call") == (label == "up"):
            pnl = Decimal(row["features"]["payout"])
        else:
            pnl = Decimal(-1)
        row["unit_pnl"] = _text(pnl)


def build_rows(observations: list[dict], opportunities: list[dict], config: dict) -> dict:
    """Validate atomically, freeze every decision, then join proxy outcomes.

    Malformed input raises ContractError rather than silently manufacturing
    ineligible rows with guessed identity. Valid opportunities never disappear.
    All decimal results are strings; counters and ages are JSON integers.
    """
    if not isinstance(observations, list) or not isinstance(opportunities, list):
        raise ContractError("observations and opportunities must be lists")
    settings = Config.parse(config)
    index = Index(observations, settings)
    parsed = [Opportunity.parse(raw) for raw in opportunities]
    if settings.terminal_policy == "last_received_before":
        if any(op.clock_id != "receiver_utc" or op.expiry_basis != "hypothetical" for op in parsed):
            raise ContractError("last_received_before requires receiver_utc and hypothetical expiry")
    if len({op.opportunity_id for op in parsed}) != len(parsed):
        raise ContractError("duplicate opportunity_id")
    parsed.sort(key=lambda op: (op.decision_ms, op.opportunity_id))
    try:
        rows = [_decision_row(index, op) for op in parsed]
        before_label_eligible = sum(row["status"] != "ineligible" for row in rows)
        for opportunity, row in zip(parsed, rows):
            _resolve(index, opportunity, row)
    except DecimalException as exc:
        raise ContractError("decimal result outside supported arithmetic range") from exc
    counts = {"total": len(rows), "before_label_eligible": before_label_eligible,
              **{status: sum(row["status"] == status for row in rows) for status in ("resolved", "unresolved", "ineligible")},
              "ties": sum(row["label"] == "tie" for row in rows)}
    return {"schema_version": "causal_quote_proxy.v1", "rows": rows, "counts": counts,
            "observation_counts": index.audit,
            "research_only": True, "accepted_contract_cash": False,
            "decimal_precision": 34, "tie_rule": settings.tie_rule, "terminal_policy": settings.terminal_policy}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON object with observations, opportunities, config")
    parser.add_argument("--output", type=Path, help="write JSON to this path; otherwise stdout")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(), parse_constant=lambda token: (_ for _ in ()).throw(ContractError(f"nonfinite JSON: {token}")))
        _fields(payload, frozenset(("observations", "opportunities", "config")), frozenset(), "input")
        result = build_rows(payload["observations"], payload["opportunities"], payload["config"])
        serialized = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(serialized)
        else:
            print(serialized, end="")
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
