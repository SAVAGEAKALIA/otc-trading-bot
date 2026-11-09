"""Small delivery gates. Full bundle/remote/download integration is periodic."""
import json
from pathlib import Path
import tempfile
import unittest
from services.otc_research.kaggle import runner


class FastDeliveryGates(unittest.TestCase):
    def test_json_accepts_finite_and_rejects_every_nested_nonfinite_form(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'record.json';path.write_text('{"metrics":[0,-0.5,1e100]}')
            self.assertEqual(runner.read_json(path)['metrics'][1],-.5)
            for value in ('NaN','Infinity','-Infinity','1e10000','-1e10000'):
                path.write_text('{"nested":[{"values":['+value+']}]}')
                with self.subTest(value=value),self.assertRaises(ValueError):runner.read_json(path)

    def test_parity_requires_complete_models_consistent_rows_flags_and_tolerance(self):
        ids=['a','b'];decisions={'logistic':ids,'catboost':ids}
        parity={'schema':'otc_saved_inference_parity_v1','rows':2,'pass':True,
            'models':{name:{'rows':2,'max_probability_error':0.0,'decisions_match':True,'pass':True}
                      for name in decisions}}
        runner.validate_parity(parity,ids,decisions)
        for field,value in [('rows',1),('rows',True),('pass',False),('pass',1),
            ('decisions_match',False),('max_probability_error',-1),
            ('max_probability_error',1e-8),('max_probability_error',10**1000)]:
            mutated=json.loads(json.dumps(parity));mutated['models']['catboost'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                runner.validate_parity(mutated,ids,decisions)
        with self.assertRaises(ValueError):runner.validate_parity({'pass':True},ids,decisions)
        with self.assertRaises(ValueError):runner.validate_parity(parity,ids,{'logistic':['a'],'catboost':ids})

    def test_owned_listing_exhausts_pages_and_fails_on_repeat(self):
        pages={'':(['first'],'next'),'next':(['second'],'')}
        self.assertEqual(runner.collect_refs(lambda token:pages[token]),['first','second'])
        with self.assertRaises(ValueError):runner.collect_refs(lambda token:([],'same'))

    def test_unknown_remote_reference_or_unpinned_version_fails_before_client(self):
        class NoCalls:
            def build_kaggle_client(self):raise AssertionError('Must reject before an API call')
        for dataset,kernel,kwargs in [('foreign/data',None,{}),
            (runner.DATASET_REF,'foreign/kernel',{'version':1}),
            (runner.DATASET_REF,runner.KERNEL_REF,{})]:
            with self.assertRaises(ValueError):runner.read_remote_privacy(NoCalls(),dataset,kernel,**kwargs)

    def test_upload_whitelist_rejects_extra_file_and_secret_patterns(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);path=folder/'source.py';path.write_text('print(1)\n')
            runner.whitelist(folder,frozenset(('source.py',)))
            extra=folder/'raw.sqlite';extra.write_text('fixture')
            with self.assertRaises(ValueError):runner.whitelist(folder,frozenset(('source.py',)))
            extra.unlink();path.write_bytes(b'KGAT_'+b'x'*32)
            with self.assertRaises(ValueError):runner.whitelist(folder,frozenset(('source.py',)))

    def test_outputs_refuse_git_metadata_and_generated_kernel_has_valid_syntax(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'.git').write_text('gitdir: elsewhere')
            target=root/'model-output'
            with self.assertRaises(ValueError):runner.new_directory(target)
            self.assertFalse(target.exists())
        compile(runner.kernel_source({name:'a'*64 for name in runner.PAYLOAD}),'kaggle_main.py','exec')

    def test_download_inventory_rejects_root_file_and_directory_symlinks(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);download=root/'download';download.mkdir()
            nested=download/'nested';nested.mkdir()
            record=nested/'record.JSON';record.write_text('{"finite":1}')
            self.assertEqual(runner.downloaded_files(download),[record])
            alias=root/'alias';alias.symlink_to(download,target_is_directory=True)
            with self.assertRaises(ValueError):runner.downloaded_files(alias)
            for target in (record,nested):
                link=download/'link';link.symlink_to(target,target_is_directory=target.is_dir())
                with self.assertRaises(ValueError):runner.downloaded_files(download)
                link.unlink()

    def test_reverification_discards_success_receipt_even_when_receipt_is_nonfinite(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);receipt=root/'verified-download.json'
            runner.write_json(receipt,{'model_loading_permitted_after_hash_verification':True})
            runner.discard_download_receipt(root)
            self.assertFalse(receipt.exists())
            receipt.write_text('{"nested":[1e10000]}')
            with self.assertRaises(ValueError):runner.discard_download_receipt(root)
            self.assertFalse(receipt.exists())


if __name__=='__main__':unittest.main()
