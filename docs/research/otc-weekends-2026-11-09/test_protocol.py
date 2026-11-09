from copy import deepcopy
import unittest
from protocol import register,validate,stages,START,ms

class WeekendGates(unittest.TestCase):
 def test_fixed_population(self):
  r=register(1794000000000);self.assertTrue(validate(r));self.assertEqual(r['scheduled_opportunities'],70560)
  self.assertEqual([len(s['weekends']) for s in stages()],[3,1,1,1,1])
  weekends=[w['start_ms'] for s in stages() for w in s['weekends']];self.assertEqual(len(weekends),len(set(weekends)))
 def test_no_calendar_or_readiness_changes(self):
  r=register(1794000000000)
  for key,value in [('start_ms',r['start_ms']+120000),('grid_ms',60000),('collection_deployed',True),('scheduler_deployed',True),('assets',['EURUSD-OTC']),('capital_promotion',True)]:
   bad=deepcopy(r);bad[key]=value
   with self.assertRaises(ValueError):validate(bad)
 def test_deadline(self):
  from datetime import timedelta
  with self.assertRaises(ValueError):register(ms(START-timedelta(hours=6)))
 def test_stage_shift_even_with_digest_recomputed(self):
  from protocol import digest
  r=register(1794000000000);r['stages'][1]['end_ms']+=120000;r.pop('registration_sha256');r['registration_sha256']=digest(r)
  with self.assertRaises(ValueError):validate(r)
if __name__=='__main__':unittest.main()
