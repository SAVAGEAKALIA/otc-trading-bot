import sqlite3
import tempfile
import unittest
from pathlib import Path

from trading_platform.ml.context_features import (
    CONTEXT_FEATURES,
    CONTEXT_SCHEMA_VERSION,
    ContextPolicy,
    MarketContextProvider,
    canonical_asset,
)
from trading_platform.scripts.training.train_catboost_gate import (
    CONTEXT_FEATURES as TRAINER_CONTEXT_FEATURES,
    CONTEXT_SCHEMA_VERSION as TRAINER_CONTEXT_SCHEMA_VERSION,
)


SCHEMA = """
CREATE TABLE quote_samples (
    canonical_asset TEXT, broker_asset TEXT, source_event_ms INTEGER,
    received_at_ms INTEGER, server_at_receive_ms INTEGER,
    clock_offset_ms INTEGER, bid REAL, ask REAL, mid REAL, spread REAL
);
CREATE TABLE mood_samples (
    canonical_asset TEXT, broker_asset TEXT, instrument_type TEXT,
    observed_bucket_ms INTEGER, received_at_ms INTEGER,
    server_at_receive_ms INTEGER, clock_offset_ms INTEGER,
    call_fraction REAL, put_fraction REAL
);
CREATE TABLE payout_samples (
    canonical_asset TEXT, broker_asset TEXT, instrument_type TEXT,
    observed_bucket_ms INTEGER, received_at_ms INTEGER,
    server_at_receive_ms INTEGER, clock_offset_ms INTEGER,
    commission_percent REAL, payout_fraction REAL, source TEXT
);
CREATE TABLE live_deal_events (
    event_hash TEXT, canonical_asset TEXT, broker_asset TEXT,
    instrument_type TEXT, expiration_type TEXT, direction TEXT, amount REAL,
    event_time_ms INTEGER, expiration_ms INTEGER, received_at_ms INTEGER,
    server_at_receive_ms INTEGER, clock_offset_ms INTEGER,
    receive_latency_ms INTEGER
);
"""


class MarketContextProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "context.sqlite"
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(SCHEMA)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def insert_context(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO quote_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("EURUSD-OTC", "EURUSD-op", 99_000, 99_000, 99_000, 0,
                 1.1000, 1.1002, 1.1001, 0.0002),
            )
            # This future quote must never enter the snapshot at 100,000 ms.
            connection.execute(
                "INSERT INTO quote_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("EURUSD-OTC", "EURUSD-op", 101_000, 101_000, 101_000, 0,
                 1.2000, 1.2004, 1.2002, 0.0004),
            )
            connection.execute(
                "INSERT INTO mood_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("EURUSD-OTC", "EURUSD-op", "turbo-option", 98_000,
                 98_000, 98_000, 0, 0.60, 0.40),
            )
            connection.execute(
                "INSERT INTO payout_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("EURUSD-OTC", "EURUSD-op", "turbo-option", 97_000,
                 97_000, 97_000, 0, 20.0, 0.80, "test"),
            )
            deals = [
                ("a", "call", 2.0, 95_000),
                ("b", "call", 3.0, 96_000),
                ("c", "put", 1.0, 97_000),
            ]
            for event_hash, direction, amount, event_ms in deals:
                connection.execute(
                    "INSERT INTO live_deal_events VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (event_hash, "EURUSD-OTC", "EURUSD-op", "turbo-option",
                     "PT2M", direction, amount, event_ms, 120_000, event_ms,
                     event_ms, 0, 0),
                )

    def test_snapshot_is_causal_and_maps_op_alias(self) -> None:
        self.insert_context()
        provider = MarketContextProvider(
            self.db_path,
            ContextPolicy(
                max_quote_age_ms=10_000,
                max_mood_age_ms=10_000,
                max_payout_age_ms=10_000,
                max_deal_feed_age_ms=10_000,
            ),
        )
        snapshot = provider.snapshot("EURUSD-OP", 100_000)
        self.assertEqual(canonical_asset("EURUSD-op"), "EURUSD-OTC")
        self.assertAlmostEqual(snapshot["spread_bps"], 0.0002 / 1.1001 * 10_000)
        self.assertAlmostEqual(snapshot["traders_mood"], 0.60)
        self.assertAlmostEqual(snapshot["payout_fraction"], 0.80)
        self.assertEqual(snapshot["deal_count_10s"], 3.0)
        self.assertAlmostEqual(snapshot["call_ratio_10s"], 2.0 / 3.0)
        self.assertEqual(snapshot["context_complete"], 1.0)

    def test_stale_values_are_flagged_not_backfilled(self) -> None:
        self.insert_context()
        provider = MarketContextProvider(
            self.db_path,
            ContextPolicy(
                max_quote_age_ms=500,
                max_mood_age_ms=500,
                max_payout_age_ms=500,
                max_deal_feed_age_ms=500,
            ),
        )
        snapshot = provider.snapshot("EURUSD-OTC", 100_000)
        self.assertEqual(snapshot["quote_missing"], 1.0)
        self.assertEqual(snapshot["mood_missing"], 1.0)
        self.assertEqual(snapshot["payout_missing"], 1.0)
        self.assertEqual(snapshot["context_complete"], 0.0)
        self.assertEqual(snapshot["payout_fraction"], 0.0)

    def test_standalone_trainer_context_contract_matches_runtime(self) -> None:
        self.assertEqual(TRAINER_CONTEXT_SCHEMA_VERSION, CONTEXT_SCHEMA_VERSION)
        self.assertEqual(TRAINER_CONTEXT_FEATURES, CONTEXT_FEATURES)


if __name__ == "__main__":
    unittest.main()
