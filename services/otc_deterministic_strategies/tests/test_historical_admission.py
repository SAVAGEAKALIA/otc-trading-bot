import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ..evals.historical_admission import run


class HistoricalAdmissionTests(unittest.TestCase):
    def test_empty_sources_do_not_invent_prices_offers_or_economic_opportunities(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            candles = base / 'candles.sqlite'
            context = base / 'context.sqlite'
            with sqlite3.connect(candles) as connection:
                connection.execute('CREATE TABLE candles(asset TEXT,timeframe INTEGER,timestamp INTEGER)')
            with sqlite3.connect(context) as connection:
                connection.execute('''CREATE TABLE realtime_candles(broker_asset TEXT,timeframe_sec INTEGER,
                 candle_start_ms INTEGER,finalized INTEGER,received_at_ms INTEGER,server_at_receive_ms INTEGER,
                 clock_offset_ms INTEGER)''')
                connection.execute('CREATE TABLE quote_samples(broker_asset TEXT,received_at_ms INTEGER)')
                connection.execute('CREATE TABLE payout_samples(broker_asset TEXT,instrument_type TEXT,received_at_ms INTEGER)')
            with contextlib.redirect_stdout(io.StringIO()):
                report = run(candles, context, base / 'report.json')
            self.assertEqual(report['status'], 'BLOCKED_FOR_ECONOMIC_EVIDENCE')
            self.assertEqual(report['admitted_actual_contracts'], 0)
            self.assertEqual(report['admitted_economic_opportunities'], 0)
            self.assertIsNone(report['quotes_and_payouts'][0]['quote_first_utc'])
            self.assertFalse(report['economic_claim'])
            self.assertFalse(report['directional_proxy_scored'])
            self.assertFalse(report['live_or_fresh_model_cohort_used'])


if __name__ == '__main__':
    unittest.main()
