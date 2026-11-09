"""Offline adversarial delivery eval: no network, credentials, upload or model fit."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import sys
import math
from unittest.mock import patch

from services.otc_research.kaggle import runner
from services.otc_research.kaggle.tests.test_runner import DeliveryTests, FixtureAPI, output_fixture, refresh_artifact_manifest


def previous_download_verifier():
    """Restore the actual preceding verifier by reversing only its new boundary."""
    source=inspect.getsource(runner.verify_download)
    replacements={
        '    discard_download_receipt(downloaded)\n':'',
        "    files=downloaded_files(downloaded)\n    candidates=[path for path in files if path.name=='artifact_manifest.json']\n":
            "    candidates=list(downloaded.rglob('artifact_manifest.json'))\n",
        "    if {path.name for path in root.iterdir()}!=REQUIRED_OUTPUTS|{'artifact_manifest.json'}:\n        raise ValueError('Remote artifact inventory mismatch')\n":'',
        "    decoded_files={path:read_json(path) for path in files if path.suffix.lower()=='.json'}\n    decoded={name:decoded_files[root/name] for name in hashes if name.endswith('.json')}\n":
            "    decoded={name:read_json(root/name) for name in hashes if name.endswith('.json')}\n",
    }
    for current,previous in replacements.items():
        if source.count(current)!=1:raise AssertionError('Previous-verifier mutation no longer matches the source')
        source=source.replace(current,previous,1)
    namespace=dict(vars(runner));exec(compile(source,'previous_download_verifier.py','exec'),namespace)
    return namespace['verify_download'],source


def evaluate(output: Path, sdk_runtime: Path | None = None):
    if sdk_runtime:sys.path.insert(0,str(sdk_runtime.resolve()))
    checks={}
    fixture=DeliveryTests('test_admitted_package_is_private_cpu_and_exact_source');fixture.setUp()
    try:
        root=fixture.root/'full-package';runner.prepare(*fixture.inputs(),root)
        checks['faithful_isolated_contract_admission_positive']=runner.admit_bundle(root/'dataset')['evidence_classes']==['received_price_proxy']
        kernel=root/'kernel/kernel-metadata.json';original=kernel.read_bytes()
        for name,value in [('is_private',False),('is_private','true'),('is_private',1),
            ('enable_gpu',True),('enable_gpu',0),('enable_tpu',True),
            ('dataset_sources',['foreign/raw-source']),('competition_sources',['another-task'])]:
            metadata=json.loads(original);metadata[name]=value;runner.write_json(kernel,metadata)
            try:runner.verify_package(root);passed=False
            except ValueError:passed=True
            checks[f'{name}:{value!r}_rejected']=passed
            kernel.write_bytes(original)
        matrix=root/'dataset/input.csv';before=matrix.read_bytes()
        for label,payload in [('token',b'KGAT_'+b'A'*32),('private_key',b'-----BEGIN RSA '+b'PRIVATE KEY-----')]:
            matrix.write_bytes(payload)
            try:runner.verify_package(root);passed=False
            except ValueError:passed=True
            checks[f'{label}_rejected']=passed
            matrix.write_bytes(before)
        old_limit=runner.MAX_PACKAGE_BYTES;runner.MAX_PACKAGE_BYTES=1
        try:
            try:runner.verify_package(root);checks['size_budget_rejected']=False
            except ValueError:checks['size_budget_rejected']=True
        finally:runner.MAX_PACKAGE_BYTES=old_limit
        checks['admitted_package_still_passes']=runner.verify_package(root)['phase']=='prepared'
        # Mutation proves the whitelist, rather than incidental metadata rejection,
        # is what prevents a raw source database from being uploaded.
        extra=root/'dataset/market_context.sqlite';extra.write_bytes(b'offline raw fixture')
        try:runner.verify_package(root);checks['raw_database_rejected']=False
        except ValueError:checks['raw_database_rejected']=True
        actual=runner.DATASET_FILES;runner.DATASET_FILES=actual|{'market_context.sqlite'}
        try:checks['unsafe_whitelist_mutant_would_admit_raw_database']=runner.verify_package(root)['phase']=='prepared'
        finally:runner.DATASET_FILES=actual
        extra.unlink()
        from kagglesdk.kernels.types.kernels_api_service import ApiKernelMetadata,ApiGetKernelResponse,ApiKernelBlob
        from kagglesdk.datasets.types.dataset_api_service import DatasetInfo,ApiGetDatasetMetadataResponse
        class SDKAPI(FixtureAPI):
            def __init__(self,source):
                super().__init__(source)
                info=DatasetInfo()
                for field,value in vars(self.info).items():setattr(info,field,value)
                meta=ApiKernelMetadata()
                for field,value in vars(self.meta).items():setattr(meta,field,value)
                blob=ApiKernelBlob();blob.source=source
                self.info=info;self.meta=meta;self.blob=blob
            def dataset(self,request):
                result=ApiGetDatasetMetadataResponse();result.info=self.info;return result
            def kernel(self,request):
                self.calls.append(request.version_label)
                result=ApiGetKernelResponse();result.metadata=self.meta;result.blob=self.blob;return result
        source=(root/'kernel/main.py').read_text();expected=hashlib.sha256(source.encode()).hexdigest()
        kwargs={'version':1,'expected_source_hash':expected,'expected_ids':{'dataset_id':123,'kernel_id':456}}
        api=SDKAPI(source);evidence=runner.read_remote_privacy(api,runner.DATASET_REF,runner.KERNEL_REF,**kwargs)
        checks['official_sdk_exact_version_source_identity_positive']=evidence['kernel_version']==1 and api.calls==['v1']
        for field,value in [('ref','foreign/kernel'),('current_version_number',99),('id',999),
            ('competition_data_sources',['foreign']),('kernel_data_sources',['foreign']),
            ('model_data_sources',['foreign']),('machine_shape','NvidiaTeslaP100')]:
            api=SDKAPI(source);setattr(api.meta,field,value)
            try:runner.read_remote_privacy(api,runner.DATASET_REF,runner.KERNEL_REF,**kwargs);passed=False
            except ValueError:passed=True
            checks['remote_'+field+'_rejected']=passed
        api=SDKAPI('unreviewed code')
        try:runner.read_remote_privacy(api,runner.DATASET_REF,runner.KERNEL_REF,**kwargs);checks['remote_source_sha_rejected']=False
        except ValueError:checks['remote_source_sha_rejected']=True
        bad=SDKAPI('unreviewed code');bad.meta.current_version_number=99
        bad.meta.ref='foreign/kernel';bad.meta.machine_shape='NvidiaTeslaP100';bad.meta.kernel_data_sources=['foreign']
        # The preceding implementation checked only these four fields. This
        # literal old-behavior mutant admits the hostile SDK fixture.
        checks['old_remote_verifier_mutant_admits_wrong_version_source']=bool(bad.meta.is_private is True and not bad.meta.enable_gpu and not bad.meta.enable_tpu and bad.meta.dataset_data_sources==[runner.DATASET_REF])
        overflow=root/'overflow.json'
        for name,number in [('positive','1e10000'),('negative','-1e10000'),('nan','NaN'),('infinity','Infinity')]:
            overflow.write_text('{"nested":[{"array":['+number+']}]}')
            try:runner.read_json(overflow);checks['nested_'+name+'_overflow_rejected']=False
            except ValueError:checks['nested_'+name+'_overflow_rejected']=True
        overflow.write_text('{"nested":[1e10000]}')
        checks['old_json_parser_mutant_emits_infinity']=not math.isfinite(json.loads(overflow.read_text())['nested'][0])
        download=root/'download-fixture';comparison=output_fixture(root,download)
        text=(comparison/'report.json').read_text().strip()
        (comparison/'report.json').write_text(text[:-1]+',"economic_metric":1e10000}\n')
        refresh_artifact_manifest(root,comparison)
        try:runner.verify_download(root,download);checks['hash_matching_overflow_report_rejected']=False
        except ValueError:checks['hash_matching_overflow_report_rejected']=True
        with patch.object(runner,'read_json',lambda path:json.loads(path.read_text())):
            checks['old_json_mutant_marks_overflow_download_loadable']=runner.verify_download(root,download)['model_loading_permitted_after_hash_verification'] is True
        for index,name in enumerate(('catboost_calibration.json','logistic_calibration.json',
            'catboost_policy_selection.json','logistic_policy_selection.json','development_selection.json',
            'feature_order.json','registration.json')):
            destination=root/f'json-omission-{index}';comparison=output_fixture(root,destination)
            (comparison/name).write_text('{"nested":[{"metric":1e10000}]}')
            refresh_artifact_manifest(root,comparison)
            try:runner.verify_download(root,destination);checks['all_json_'+name+'_overflow_rejected']=False
            except ValueError:checks['all_json_'+name+'_overflow_rejected']=True
        previous_verify,previous_source=previous_download_verifier()
        extra_json_cases=[('comparison_extra','comparison/extra.json'),
                          ('comparison_nested','comparison/nested/extra.json'),
                          ('outside_root','outside.json'),
                          ('outside_nested','remote/diagnostics/extra.JSON')]
        for name,relative in extra_json_cases:
            destination=root/f'undeclared-json-{name}';output_fixture(root,destination)
            extra=destination/relative;extra.parent.mkdir(parents=True,exist_ok=True)
            extra.write_text('{"nested":[{"metric":1e10000}]}')
            checks['actual_previous_verifier_'+name+'_accepted']=previous_verify(root,destination)['model_loading_permitted_after_hash_verification'] is True
            try:runner.verify_download(root,destination);checks['all_downloaded_json_'+name+'_rejected']=False
            except ValueError:checks['all_downloaded_json_'+name+'_rejected']=True
            checks['failed_recheck_'+name+'_leaves_no_success_receipt']=not (destination/'verified-download.json').exists()
        destination=root/'finite-extra';comparison=output_fixture(root,destination)
        (comparison/'extra.json').write_text('{"finite":1}')
        try:runner.verify_download(root,destination);checks['finite_undeclared_comparison_artifact_rejected']=False
        except ValueError:checks['finite_undeclared_comparison_artifact_rejected']=True
        destination=root/'operational-output';output_fixture(root,destination)
        diagnostics=destination/'remote/diagnostics';diagnostics.mkdir(parents=True)
        (diagnostics/'finite.JSON').write_text('{"phase":"completed","metric":0.5}')
        (destination/'progress.log').write_text('remote phase log\n')
        (destination/'stdout.txt').write_text('remote stdout\n')
        checks['finite_operational_json_logs_and_stdout_accepted']=runner.verify_download(root,destination)['model_loading_permitted_after_hash_verification'] is True
        for label,is_directory in [('file',False),('directory',True)]:
            destination=root/f'symlink-{label}';output_fixture(root,destination)
            target=diagnostics if is_directory else diagnostics/'finite.JSON'
            (destination/'linked').symlink_to(target,target_is_directory=is_directory)
            checks['actual_previous_verifier_external_'+label+'_symlink_accepted']=previous_verify(root,destination)['model_loading_permitted_after_hash_verification'] is True
            try:runner.verify_download(root,destination);checks['external_'+label+'_symlink_rejected']=False
            except ValueError:checks['external_'+label+'_symlink_rejected']=True
            checks['symlink_'+label+'_failed_recheck_leaves_no_success_receipt']=not (destination/'verified-download.json').exists()
        destination=root/'old-stale-receipt';comparison=output_fixture(root,destination)
        previous_verify(root,destination);(comparison/'report.md').write_text('tampered')
        try:previous_verify(root,destination);checks['actual_previous_verifier_stale_success_after_hash_failure']=False
        except ValueError:checks['actual_previous_verifier_stale_success_after_hash_failure']=(destination/'verified-download.json').exists()
        try:runner.verify_download(root,destination);checks['recheck_changed_hash_rejected']=False
        except ValueError:checks['recheck_changed_hash_rejected']=True
        checks['recheck_changed_hash_clears_stale_success_receipt']=not (destination/'verified-download.json').exists()
        cases=[('empty',lambda p:{'pass':True}),
               ('wrong_schema',lambda p:{**p,'schema':'unknown'}),
               ('missing_model',lambda p:{**p,'models':{'logistic':p['models']['logistic']}}),
               ('false_model',lambda p:{**p,'models':{**p['models'],'logistic':{**p['models']['logistic'],'pass':False}}}),
               ('false_decisions',lambda p:{**p,'models':{**p['models'],'catboost':{**p['models']['catboost'],'decisions_match':False}}}),
               ('wrong_count',lambda p:{**p,'rows':p['rows']-1}),
               ('error_above_tolerance',lambda p:{**p,'models':{**p['models'],'catboost':{**p['models']['catboost'],'max_probability_error':1e-8}}})]
        for index,(name,change) in enumerate(cases):
            destination=root/f'parity-omission-{index}';comparison=output_fixture(root,destination)
            parity=change(runner.read_json(comparison/'saved_inference_parity.json'))
            runner.write_json(comparison/'saved_inference_parity.json',parity)
            report=runner.read_json(comparison/'report.json');report['saved_inference_parity']=parity
            runner.write_json(comparison/'report.json',report);refresh_artifact_manifest(root,comparison)
            try:runner.verify_download(root,destination);checks['parity_'+name+'_rejected']=False
            except ValueError:checks['parity_'+name+'_rejected']=True
            if name in {'empty','false_model'}:
                checks['old_parity_mutant_'+name+'_accepted']=parity.get('pass') is True
        destination=root/'contradictory-report';comparison=output_fixture(root,destination)
        report=runner.read_json(comparison/'report.json');report['saved_inference_parity']['pass']=False
        runner.write_json(comparison/'report.json',report);refresh_artifact_manifest(root,comparison)
        try:runner.verify_download(root,destination);checks['contradictory_embedded_report_parity_rejected']=False
        except ValueError:checks['contradictory_embedded_report_parity_rejected']=True
        destination=root/'missing-decision-row';comparison=output_fixture(root,destination)
        lines=(comparison/'logistic_decisions.csv').read_text().splitlines()
        (comparison/'logistic_decisions.csv').write_text('\n'.join(lines[:-1])+'\n');refresh_artifact_manifest(root,comparison)
        try:runner.verify_download(root,destination);checks['decision_population_row_missing_rejected']=False
        except ValueError:checks['decision_population_row_missing_rejected']=True
        contract=root/'dataset/contract_training_schema.py';original=contract.read_bytes()
        contract.write_text("ASSETS=()\nFEATURES=()\nCOLUMNS=('wrong',)\nMANIFEST_SCHEMA='wrong'\n")
        try:runner.admit_bundle(root/'dataset');checks['broken_contract_isolated_admission_rejected']=False
        except ValueError:checks['broken_contract_isolated_admission_rejected']=True
        contract.write_bytes(original)
        contract=root/'dataset/contract_training_schema.py';saved=contract.read_bytes();contract.unlink()
        try:runner.verify_package(root);checks['missing_contract_package_file_rejected']=False
        except ValueError:checks['missing_contract_package_file_rejected']=True
        contract.write_bytes(saved)
    finally:
        fixture.doCleanups()
    output.parent.mkdir(parents=True,exist_ok=True)
    result={'schema':'otc_kaggle_delivery_eval_v1','pass':all(checks.values()),'checks':checks,
            'threshold':'all checks must pass','fixtures':'offline fabricated fixtures only; no Kaggle requests',
            'previous_download_verifier_sha256':hashlib.sha256(previous_source.encode()).hexdigest()}
    (output.parent/'previous_download_verifier.py').write_text(previous_source)
    runner.write_json(output,result);print(json.dumps(result,sort_keys=True))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--sdk-runtime',type=Path,default=Path('/tmp/binary-training/kaggle-runtime'))
    args=parser.parse_args();raise SystemExit(0 if evaluate(args.output,args.sdk_runtime)['pass'] else 1)
