"""Seeded signal availability eval plus old-catalogue mutation regression."""
import asyncio
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trading_platform.brokers.iqoption.practice import PracticeExecution
from trading_platform.legacy.iqoption_bot.worker import APIWorker
from tests.unit.interfaces.test_otc_signal_delivery import CatalogueTrapBroker, NOW, SignalDeliveryGates


async def evaluate():
    rng = random.Random(20261109)
    checks = 0
    with tempfile.TemporaryDirectory(dir='/tmp') as tmp, patch('time.time_ns', return_value=NOW):
        api = CatalogueTrapBroker()
        guard = PracticeExecution(api, Path(tmp)/'orders.sqlite3')
        worker = object.__new__(APIWorker)
        worker.api = api
        worker.asset_resolver = SimpleNamespace(execution_adapter=SimpleNamespace(practice=guard))
        original = deepcopy(api.offer)
        for _ in range(5000):
            api.offer = deepcopy(original)
            api.offer['enabled'] = rng.choice((True, False))
            api.offer['is_suspended'] = rng.choice((True, False))
            commission = rng.randrange(0, 101)
            api.offer['option']['profit']['commission'] = commission
            result = await worker.get_available_assets()
            expected = {'USDNGN-OTC': {'open': True}} if api.offer['enabled'] and not api.offer['is_suspended'] and commission <= 20 else {}
            assert result == {'turbo': expected}
            assert api.catalogue_calls == 0
            assert not api.sent
            checks += 3
    return checks


def main():
    checks = asyncio.run(evaluate())
    with contextlib.redirect_stdout(io.StringIO()):
        result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(SignalDeliveryGates))
        async def old_catalogue(self):
            try:
                return await asyncio.to_thread(self.api.get_all_open_time)
            except Exception:
                return {}
        with patch.object(APIWorker, 'get_available_assets', old_catalogue):
            mutant = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite([
                SignalDeliveryGates('test_telegram_asset_lookup_uses_actual_eligible_turbo_offer'),
                SignalDeliveryGates('test_snapshot_failure_does_not_start_catalogue_or_invent_assets'),
            ]))
    assert result.wasSuccessful()
    assert len(mutant.failures) == 2 and not mutant.errors
    return {'pass': True, 'seed': 20261109, 'checks': checks, 'gates': result.testsRun,
            'old_catalogue_mutant_killed': True, 'account_calls': 0, 'orders': 0, 'verified_edge': False}


if __name__ == '__main__':
    print(json.dumps(main(), sort_keys=True))
