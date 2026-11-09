"""Free periodic workflow ordering/no-fit eval with a fixed pass threshold."""
import io
import json
import unittest
from .tests.test_run import WorkflowGates

def main():
    detail=io.StringIO();result=unittest.TextTestRunner(stream=detail).run(unittest.defaultTestLoader.loadTestsFromTestCase(WorkflowGates))
    print(json.dumps({'schema':'otc_fixed_workflow_eval_v1','tests':result.testsRun,
        'errors':len(result.errors),'failures':len(result.failures),'passed':result.wasSuccessful(),
        'pass_threshold':1.0,'real_fit_calls':0,'network_calls':0},sort_keys=True))
    if not result.wasSuccessful():print(detail.getvalue())
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
