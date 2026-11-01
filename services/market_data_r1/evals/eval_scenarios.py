"""Offline adverse-input evaluation. Pass requires every scenario defended."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from collector import DAY,audit_series,funding,screen

class Fake:
 def __init__(self,pages):self.pages=iter(pages)
 def get(self,*a,**kw):return next(self.pages)
def ev(t):return {'fundingRateTimestamp':str(t),'fundingRate':'0.01'}

class ScenarioEvals(unittest.TestCase):
 def test_interval_change_not_silently_filled(self):
  r=audit_series([ev(0),ev(8*3600000),ev(12*3600000)],0,DAY,'funding')
  self.assertEqual(r['gap_hours_histogram'],{'4.0':1,'8.0':1})
  self.assertIsNone(r['calendar_complete'])
  self.assertIn('unverified',r['funding_schedule_status'])
 def test_repeated_funding_page_rejected(self):
  with self.assertRaises(ValueError):funding(Fake([{'list':[ev(8)]},{'list':[ev(8)]}]),'BTCUSDT',0,10)
 def test_crossed_nan_zero_wide_or_illiquid_quotes_rejected(self):
  q={'bid1Price':'100','ask1Price':'100.1','turnover24h':'100000000'}
  for changed in [{'ask1Price':'99'},{'ask1Price':'NaN'},{'bid1Price':'0'},{'ask1Price':'110'},{'turnover24h':'1'}]:
   with self.subTest(changed=changed):self.assertFalse(screen(q|changed,q)['passes_current_quote_screen'])
 def test_shifted_daily_grid_never_passes_calendar_gate(self):
  # One candle per date is insufficient: all starts must be UTC-midnight.
  for shift in [1,60_000,3_600_000,DAY-1]:
   rows=[[str(day*DAY+shift),'10','12','9','11'] for day in range(3)]
   with self.subTest(shift=shift),self.assertRaisesRegex(ValueError,'UTC midnight'):
    audit_series(rows,0,3*DAY,'candle')
 def test_corrupt_activity_does_not_pass_complete_calendar(self):
  for field in [5,6]:
   for value in ['NaN','-Infinity','-0.01']:
    rows=[[str(day*DAY),'10','12','9','11','0','0'] for day in range(3)]
    rows[1][field]=value
    with self.subTest(field=field,value=value),self.assertRaises(ValueError):
     audit_series(rows,0,3*DAY,'candle')
 def test_empty_funding_is_missing_not_zero_yield(self):
  r=audit_series([],0,DAY,'funding')
  self.assertEqual(r['rows'],0);self.assertEqual(len(r['whole_missing_days']),1)

if __name__=='__main__':unittest.main()
