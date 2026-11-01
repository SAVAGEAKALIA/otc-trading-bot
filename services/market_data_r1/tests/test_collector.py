import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
import tempfile,json,hashlib
from collector import DAY,ms,finite,unique,audit_series,screen,funding,instruments,ReplayClient,PublicClient

START=ms('2026-10-01T00:00:00Z')

def bar(t):return [str(t),'10','12','9','11','1','10']
def event(t,rate='0.001'):return {'fundingRateTimestamp':str(t),'fundingRate':rate}

class Fake:
 def __init__(self,pages):self.pages=iter(pages)
 def get(self,*a,**kw):return next(self.pages)

class GateTests(unittest.TestCase):
 def test_utc_epoch(self):self.assertEqual(ms('1970-01-01T00:00:00Z'),0)
 def test_naive_time_rejected(self):
  with self.assertRaises(ValueError):ms('2026-10-01T00:00:00')
 def test_nonfinite_rejected(self):
  for n in ['NaN','Infinity','-Infinity']:
   with self.subTest(n=n),self.assertRaises(ValueError):finite(n)
 def test_exact_duplicates_deduped(self):self.assertEqual(unique([bar(START)]*2,lambda r:r[0])[1],1)
 def test_conflicting_duplicates_rejected(self):
  with self.assertRaises(ValueError):unique([event(START),event(START,'0.002')],lambda r:r['fundingRateTimestamp'])
 def test_candle_gap_preserved(self):
  result=audit_series([bar(START),bar(START+2*DAY)],START,START+3*DAY,'candle')
  self.assertEqual(result['whole_missing_days'],['2026-10-02']);self.assertFalse(result['calendar_complete'])
 def test_complete_calendar(self):self.assertTrue(audit_series([bar(START)],START,START+DAY,'candle')['calendar_complete'])
 def test_daily_bar_must_start_at_utc_midnight(self):
  with self.assertRaisesRegex(ValueError,'UTC midnight'):
   audit_series([bar(START+3600000)],START,START+DAY,'candle')
 def test_audit_window_requires_positive_complete_utc_days(self):
  for start,end in [(START+1,START+DAY),(START,START+DAY-1),(START,START),(START+DAY,START)]:
   for kind in ['candle','funding']:
    with self.subTest(start=start,end=end,kind=kind),self.assertRaisesRegex(ValueError,'complete UTC days'):
     audit_series([],start,end,kind)
 def test_partial_day_outside_window_rejected(self):
  with self.assertRaises(ValueError):audit_series([bar(START+DAY)],START,START+DAY,'candle')
 def test_invalid_ohlc(self):
  b=bar(START);b[2]='5'
  with self.assertRaises(ValueError):audit_series([b],START,START+DAY,'candle')
 def test_optional_candle_activity_must_be_finite_nonnegative(self):
  for field in [5,6]:
   for bad in ['NaN','Infinity','-1']:
    b=bar(START);b[field]=bad
    with self.subTest(field=field,bad=bad),self.assertRaises(ValueError):
     audit_series([b],START,START+DAY,'candle')
 def test_price_only_mark_candle_remains_valid(self):
  self.assertTrue(audit_series([bar(START)[:5]],START,START+DAY,'candle')['calendar_complete'])
 def test_existing_report_only_output_is_never_mutated(self):
  with tempfile.TemporaryDirectory() as d:
   output=Path(d)/'snapshot';output.mkdir();report=output/'report.json';report.write_text('PREVIOUS COMPLETE REPORT')
   with self.assertRaises(FileExistsError):PublicClient(output/'raw')
   self.assertEqual(report.read_text(),'PREVIOUS COMPLETE REPORT')
   self.assertFalse((output/'raw').exists())
 def test_valid_quote_screen(self):
  q={'bid1Price':'100','ask1Price':'100.1','turnover24h':'100000000'}
  self.assertTrue(screen(q,q)['passes_current_quote_screen'])
 def test_missing_quote_fails(self):self.assertFalse(screen({},{})['passes_current_quote_screen'])
 def test_funding_pagination(self):
  got=funding(Fake([{'list':[event(START+3600000)]},{'list':[event(START)]}]),'BTCUSDT',START,START+DAY)
  self.assertEqual(len(got),2)
 def test_cursor_repeat_fails(self):
  with self.assertRaises(ValueError):instruments(Fake([{'list':[],'nextPageCursor':'same'}]*2),'linear')

class ReplayTests(unittest.TestCase):
 def fixture(self,root):
  source=root/'source';source.mkdir()
  raw=b'{"retCode":0,"result":{"timeSecond":"123"}}'
  (source/'0000.json').write_bytes(raw)
  record={'file':'0000.json','url':'https://api.bybit.com/v5/market/time?','sha256':hashlib.sha256(raw).hexdigest()}
  (source/'manifest.json').write_text(json.dumps([record]))
  return source
 def test_replay_validates_source(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=self.fixture(root)
   client=ReplayClient(root/'out'/'raw',source)
   self.assertEqual(client.get('time'),{'timeSecond':'123'})
 def test_checksum_tampering_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=self.fixture(root)
   (source/'0000.json').write_text('{}')
   with self.assertRaises(ValueError):ReplayClient(root/'out'/'raw',source).get('time')
 def test_request_mismatch_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=self.fixture(root)
   with self.assertRaises(ValueError):ReplayClient(root/'out'/'raw',source).get('tickers',category='spot')

if __name__=='__main__':unittest.main()
