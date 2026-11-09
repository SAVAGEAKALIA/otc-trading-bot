"""Periodic free source-boundary eval; every source-scope check must pass."""
import io
import json
import unittest
from services.otc_fresh_compare.tests.test_source_scope import ScopeTests

def main():
    detail=io.StringIO();result=unittest.TextTestRunner(stream=detail).run(unittest.defaultTestLoader.loadTestsFromTestCase(ScopeTests))
    record={'schema':'otc_whole_source_scope_eval_v1','pass_threshold':1.0,'passed':result.wasSuccessful(),
            'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'network_calls':0,'broker_calls':0,'fit_calls':0}
    print(json.dumps(record,sort_keys=True))
    if not result.wasSuccessful():print(detail.getvalue())
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
