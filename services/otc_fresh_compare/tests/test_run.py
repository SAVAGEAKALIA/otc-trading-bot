"""Workflow ordering and no-fit-on-failure gates. No real model or wait."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from services.otc_fresh_compare.run import run_registered

class WorkflowGates(unittest.TestCase):
    @patch('services.otc_fresh_compare.run.print')
    def test_order_wait_then_export_then_original_compare(self,unused_print):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);reg=root/'registration.json';reg.write_text(json.dumps({'registration_sha256':'a'*64}))
            order=[];report={'status':'DONE','saved_inference_parity':{'pass':True}}
            with patch('services.otc_fresh_compare.run.validate_registration'),patch('services.otc_fresh_compare.run.freeze_plan',side_effect=lambda *a:order.append('freeze')),patch('services.otc_fresh_compare.run.compile_trainer',side_effect=lambda *a:order.append('compile')),patch('services.otc_fresh_compare.run.wait_for_chain',side_effect=lambda *a,**k:order.append('wait_complete')),patch('services.otc_fresh_compare.run.export_matrix',side_effect=lambda *a:order.append('export') or {'opportunities':10080}),patch('services.otc_fresh_compare.run.compare',side_effect=lambda *a:order.append('compare') or report):
                self.assertEqual(run_registered(reg,root/'sourcechain.json',root/'run'),report)
            self.assertEqual(order,['freeze','compile','wait_complete','export','compare'])
    @patch('services.otc_fresh_compare.run.print')
    def test_failed_wait_or_export_never_fits(self,unused_print):
        for phase in ('wait_for_chain','export_matrix'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);reg=root/'registration.json';reg.write_text(json.dumps({'registration_sha256':'a'*64}))
                with patch('services.otc_fresh_compare.run.validate_registration'),patch('services.otc_fresh_compare.run.freeze_plan'),patch('services.otc_fresh_compare.run.compile_trainer'),patch('services.otc_fresh_compare.run.wait_for_chain'),patch('services.otc_fresh_compare.run.export_matrix',return_value={'opportunities':10080}),patch('services.otc_fresh_compare.run.compare') as fit,patch('services.otc_fresh_compare.run.'+phase,side_effect=ValueError('incomplete or invalid source')):
                    with self.assertRaises(ValueError):run_registered(reg,root/'sourcechain.json',root/'run')
                    fit.assert_not_called()
                saved=json.loads((root/'run'/'workflow-status.json').read_text())
                self.assertEqual(saved['status'],'BLOCKED');self.assertFalse(saved['promotable'])

if __name__=='__main__':unittest.main()
