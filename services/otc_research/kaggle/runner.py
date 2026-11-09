"""Private, CPU-only Kaggle delivery for the fixed received-price experiment.

The official Kaggle client performs uploads/downloads. Gate tests never import it.
No credentials enter the package; remote results are hashed before model loading.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path
import re
import sys

OWNER = 'saviourakalia'
DATASET_SLUG = 'otc-received-proxy-v1-20261107'
KERNEL_SLUG = 'otc-logistic-catboost-v1-20261107'
DATASET_REF = f'{OWNER}/{DATASET_SLUG}'
KERNEL_REF = f'{OWNER}/{KERNEL_SLUG}'
CONTRACT_ALIASES = {'contract_init.py':'__init__.py', 'contract_records.py':'records.py',
                    'contract_training_schema.py':'training_schema.py'}
PAYLOAD = ('input.csv', 'manifest.json', 'training.py', 'requirements.txt', *CONTRACT_ALIASES)
DATASET_FILES = frozenset((*PAYLOAD, 'package-manifest.json', 'dataset-metadata.json'))
KERNEL_FILES = frozenset(('main.py', 'kernel-metadata.json'))
REQUIRED_OUTPUTS = frozenset(('catboost.cbm','logistic.joblib','preprocessor.joblib',
    'catboost_calibration.json','logistic_calibration.json','feature_order.json',
    'dataset_manifest.json','registration.json','development_selection.json',
    'catboost_policy_selection.json','logistic_policy_selection.json',
    'catboost_decisions.csv','logistic_decisions.csv','saved_inference_parity.json',
    'report.json','report.md'))
MAX_PACKAGE_BYTES = 40 * 1024 * 1024
SECRET_PATTERN = re.compile(rb'KGAT_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY-----')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n')


def read_json(path: Path):
    def finite_float(value):
        result=float(value)
        if not math.isfinite(result):raise ValueError('Nonfinite JSON number')
        return result
    return json.loads(path.read_text(), parse_float=finite_float,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def new_directory(path: Path) -> Path:
    path = path.resolve()
    for parent in (path, *path.parents):
        if (parent/'.git').is_file() or ((parent/'.git').is_dir() and any((parent/'.git').iterdir())):
            raise ValueError('Kaggle artifacts must be outside Git repositories')
        if (parent/'HEAD').is_file() and (parent/'objects').is_dir() and (parent/'refs').is_dir():
            raise ValueError('Kaggle artifacts must be outside Git repositories')
    if path.exists() and any(path.iterdir()):
        raise ValueError('Kaggle package/run directory must be new or empty')
    path.mkdir(parents=True, exist_ok=True)
    return path


def whitelist(folder: Path, allowed: frozenset):
    found = frozenset(p.name for p in folder.iterdir())
    if found != allowed:
        raise ValueError('Upload file whitelist mismatch')
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValueError('Upload entries must be regular files, never symlinks/directories')
        if SECRET_PATTERN.search(path.read_bytes()):
            raise ValueError(f'Secret-shaped content in upload file {path.name}')
    if sum(p.stat().st_size for p in folder.iterdir()) > MAX_PACKAGE_BYTES:
        raise ValueError('Upload exceeds the registered 40MB package budget')


def kernel_source(hashes: dict[str, str]) -> str:
    """The kernel imports only exact verified input bytes and uses CPU."""
    return '''from pathlib import Path
import hashlib, importlib.util, json, shutil, subprocess, sys

EXPECTED = ''' + repr(hashes) + '''
ROOT = Path('/kaggle/input/''' + DATASET_SLUG + '''')
# New Kaggle mount layouts may insert an owner directory. Resolve by content,
# accepting exactly one complete matching package rather than arbitrary code.
candidates = [ROOT] if ROOT.is_dir() else []
if not candidates:
    candidates = [p.parent for p in Path('/kaggle/input').rglob('package-manifest.json')]
matching = [p for p in candidates if all((p/name).is_file() and hashlib.sha256((p/name).read_bytes()).hexdigest()==value for name,value in EXPECTED.items())]
if len(matching)!=1:
    raise ValueError('Exactly one hash-matching received-price package is required')
ROOT = matching[0]
manifest=json.loads((ROOT/'manifest.json').read_text())
if manifest['evidence_classes']!=['received_price_proxy'] or manifest.get('promotable') is not False:
    raise ValueError('This kernel admits nonpromotable received-price evidence only')
CODE = Path('/kaggle/temp/otc-code')
CONTRACTS = CODE/'contracts/otc_v1'
CONTRACTS.mkdir(parents=True,exist_ok=False)
for alias,name in {'contract_init.py': '__init__.py', 'contract_records.py': 'records.py', 'contract_training_schema.py': 'training_schema.py'}.items():
    shutil.copyfile(ROOT/alias,CONTRACTS/name)
shutil.copyfile(ROOT/'training.py',CODE/'training.py')
sys.path.insert(0,str(CODE))
subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--no-cache-dir', '-r', str(ROOT/'requirements.txt')], check=True)
spec=importlib.util.spec_from_file_location('otc_kaggle_training', CODE/'training.py')
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
result=module.run_comparison(ROOT/'input.csv', ROOT/'manifest.json', Path('/kaggle/working/comparison'), device='CPU')
print(json.dumps({'event':'kaggle_comparison_complete','status':result['status'],'promotable':False,'device':'CPU'}), flush=True)
'''


def admit_bundle(dataset: Path) -> dict:
    # Admission uses the exact copied contracts in an isolated fresh process,
    # so an already-imported local schema cannot hide a broken package.
    with tempfile.TemporaryDirectory(prefix='otc-package-admission-') as name:
        code=Path(name);boundary=code/'contracts/otc_v1';boundary.mkdir(parents=True)
        for alias,filename in CONTRACT_ALIASES.items():
            (boundary/filename).write_bytes((dataset/alias).read_bytes())
        (code/'training.py').write_bytes((dataset/'training.py').read_bytes())
        admission="import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import training;rows,manifest=training.load_inputs(Path(sys.argv[2]),Path(sys.argv[3]));training.training_admission(rows);print(json.dumps(manifest,allow_nan=False))"
        result=subprocess.run([sys.executable,'-I','-c',admission,str(code),str(dataset/'input.csv'),str(dataset/'manifest.json')],
                              cwd=code,text=True,capture_output=True)
        if result.returncode:raise ValueError('Bundled contract or dataset admission failed')
        return json.loads(result.stdout)


def prepare(matrix: Path, manifest: Path, trainer: Path, requirements: Path, output: Path, contracts_root: Path | None = None) -> dict:
    output = new_directory(output)
    dataset = output/'dataset'; kernel = output/'kernel'
    dataset.mkdir(); kernel.mkdir()
    contracts_root=contracts_root or trainer.resolve().parents[2]/'contracts/otc_v1'
    sources={'input.csv':matrix,'manifest.json':manifest,'training.py':trainer,'requirements.txt':requirements,
             **{alias:contracts_root/name for alias,name in CONTRACT_ALIASES.items()}}
    for name,source in sources.items():
        if source.is_symlink() or not source.is_file():
            raise ValueError('Package sources must be regular files')
        payload = source.read_bytes()
        if SECRET_PATTERN.search(payload):
            raise ValueError(f'Secret-shaped content in {name}')
        (dataset/name).write_bytes(payload)
    source_manifest=read_json(dataset/'manifest.json')
    if source_manifest.get('evidence_classes') != ['received_price_proxy']:
        raise ValueError('Kaggle upload admits received-price data only, never synthetic evals')
    requirements_text=(dataset/'requirements.txt').read_text().strip().splitlines()
    if not requirements_text or any(not re.fullmatch(r'[A-Za-z0-9_-]+==[0-9]+(?:\.[0-9]+)*(?:[A-Za-z0-9.]*)?', line) for line in requirements_text):
        raise ValueError('Kaggle training dependencies must be exact version pins')
    source_manifest=admit_bundle(dataset)
    hashes={name:digest(dataset/name) for name in PAYLOAD}
    package={'schema':'otc_private_kaggle_package_v1','files':hashes,'dataset_ref':DATASET_REF,
             'kernel_ref':KERNEL_REF,'private':True,'device':'CPU','promotable':False}
    write_json(dataset/'package-manifest.json',package)
    write_json(dataset/'dataset-metadata.json',{'id':DATASET_REF,'title':'OTC received proxy v1 20261107',
        'licenses':[{'name':'other'}],'description':'Private historical received-price experiment. No accepted broker contracts or profitability claim.'})
    (kernel/'main.py').write_text(kernel_source(hashes))
    write_json(kernel/'kernel-metadata.json',{'id':KERNEL_REF,'title':'OTC Logistic Catboost V1 20261107',
        'code_file':'main.py','language':'python','kernel_type':'script','is_private':True,
        'enable_gpu':False,'enable_tpu':False,'enable_internet':True,
        'dataset_sources':[DATASET_REF],'competition_sources':[],'kernel_sources':[],'model_sources':[]})
    whitelist(dataset,DATASET_FILES);whitelist(kernel,KERNEL_FILES)
    write_json(output/'delivery.json',{'schema':'otc_kaggle_delivery_v1','phase':'prepared',
        'dataset_ref':DATASET_REF,'kernel_ref':KERNEL_REF,'kernel_version':None,
        'package':package,'kernel_sha256':digest(kernel/'main.py')})
    return read_json(output/'delivery.json')


def verify_package(output: Path) -> dict:
    state=read_json(output/'delivery.json')
    if state.get('schema')!='otc_kaggle_delivery_v1' or state.get('dataset_ref')!=DATASET_REF or state.get('kernel_ref')!=KERNEL_REF:
        raise ValueError('Unregistered Kaggle delivery')
    whitelist(output/'dataset',DATASET_FILES);whitelist(output/'kernel',KERNEL_FILES)
    package=read_json(output/'dataset/package-manifest.json')
    if package!=state['package'] or set(package.get('files',{}))!=set(PAYLOAD):
        raise ValueError('Package declaration changed')
    if package.get('private') is not True or package.get('device')!='CPU' or package.get('promotable') is not False:
        raise ValueError('Package must remain private, CPU and nonpromotable')
    if any(digest(output/'dataset'/name)!=value for name,value in package['files'].items()):
        raise ValueError('Package bytes changed after preparation')
    expected={'id':KERNEL_REF,'is_private':True,'enable_gpu':False,'enable_tpu':False,
              'dataset_sources':[DATASET_REF],'competition_sources':[],'kernel_sources':[],'model_sources':[]}
    metadata=read_json(output/'kernel/kernel-metadata.json')
    if metadata.get('is_private') is not True or metadata.get('enable_gpu') is not False or metadata.get('enable_tpu') is not False or any(metadata.get(key)!=value for key,value in expected.items()) or set(metadata)!=set(expected)|{'title','code_file','language','kernel_type','enable_internet'}:
        raise ValueError('Kernel scope or privacy changed')
    if metadata['code_file']!='main.py' or metadata['language']!='python' or metadata['kernel_type']!='script' or metadata['enable_internet'] is not True:
        raise ValueError('Unsupported kernel configuration')
    if digest(output/'kernel/main.py')!=state['kernel_sha256']:
        raise ValueError('Kernel source changed after preparation')
    dataset_metadata=read_json(output/'dataset/dataset-metadata.json')
    if dataset_metadata.get('id')!=DATASET_REF or set(dataset_metadata)!={'id','title','licenses','description'}:
        raise ValueError('Dataset metadata changed')
    return state


def api_client(runtime: Path | None = None):
    if runtime:
        sys.path.insert(0,str(runtime.resolve()))
    # Credentials are deliberately not arguments and are never persisted here.
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();api.authenticate()
    if api.config_values.get(api.CONFIG_NAME_USER)!=OWNER:
        raise ValueError('Authenticated Kaggle owner does not match the registered account')
    return api


def positive_integer(value, name: str) -> int:
    if type(value) is not int or value<=0:raise ValueError(f'{name} must be a positive integer')
    return value


def read_remote_privacy(api, dataset_ref: str, kernel_ref: str | None = None, *,
                        version: int | None = None, expected_source_hash: str | None = None,
                        expected_ids: dict | None = None) -> dict:
    if dataset_ref!=DATASET_REF or kernel_ref not in {None,KERNEL_REF}:
        raise ValueError('Remote resource reference is outside the registration')
    if kernel_ref:
        positive_integer(version,'Kernel version')
        if not isinstance(expected_source_hash,str) or not re.fullmatch('[0-9a-f]{64}',expected_source_hash):
            raise ValueError('Exact remote kernel source hash is required')
    from kagglesdk.datasets.types.dataset_api_service import ApiGetDatasetMetadataRequest
    from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelRequest
    with api.build_kaggle_client() as client:
        request=ApiGetDatasetMetadataRequest();request.owner_slug=OWNER;request.dataset_slug=DATASET_SLUG
        result=client.datasets.dataset_api_client.get_dataset_metadata(request)
        info=result.info
        if result.error_message or info is None or info.is_private is not True:
            raise ValueError('Remote dataset privacy is not verified private')
        dataset_id=positive_integer(info.dataset_id,'Dataset ID')
        if info.owner_user!=OWNER or info.dataset_slug!=DATASET_SLUG:
            raise ValueError('Remote dataset identity changed')
        if expected_ids and positive_integer(expected_ids.get('dataset_id'),'Expected dataset ID')!=dataset_id:
            raise ValueError('Remote dataset ID changed')
        privacy={'dataset_private':True,'dataset_ref':DATASET_REF,'dataset_id':dataset_id}
        if kernel_ref:
            request=ApiGetKernelRequest();request.user_name=OWNER;request.kernel_slug=KERNEL_SLUG
            request.version_label=f'v{version}'
            result=client.kernels.kernels_api_client.get_kernel(request)
            meta=result.metadata;blob=result.blob
            if meta is None or meta.is_private is not True or meta.enable_gpu is not False or meta.enable_tpu is not False:
                raise ValueError('Remote kernel is not private CPU without TPU/GPU')
            # author is a display name, while ref carries the account identity.
            if meta.ref!=KERNEL_REF or meta.slug!=KERNEL_SLUG:
                raise ValueError('Remote kernel identity changed')
            kernel_id=positive_integer(meta.id,'Kernel ID')
            if expected_ids and positive_integer(expected_ids.get('kernel_id'),'Expected kernel ID')!=kernel_id:
                raise ValueError('Remote kernel ID changed')
            if type(meta.current_version_number) is not int or meta.current_version_number!=version:
                raise ValueError('Remote kernel version does not match the pinned version')
            if (meta.dataset_data_sources!=[DATASET_REF] or meta.competition_data_sources!=[]
                    or meta.kernel_data_sources!=[] or meta.model_data_sources!=[]):
                raise ValueError('Remote kernel source scope widened')
            # The official SDK declares no machine shape as its default CPU.
            # Every named supported shape is a GPU/TPU, so only empty is admitted.
            if meta.machine_shape!='':
                raise ValueError('Remote kernel machine shape is not default CPU')
            if blob is None or not isinstance(blob.source,str) or hashlib.sha256(blob.source.encode()).hexdigest()!=expected_source_hash:
                raise ValueError('Remote kernel source differs from the reviewed package')
            privacy.update(kernel_private=True,kernel_ref=KERNEL_REF,kernel_id=kernel_id,
                           kernel_version=version,source_sha256=expected_source_hash,
                           requested_version_label=request.version_label,machine_shape='default_cpu')
    return privacy


def preserve_version_evidence(state: dict, evidence: dict) -> None:
    versions=state.setdefault('verified_versions',{})
    key=str(evidence['kernel_version'])
    if key in versions and versions[key]!=evidence:
        raise ValueError('Previously verified immutable kernel version changed')
    versions[key]=evidence
    state['privacy']=evidence


def collect_refs(fetch_page) -> list[str]:
    token='';seen=set();refs=set()
    for _ in range(100):
        items,next_token=fetch_page(token)
        refs.update(items)
        if not next_token:return sorted(refs)
        if next_token in seen:raise ValueError('Owned-resource pagination did not advance')
        seen.add(next_token);token=next_token
    raise ValueError('Owned-resource listing exceeded its bounded pagination budget')


def owned_resources(api) -> dict:
    from kagglesdk.datasets.types.dataset_api_service import ApiListDatasetsRequest
    from kagglesdk.datasets.types.dataset_enums import DatasetSelectionGroup
    from kagglesdk.kernels.types.kernels_api_service import ApiListKernelsRequest
    from kagglesdk.kernels.types.kernels_enums import KernelsListViewType
    with api.build_kaggle_client() as client:
        def datasets(token):
            request=ApiListDatasetsRequest();request.group=DatasetSelectionGroup.DATASET_SELECTION_GROUP_MY
            request.page_size=100;request.page_token=token
            response=client.datasets.dataset_api_client.list_datasets(request)
            return [item.ref for item in response.datasets],response.next_page_token
        def kernels(token):
            request=ApiListKernelsRequest();request.group=KernelsListViewType.PROFILE;request.user=OWNER
            request.page_size=100;request.page_token=token
            response=client.kernels.kernels_api_client.list_kernels(request)
            return [item.ref for item in response.kernels],response.next_page_token
        return {'datasets':collect_refs(datasets),'kernels':collect_refs(kernels)}


def upload(output: Path, api) -> dict:
    state=verify_package(output)
    if state['phase']!='prepared':
        raise ValueError('Delivery is already uploaded; never overwrite an existing dataset')
    # Kaggle conceals missing resources with 403. Complete authenticated MY /
    # PROFILE listings establish absence; a direct 403 never does.
    existing=owned_resources(api)
    if DATASET_REF in existing['datasets'] or KERNEL_REF in existing['kernels']:
        raise ValueError('Registered dataset/kernel already exists; cannot overwrite it')
    state['preupload_owned_resources']=existing
    state['phase']='dataset_upload_submitting';write_json(output/'delivery.json',state)
    result=api.dataset_create_new(str(output/'dataset'),public=False,quiet=True,convert_to_csv=False)
    if result.error or result.ref!=DATASET_REF:
        raise ValueError('Private dataset creation did not return the registered reference')
    state['phase']='dataset_uploaded';state['dataset_url']=result.url
    write_json(output/'delivery.json',state)
    progress(output,'dataset_uploaded')
    return state


def save_private_kernel(output: Path, api) -> dict:
    state=verify_package(output)
    if state['phase']!='dataset_uploaded':raise ValueError('Save requires the new dataset')
    dataset=read_remote_privacy(api,DATASET_REF)
    status=api.dataset_status(DATASET_REF)
    if str(status).lower() not in {'ready','complete'}:
        raise ValueError('Dataset processing is not ready; check again before saving')
    if KERNEL_REF in owned_resources(api)['kernels']:
        raise ValueError('Registered kernel already exists; cannot overwrite it')
    state['phase']='kernel_save_submitting';write_json(output/'delivery.json',state)
    response=api.kernels_push(str(output/'kernel'),no_run=True)
    if response.error or response.ref!=KERNEL_REF:
        raise ValueError('Private kernel save failed')
    version=positive_integer(response.version_number,'Saved kernel version')
    kernel_id=positive_integer(response.kernel_id,'Saved kernel ID')
    state.update(phase='kernel_saved_unverified',kernel_version=version,kernel_id=kernel_id,
                 dataset_id=dataset['dataset_id'],kernel_url=response.url)
    write_json(output/'delivery.json',state)
    evidence=read_remote_privacy(api,DATASET_REF,KERNEL_REF,version=version,
        expected_source_hash=state['kernel_sha256'],expected_ids=state)
    preserve_version_evidence(state,evidence)
    state['phase']='saved_private';write_json(output/'delivery.json',state)
    progress(output,'saved_private')
    return state


def launch(output: Path, api) -> dict:
    state=verify_package(output)
    if state['phase']!='saved_private':raise ValueError('Launch requires prior verified private quick save')
    evidence=read_remote_privacy(api,DATASET_REF,KERNEL_REF,version=state['kernel_version'],
        expected_source_hash=state['kernel_sha256'],expected_ids=state)
    preserve_version_evidence(state,evidence)
    state['phase']='kernel_launch_submitting';write_json(output/'delivery.json',state)
    response=api.kernels_push(str(output/'kernel'),timeout='3600',no_run=False)
    if response.error or response.ref!=KERNEL_REF or positive_integer(response.kernel_id,'Launched kernel ID')!=state['kernel_id']:
        raise ValueError('Kernel run did not preserve the registered identity')
    version=positive_integer(response.version_number,'Launched kernel version')
    if version!=state['kernel_version']+1:
        raise ValueError('Kernel launch version is not the immediate successor of the reviewed save')
    state.update(phase='launched_unverified',kernel_version=version)
    write_json(output/'delivery.json',state)
    evidence=read_remote_privacy(api,DATASET_REF,KERNEL_REF,version=version,
        expected_source_hash=state['kernel_sha256'],expected_ids=state)
    preserve_version_evidence(state,evidence)
    state['phase']='launched';write_json(output/'delivery.json',state)
    progress(output,'launched')
    return state


def progress(output: Path, status: str, **extra) -> dict:
    event={'event':'Binary OTC Kaggle comparison','utc':datetime.now(timezone.utc).isoformat(),
           'status':status,'percent_done':100 if status=='COMPLETE' else None,
           'eta_seconds':0 if status=='COMPLETE' else None,**extra}
    with (output/'progress.log').open('a') as handle:handle.write(json.dumps(event,sort_keys=True)+'\n')
    print(json.dumps(event,sort_keys=True),flush=True)
    return event


def snapshot(output: Path, api) -> dict:
    state=verify_package(output)
    if state['phase']!='launched':
        return progress(output,state['phase'])
    evidence=read_remote_privacy(api,DATASET_REF,KERNEL_REF,version=state['kernel_version'],
        expected_source_hash=state['kernel_sha256'],expected_ids=state)
    preserve_version_evidence(state,evidence)
    response=api.kernels_status(f'{KERNEL_REF}/{state["kernel_version"]}')
    status=response.status.name
    state['last_status']=status
    # Failure text can include kernel logs; record the presence, never arbitrary text.
    state['failure_message_present']=bool(response.failure_message)
    write_json(output/'delivery.json',state)
    return progress(output,status,failure_message_present=state['failure_message_present'])


def validate_parity(parity: dict, input_ids: list[str], decisions: dict[str,list[str]]) -> None:
    if not isinstance(parity,dict) or set(parity)!={'schema','rows','models','pass'} or parity['schema']!='otc_saved_inference_parity_v1':
        raise ValueError('Remote saved-model parity schema is incomplete')
    total=positive_integer(parity['rows'],'Parity rows')
    if total!=len(input_ids) or len(set(input_ids))!=total or parity['pass'] is not True:
        raise ValueError('Remote parity population or overall verdict is inconsistent')
    models=parity['models']
    if not isinstance(models,dict) or set(models)!={'logistic','catboost'}:
        raise ValueError('Remote parity needs exactly both registered models')
    for name,entry in models.items():
        if not isinstance(entry,dict) or set(entry)!={'rows','max_probability_error','decisions_match','pass'}:
            raise ValueError('Remote model parity entry is incomplete')
        if positive_integer(entry['rows'],'Model parity rows')!=total:
            raise ValueError('Remote model parity row count differs from input')
        error=entry['max_probability_error']
        if type(error) not in {int,float} or error<0 or error>1e-12 or not math.isfinite(error):
            raise ValueError('Remote model probability parity exceeds tolerance')
        if entry['decisions_match'] is not True or entry['pass'] is not True:
            raise ValueError('Remote model decisions or verdict contradict successful parity')
        actual=decisions[name]
        if len(actual)!=total or len(set(actual))!=total or set(actual)!=set(input_ids):
            raise ValueError('Remote decision CSV population contradicts parity/input')


def csv_ids(path: Path) -> list[str]:
    with path.open(newline='') as stream:
        reader=csv.DictReader(stream)
        if reader.fieldnames is None or 'opportunity_id' not in reader.fieldnames:
            raise ValueError('Decision/input CSV needs opportunity IDs')
        ids=[]
        for row in reader:
            if None in row or any(value is None for value in row.values()) or not row['opportunity_id']:
                raise ValueError('Decision/input CSV is malformed')
            ids.append(row['opportunity_id'])
        return ids


def downloaded_files(downloaded: Path) -> list[Path]:
    """Inventory the complete download without following links or special files."""
    if downloaded.is_symlink() or not downloaded.is_dir():
        raise ValueError('Download root must be a regular directory, never a symlink')
    pending=[downloaded];files=[]
    while pending:
        for path in pending.pop().iterdir():
            if path.is_symlink():
                raise ValueError('Downloaded entries must never be symlinks')
            if path.is_dir():pending.append(path)
            elif path.is_file():files.append(path)
            else:raise ValueError('Downloaded entries must be regular files or directories')
    return files


def discard_download_receipt(downloaded: Path) -> None:
    """A failed recheck must never retain a previous positive loading receipt."""
    if downloaded.is_symlink() or not downloaded.is_dir():
        raise ValueError('Download root must be a regular directory, never a symlink')
    receipt=downloaded/'verified-download.json'
    if receipt.is_symlink() or (receipt.exists() and not receipt.is_file()):
        raise ValueError('Download verification receipt must be a regular file')
    if receipt.exists():
        try:read_json(receipt)
        finally:receipt.unlink()


def verify_download(output: Path, downloaded: Path) -> dict:
    discard_download_receipt(downloaded)
    state=verify_package(output)
    files=downloaded_files(downloaded)
    candidates=[path for path in files if path.name=='artifact_manifest.json']
    if len(candidates)!=1:raise ValueError('Exactly one comparison artifact manifest is required')
    root=candidates[0].parent
    if {path.name for path in root.iterdir()}!=REQUIRED_OUTPUTS|{'artifact_manifest.json'}:
        raise ValueError('Remote artifact inventory mismatch')
    manifest=read_json(candidates[0])
    hashes=manifest.get('files')
    if not isinstance(hashes,dict) or set(hashes)!=REQUIRED_OUTPUTS or manifest.get('schema')!='otc_training_artifacts_v1' or manifest.get('promotable') is not False:
        raise ValueError('Malformed or incomplete remote artifact manifest')
    for name, expected in hashes.items():
        path=root/name
        if not isinstance(expected,dict) or set(expected)!={'sha256','bytes'} or type(expected['bytes']) is not int or expected['bytes']<=0 or Path(name).name!=name or path.is_symlink() or not path.is_file() or digest(path)!=expected['sha256'] or path.stat().st_size!=expected['bytes']:
            raise ValueError('Remote artifact digest mismatch or unsafe filename')
    if manifest.get('input_sha256')!=state['package']['files']['input.csv'] or manifest.get('code_sha256')!=state['package']['files']['training.py']:
        raise ValueError('Remote artifact manifest does not match uploaded input/source')
    # Inspect every JSON in the entire download, including nested files outside
    # comparison. Operational logs may sit outside the exact artifact subtree.
    decoded_files={path:read_json(path) for path in files if path.suffix.lower()=='.json'}
    decoded={name:decoded_files[root/name] for name in hashes if name.endswith('.json')}
    parity=decoded['saved_inference_parity.json']
    input_ids=csv_ids(output/'dataset/input.csv')
    decisions={name:csv_ids(root/f'{name}_decisions.csv') for name in ('logistic','catboost')}
    validate_parity(parity,input_ids,decisions)
    if digest(root/'dataset_manifest.json')!=state['package']['files']['manifest.json']:
        raise ValueError('Remote dataset manifest changed')
    report=decoded['report.json']
    validate_parity(report.get('saved_inference_parity'),input_ids,decisions)
    if report.get('saved_inference_parity')!=parity:
        raise ValueError('Remote report parity proof contradicts the parity artifact')
    if report.get('status')!='DONE' or report.get('promotable') is not False or report.get('device')!='CPU':
        raise ValueError('Remote comparison did not complete the registered nonpromotable CPU run')
    if report.get('input_sha256')!=state['package']['files']['input.csv'] or report.get('code_sha256')!=state['package']['files']['training.py'] or report.get('manifest_sha256')!=state['package']['files']['manifest.json']:
        raise ValueError('Remote report does not match exact uploaded input/source')
    result={'schema':'otc_kaggle_verified_download_v1','kernel_ref':KERNEL_REF,
        'kernel_version':state['kernel_version'],'artifacts_sha256':{name:entry['sha256'] for name,entry in hashes.items()},'report_path':str(root/'report.json'),
        'input_and_source_match':True,'model_loading_permitted_after_hash_verification':True}
    write_json(downloaded/'verified-download.json',result)
    return result


def fetch(output: Path, api) -> dict:
    if snapshot(output,api)['status']!='COMPLETE':raise ValueError('Fetch requires a completed pinned kernel version')
    state=verify_package(output);target=new_directory(output/'downloaded')
    api.kernels_output(f'{KERNEL_REF}/{state["kernel_version"]}',str(target),quiet=True)
    return verify_download(output,target)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','upload','save','launch','status','fetch','verify-package'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--sdk-runtime',type=Path)
    parser.add_argument('--matrix',type=Path);parser.add_argument('--manifest',type=Path)
    parser.add_argument('--trainer',type=Path);parser.add_argument('--requirements',type=Path)
    parser.add_argument('--contracts-root',type=Path)
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            if any(getattr(args,name) is None for name in ('matrix','manifest','trainer','requirements')):
                raise ValueError('Prepare needs matrix, manifest, trainer and requirements')
            result=prepare(args.matrix,args.manifest,args.trainer,args.requirements,args.output,args.contracts_root)
        elif args.action=='verify-package':result=verify_package(args.output)
        else:
            client=api_client(args.sdk_runtime)
            result={'upload':upload,'save':save_private_kernel,'launch':launch,'status':snapshot,'fetch':fetch}[args.action](args.output,client)
        print(json.dumps(result,sort_keys=True,allow_nan=False),flush=True)
    except Exception as error:
        # Exceptions from SDKs may contain HTTP data or credentials. Never print repr.
        print(json.dumps({'status':'BLOCKED','error_type':type(error).__name__}),file=sys.stderr,flush=True)
        return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
