import unittest
from services.otc_observer.normalize import normalize_rows, availability_audit


class NormalizeTests(unittest.TestCase):
    def quote(self, source=1000, value=1.1):
        return dict(broker_asset='EURUSD-OTC', source_event_ms=source, received_at_ms=2000, clock_offset_ms=-100, mid=value)

    def test_batch_latest_original_tick_true_receipt(self):
        events, counts, lineage = normalize_rows([self.quote(1000, 1.1), self.quote(1500, 1.2)], 'quote')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['value'], '1.2')
        self.assertEqual(events[0]['available_ms'], 2000)
        self.assertEqual(events[0]['event_ms'], 2000)
        self.assertEqual(lineage[events[0]['event_id']]['raw_source_or_bucket_ms'], 1500)
        self.assertEqual(lineage[events[0]['event_id']]['product_basis'], 'explicit_assumed')
        self.assertEqual(counts['batch_rows_collapsed'], 1)

    def test_payout_future_receipt_detected_on_same_grid(self):
        raw = dict(broker_asset='EURUSD-OTC', instrument_type='turbo-option', source='init-snapshot', observed_bucket_ms=0, received_at_ms=250000, clock_offset_ms=0, payout_fraction=.85)
        events, _, lineage = normalize_rows([raw], 'payout')
        ops = [dict(opportunity_id='one', asset='EURUSD-OTC', product='turbo-option', decision_ms=120000), dict(opportunity_id='two', asset='EURUSD-OTC', product='turbo-option', decision_ms=260000)]
        result = availability_audit(ops, events, lineage)
        self.assertEqual((result['future_join_count'], result['legacy_joined']), (1, 2))

    def test_clock_anomalies_conflicts_old_future_source_quarantined(self):
        bad = self.quote(); bad['clock_offset_ms'] = -800000
        rows = [bad, self.quote(1000, 1.1), self.quote(1000, 1.2), self.quote(2001), self.quote(-15000)]
        events, counts, _ = normalize_rows(rows, 'quote')
        self.assertFalse(events)
        self.assertEqual(counts['clock_quarantine'], 1)
        self.assertEqual(counts['conflicting_batch_rows'], 2)
        self.assertEqual(counts['quote_source_age_quarantine'], 1)
        self.assertEqual(counts['missing_source_identity'], 1)

    def test_product_unknown_receipt_value_and_asset(self):
        raw = dict(broker_asset='EURUSD-OTC', instrument_type='binary-option', source='init-snapshot', observed_bucket_ms=0, received_at_ms=2000, clock_offset_ms=0, payout_fraction=.85)
        self.assertEqual(normalize_rows([raw], 'payout')[1]['wrong_product'], 1)
        raw.update(instrument_type='turbo-option', received_at_ms=None)
        self.assertEqual(normalize_rows([raw], 'payout')[1]['missing_receipt'], 1)
        for value in [float('nan'), float('inf'), -1, 0]:
            self.assertFalse(normalize_rows([self.quote(value=value)], 'quote')[0])
        raw = self.quote(); raw['broker_asset'] = ' '
        self.assertEqual(normalize_rows([raw], 'quote')[1]['missing_asset_identity'], 1)
        for kind in ['cash', None]:
            with self.assertRaises(ValueError): normalize_rows([], kind)


if __name__ == '__main__': unittest.main()
