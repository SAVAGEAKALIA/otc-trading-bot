"""Small deterministic fixtures shared by local verification commands."""
from copy import deepcopy


def config():
    return {"source_priority": {"quote": ["primary", "secondary"], "mood": ["primary", "secondary"], "payout": ["primary", "secondary"]},
            "max_age_ms": {"quote": 300, "mood": 300, "payout": 300},
            "max_entry_wait_ms": 100, "max_settlement_wait_ms": 50, "lookback_ms": 200,
            "tie_rule": "full_refund"}


def observation(event_id, kind, event_ms, value, *, available_ms="same", **updates):
    record = {"event_id": event_id, "broker": "fixture", "asset": "EURUSD-OTC", "product": "binary",
              "source": "primary", "kind": kind,
              "available_ms": event_ms if available_ms == "same" else available_ms,
              "event_ms": event_ms, "value": str(value), "clock_id": "fixture-normalized-utc"}
    record.update(updates)
    return record


def opportunity(**updates):
    record = {"opportunity_id": "op-1", "broker": "fixture", "asset": "EURUSD-OTC", "product": "binary",
              "clock_id": "fixture-normalized-utc", "decision_ms": 1000, "expiry_ms": 2000,
              "latest_entry_ms": 1150, "expiry_basis": "broker_offer", "acceptance_delay_ms": 10,
              "evidence_class": "received_price_proxy", "direction": "call"}
    record.update(updates)
    return record


def observations():
    return [observation("q-lookback", "quote", 800, "98"),
            observation("q-decision", "quote", 950, "100"),
            observation("p-decision", "payout", 900, "0.8"),
            observation("m-own", "mood", 940, "0.6"),
            observation("m-other", "mood", 910, "0.4", asset="GBPUSD-OTC"),
            observation("q-entry", "quote", 1010, "100"),
            observation("q-terminal", "quote", 2000, "101")]


def payload():
    return deepcopy({"observations": observations(), "opportunities": [opportunity()], "config": config()})


def boundary_manifest():
    """A small completed receiver export with two frozen decision ticks."""
    return {'schema': 'otc_receiver_observation_export_v1', 'status': 'DONE',
            'source_stable': True, 'clock': 'receiver_utc', 'promotable': False,
            'product': 'turbo-option', 'quote_product_mapping': 'explicit_assumed',
            'assets': ['EURUSD-OTC', 'GBPUSD-OTC'],
            'receipt_bounds': {kind: {'first_receipt_ms': 100001, 'last_receipt_ms': 250000}
                               for kind in ('quote', 'mood', 'payout')},
            'inventory': {kind + '_samples': {'columns': ['received_at_ms'], 'rows_in_scope': 2}
                          for kind in ('quote', 'mood', 'payout')}}
