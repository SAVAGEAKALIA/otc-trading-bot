"""Offline delivery guards. Test matrices are fabricated fixtures and never sent."""
import csv
import hashlib
import json
import shutil
import contextlib
import io
from types import SimpleNamespace as NS
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

from services.otc_research import training
from services.otc_research.kaggle import runner


class Request:
    pass


class FixtureAPI:
    def __init__(self,source):
        self.calls=[];self.push_version=1;self.remote_version_override=None
        self.info=NS(dataset_id=123,is_private=True,owner_user=runner.OWNER,dataset_slug=runner.DATASET_SLUG)
        self.meta=NS(id=456,ref=runner.KERNEL_REF,author='Saviour Akalia',slug=runner.KERNEL_SLUG,
            current_version_number=1,is_private=True,enable_gpu=False,enable_tpu=False,
            machine_shape='',dataset_data_sources=[runner.DATASET_REF],competition_data_sources=[],
            kernel_data_sources=[],model_data_sources=[])
        self.blob=NS(source=source)

    def build_kaggle_client(self):
        api=self
        class Context:
            def __enter__(self):
                return NS(datasets=NS(dataset_api_client=NS(get_dataset_metadata=api.dataset,
                    list_datasets=lambda request:NS(datasets=[],next_page_token=''))),
                    kernels=NS(kernels_api_client=NS(get_kernel=api.kernel,
                    list_kernels=lambda request:NS(kernels=[],next_page_token=''))))
            def __exit__(self,*args):return False
        return Context()

    def dataset(self,request):return NS(error_message='',info=self.info)
    def kernel(self,request):
        self.calls.append(request.version_label)
        return NS(metadata=self.meta,blob=self.blob)
    def dataset_status(self,ref):return 'ready'
    def kernels_push(self,folder,**kwargs):
        self.meta.current_version_number=self.remote_version_override or self.push_version
        response=NS(error='',ref=runner.KERNEL_REF,version_number=self.push_version,kernel_id=456,url='https://www.kaggle.com/code/'+runner.KERNEL_REF)
        self.push_version+=1
        return response


def fake_request_modules():
    return patch.dict('sys.modules',{
        'kagglesdk.datasets.types.dataset_api_service':NS(ApiGetDatasetMetadataRequest=Request,ApiListDatasetsRequest=Request),
        'kagglesdk.kernels.types.kernels_api_service':NS(ApiGetKernelRequest=Request,ApiListKernelsRequest=Request),
        'kagglesdk.datasets.types.dataset_enums':NS(DatasetSelectionGroup=NS(DATASET_SELECTION_GROUP_MY=0)),
        'kagglesdk.kernels.types.kernels_enums':NS(KernelsListViewType=NS(PROFILE=0))})


def parity_fixture(ids):
    count=len(ids)
    return {'schema':'otc_saved_inference_parity_v1','rows':count,'pass':True,
        'models':{name:{'rows':count,'max_probability_error':0.0,'decisions_match':True,'pass':True}
                  for name in ('logistic','catboost')}}


def output_fixture(package,downloaded):
    comparison=downloaded/'comparison';comparison.mkdir(parents=True)
    state=runner.read_json(package/'delivery.json')
    ids=runner.csv_ids(package/'dataset/input.csv');parity=parity_fixture(ids)
    for name in runner.REQUIRED_OUTPUTS:
        path=comparison/name
        if path.suffix=='.json':runner.write_json(path,{})
        elif path.suffix=='.csv':
            with path.open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['opportunity_id']);writer.writerows((value,) for value in ids)
        else:path.write_text('offline-output-fixture-only\n')
    runner.write_json(comparison/'saved_inference_parity.json',parity)
    (comparison/'dataset_manifest.json').write_bytes((package/'dataset/manifest.json').read_bytes())
    report={'status':'DONE','promotable':False,'device':'CPU','input_sha256':state['package']['files']['input.csv'],
            'code_sha256':state['package']['files']['training.py'],'manifest_sha256':state['package']['files']['manifest.json'],
            'saved_inference_parity':parity}
    runner.write_json(comparison/'report.json',report)
    refresh_artifact_manifest(package,comparison)
    return comparison


def refresh_artifact_manifest(package,comparison):
    state=runner.read_json(package/'delivery.json')
    hashes={name:{'sha256':runner.digest(comparison/name),'bytes':(comparison/name).stat().st_size}
            for name in runner.REQUIRED_OUTPUTS}
    runner.write_json(comparison/'artifact_manifest.json',{'schema':'otc_training_artifacts_v1',
            'promotable':False,'input_sha256':state['package']['files']['input.csv'],
            'code_sha256':state['package']['files']['training.py'],'files':hashes})


class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline_fixture=cls('test_admitted_package_is_private_cpu_and_exact_source')
        cls.baseline_fixture.setUp()
        cls.baseline=cls.baseline_fixture.root/'baseline'
        # Gates exercise local delivery guards. Isolated canonical admission is
        # exercised without mocks by the periodic eval and cold review.
        with patch.object(runner,'admit_bundle',side_effect=lambda dataset:runner.read_json(dataset/'manifest.json')):
            runner.prepare(*cls.baseline_fixture.inputs(full=False),cls.baseline)

    @classmethod
    def tearDownClass(cls):cls.baseline_fixture.doCleanups()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def inputs(self,evidence='received_price_proxy',full=True):
        source=self.root/'source';source.mkdir();matrix=source/'input.csv'
        with matrix.open('w',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=training.COLUMNS);writer.writeheader()
            for part,minimum in training.MINIMUM_ROWS.items():
                minimum=minimum if full else 3
                start=training.LIMITS[part][0] or training.epoch_ms('2026-08-01')
                for i in range(minimum):
                    decision=start+1000+i*120001
                    writer.writerow({'opportunity_id':f'{part}-{i}','asset':training.ASSETS[i%2],
                        'decision_ms':decision,'expiry_ms':decision+120000,'status':'resolved',
                        'label':training.LABELS[i%3],'payout':.85,
                        'f_return_lookback':.001,'f_own_mood':.5,'f_market_mood':.5,
                        'f_payout':.85,'f_quote_age_ms':1,'f_mood_age_ms':1,'f_payout_age_ms':1,
                        'evidence_class':evidence})
        manifest=source/'manifest.json'
        runner.write_json(manifest,{'schema':training.MANIFEST_SCHEMA,'expiry_basis':'hypothetical',
            'product_mapping':'explicit_assumed','clock':'receiver_utc','promotable':False,
            'input_sha256':runner.digest(matrix),'feature_availability':'receiver_receipt_lte_decision',
            'outcome_basis':'last_received_quote_at_or_before_expiry','evidence_classes':[evidence],
            'source_lineage':[{'source_id':'offline-delivery-test-only','sha256':'a'*64,
                'kind':training.EVIDENCE_KINDS[evidence],'clock':'receiver_utc'}]})
        requirements=source/'requirements.txt';requirements.write_text('catboost==1.2.10\n')
        return matrix,manifest,Path(training.__file__),requirements

    def package(self):
        target=self.root/'package';shutil.copytree(self.baseline,target)
        return target

    def test_admitted_package_is_private_cpu_and_exact_source(self):
        path=self.package();state=runner.verify_package(path)
        self.assertEqual(state['phase'],'prepared')
        self.assertEqual(set(state['package']['files']),set(runner.PAYLOAD))
        metadata=runner.read_json(path/'kernel/kernel-metadata.json')
        self.assertIs(metadata['is_private'],True)
        self.assertIs(metadata['enable_gpu'],False)
        compile((path/'kernel/main.py').read_text(),'kaggle_main.py','exec')

    def test_synthetic_evidence_cannot_be_uploaded(self):
        with self.assertRaisesRegex(ValueError,'received-price'):
            runner.prepare(*self.inputs('synthetic_training_eval',full=False),self.root/'package')

    def test_requires_pinned_training_dependencies(self):
        inputs=self.inputs(full=False);inputs[-1].write_text('catboost>=1.0\n')
        with self.assertRaisesRegex(ValueError,'exact version pins'):
            runner.prepare(*inputs,self.root/'package')

    def test_extra_raw_database_secret_and_symlink_are_rejected(self):
        path=self.package();dataset=path/'dataset'
        extra=dataset/'market_context.sqlite';extra.write_bytes(b'raw')
        with self.assertRaisesRegex(ValueError,'whitelist'):runner.verify_package(path)
        extra.unlink()
        payload=dataset/'requirements.txt';original=payload.read_bytes()
        payload.write_bytes(b'KGAT_'+b'x'*32)
        with self.assertRaisesRegex(ValueError,'Secret-shaped'):runner.verify_package(path)
        payload.write_bytes(original);payload.unlink();payload.symlink_to(self.root/'source/requirements.txt')
        with self.assertRaisesRegex(ValueError,'symlinks'):runner.verify_package(path)

    def test_changed_matrix_bytes_or_gpu_flag_fail_before_network(self):
        path=self.package();payload=path/'dataset/input.csv';original=payload.read_bytes()
        payload.write_bytes(original+b'\n')
        with self.assertRaisesRegex(ValueError,'bytes changed'):runner.verify_package(path)
        payload.write_bytes(original)
        metadata=runner.read_json(path/'kernel/kernel-metadata.json');metadata['enable_gpu']=True
        runner.write_json(path/'kernel/kernel-metadata.json',metadata)
        with self.assertRaisesRegex(ValueError,'privacy changed'):runner.verify_package(path)

    def test_no_output_inside_checkout_or_bare_repo(self):
        for kind in ('checkout','bare'):
            directory=self.root/kind;directory.mkdir()
            if kind=='checkout':(directory/'.git').write_text('gitdir: elsewhere')
            else:
                (directory/'HEAD').write_text('ref: refs/heads/main\n')
                (directory/'objects').mkdir();(directory/'refs').mkdir()
            target=directory/'package'
            with self.assertRaisesRegex(ValueError,'outside Git'):runner.new_directory(target)
            self.assertFalse(target.exists())

    def test_download_hash_and_input_identity_verified_before_loading(self):
        path=self.package();state=runner.read_json(path/'delivery.json');state['kernel_version']=2
        runner.write_json(path/'delivery.json',state)
        downloaded=path/'downloaded';comparison=output_fixture(path,downloaded)
        result=runner.verify_download(path,downloaded)
        self.assertTrue(result['input_and_source_match'])
        (comparison/'report.json').write_text('{}\n')
        with self.assertRaisesRegex(ValueError,'digest mismatch'):runner.verify_download(path,downloaded)

    def test_undeclared_comparison_files_and_nested_directories_are_rejected(self):
        package=self.package();downloaded=package/'downloaded';comparison=output_fixture(package,downloaded)
        for name,body in [('extra.json','{"nested":[1e10000]}'),
                          ('finite.json','{"value":1}'),('extra.txt','remote log')]:
            extra=comparison/name;extra.write_text(body)
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'inventory mismatch'):
                runner.verify_download(package,downloaded)
            self.assertFalse((downloaded/'verified-download.json').exists())
            extra.unlink()
        nested=comparison/'nested';nested.mkdir()
        (nested/'extra.json').write_text('{"nested":[1e10000]}')
        with self.assertRaisesRegex(ValueError,'inventory mismatch'):
            runner.verify_download(package,downloaded)

    def test_entire_download_json_is_finite_and_failure_clears_previous_success(self):
        package=self.package();downloaded=package/'downloaded';output_fixture(package,downloaded)
        nested=downloaded/'remote/diagnostics';nested.mkdir(parents=True)
        (downloaded/'progress.log').write_text('remote phase log\n')
        (downloaded/'stdout.txt').write_text('remote stdout\n')
        finite=nested/'finite.JSON';finite.write_text('{"phase":"completed","metric":0.5}')
        self.assertTrue(runner.verify_download(package,downloaded)['model_loading_permitted_after_hash_verification'])
        for location in (downloaded/'outside.json',nested/'outside.JSON'):
            for value in ('1e10000','-1e10000','NaN','Infinity','-Infinity'):
                runner.verify_download(package,downloaded)
                location.write_text('{"nested":[{"metric":'+value+'}]}')
                with self.subTest(location=location,value=value),self.assertRaisesRegex(ValueError,'Nonfinite JSON'):
                    runner.verify_download(package,downloaded)
                self.assertFalse((downloaded/'verified-download.json').exists())
                location.unlink()
        runner.verify_download(package,downloaded)
        link=downloaded/'linked-log';link.symlink_to(downloaded/'progress.log')
        with self.assertRaisesRegex(ValueError,'symlinks'):
            runner.verify_download(package,downloaded)
        self.assertFalse((downloaded/'verified-download.json').exists())

    def test_hash_matching_nonfinite_calibration_or_empty_parity_is_rejected(self):
        package=self.package();downloaded=package/'downloaded';comparison=output_fixture(package,downloaded)
        runner.verify_download(package,downloaded)
        manifest=runner.read_json(comparison/'artifact_manifest.json')
        entry=manifest['files']['logistic.joblib'];entry['bytes']=float(entry['bytes'])
        runner.write_json(comparison/'artifact_manifest.json',manifest)
        with self.assertRaisesRegex(ValueError,'digest mismatch'):
            runner.verify_download(package,downloaded)
        refresh_artifact_manifest(package,comparison)
        report=runner.read_json(comparison/'report.json');report['saved_inference_parity']['pass']=1
        runner.write_json(comparison/'report.json',report);refresh_artifact_manifest(package,comparison)
        with self.assertRaisesRegex(ValueError,'overall verdict'):
            runner.verify_download(package,downloaded)
        report['saved_inference_parity']['pass']=True
        runner.write_json(comparison/'report.json',report);refresh_artifact_manifest(package,comparison)
        target=comparison/'catboost_calibration.json';before=target.read_bytes()
        target.write_text('{"nested":[1e10000]}')
        refresh_artifact_manifest(package,comparison)
        with self.assertRaisesRegex(ValueError,'Nonfinite'):
            runner.verify_download(package,downloaded)
        target.write_bytes(before)
        runner.write_json(comparison/'saved_inference_parity.json',{'pass':True})
        refresh_artifact_manifest(package,comparison)
        with self.assertRaisesRegex(ValueError,'parity schema is incomplete'):
            runner.verify_download(package,downloaded)

    def test_parity_rows_models_flags_and_error_are_consistent(self):
        ids=['one','two'];decisions={'logistic':ids,'catboost':ids};parity=parity_fixture(ids)
        runner.validate_parity(parity,ids,decisions)
        for field,value in [('rows',1),('rows',True),('max_probability_error',-1),
            ('max_probability_error',1e-8),('max_probability_error',True),('max_probability_error',10**1000),
            ('decisions_match',False),('decisions_match',1),('pass',False),('pass',1)]:
            bad=json.loads(json.dumps(parity));bad['models']['logistic'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                runner.validate_parity(bad,ids,decisions)
        with self.assertRaisesRegex(ValueError,'CSV population'):
            runner.validate_parity(parity,ids,{'logistic':['one'],'catboost':ids})

    def test_remote_version_identity_source_scope_and_machine_are_fixed(self):
        source='reviewed source';api=FixtureAPI(source)
        kwargs={'version':1,'expected_source_hash':hashlib.sha256(source.encode()).hexdigest(),
                'expected_ids':{'dataset_id':123,'kernel_id':456}}
        with fake_request_modules():
            positive=runner.read_remote_privacy(api,runner.DATASET_REF,runner.KERNEL_REF,**kwargs)
            self.assertEqual(positive['kernel_version'],1);self.assertEqual(api.calls,['v1'])
            for field,value in [('current_version_number',99),('id',99),('ref','foreign/kernel'),
                ('machine_shape','NvidiaTeslaP100'),('competition_data_sources',['foreign']),
                ('kernel_data_sources',['foreign']),('model_data_sources',['foreign']),
                ('enable_gpu',0),('enable_tpu',None)]:
                api=FixtureAPI(source);setattr(api.meta,field,value)
                with self.subTest(field=field),self.assertRaises(ValueError):
                    runner.read_remote_privacy(api,runner.DATASET_REF,runner.KERNEL_REF,**kwargs)
            api=FixtureAPI('unreviewed source')
            with self.assertRaisesRegex(ValueError,'source differs'):
                runner.read_remote_privacy(api,runner.DATASET_REF,runner.KERNEL_REF,**kwargs)

    def test_save_and_launch_verify_exact_response_versions_before_claiming_success(self):
        package=self.package();state=runner.read_json(package/'delivery.json');state['phase']='dataset_uploaded'
        runner.write_json(package/'delivery.json',state)
        source=(package/'kernel/main.py').read_text();api=FixtureAPI(source)
        with fake_request_modules(),contextlib.redirect_stdout(io.StringIO()):
            saved=runner.save_private_kernel(package,api)
            self.assertEqual(saved['phase'],'saved_private')
            launched=runner.launch(package,api)
            self.assertEqual(launched['phase'],'launched')
            self.assertEqual(set(launched['verified_versions']),{'1','2'})
            self.assertEqual(api.calls,['v1','v1','v2'])
        failed=self.root/'failed';shutil.copytree(self.baseline,failed)
        state=runner.read_json(failed/'delivery.json');state['phase']='dataset_uploaded';runner.write_json(failed/'delivery.json',state)
        api=FixtureAPI((failed/'kernel/main.py').read_text());api.remote_version_override=99
        with fake_request_modules(),self.assertRaisesRegex(ValueError,'pinned version'):
            runner.save_private_kernel(failed,api)
        self.assertEqual(runner.read_json(failed/'delivery.json')['phase'],'kernel_saved_unverified')

    def test_nested_json_overflow_and_constants_are_rejected(self):
        path=self.root/'nested.json'
        path.write_text('{"metrics":[0.1,-0.5,1e100]}')
        self.assertEqual(runner.read_json(path)['metrics'][1],-.5)
        for number in ('NaN','Infinity','-Infinity','1e10000','-1e10000'):
            path.write_text('{"metrics":[{"nested":['+number+']}]}')
            with self.subTest(number=number),self.assertRaisesRegex(ValueError,'Nonfinite'):
                runner.read_json(path)

    def test_owned_listing_follows_every_page_and_rejects_stalls(self):
        pages={'':(['one'],'second'),'second':(['two'],'')}
        self.assertEqual(runner.collect_refs(lambda token:pages[token]),['one','two'])
        with self.assertRaisesRegex(ValueError,'did not advance'):
            runner.collect_refs(lambda token:(['one'],'repeated'))

    def test_progress_reports_unknown_percent_until_real_completion(self):
        path=self.root/'run';path.mkdir()
        queued=runner.progress(path,'QUEUED');finished=runner.progress(path,'COMPLETE')
        self.assertIsNone(queued['percent_done']);self.assertIsNone(queued['eta_seconds'])
        self.assertEqual((finished['percent_done'],finished['eta_seconds']),(100,0))
        self.assertEqual(len((path/'progress.log').read_text().splitlines()),2)


if __name__=='__main__':unittest.main()
