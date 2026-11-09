"""Compile original model procedure with registered literal UTC dates only."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import time
from contracts.otc_fresh_v1 import canonical,digest,sha256,strict_json,validate_registration

ROOT=Path(__file__).resolve().parents[2]

def source_plan(root=ROOT):
    root=Path(root)
    lock=strict_json((root/'original-source-lock.json').read_text())
    for name,value in lock['files'].items():
        if sha256(root/name)!=value:raise ValueError('Original source bytes changed: '+name)
    owned=('contracts/otc_fresh_v1.py','services/otc_fresh_compare/compiler.py',
           'services/otc_fresh_compare/export.py','services/otc_fresh_compare/source_chain.py',
           'services/otc_fresh_compare/census.py','services/otc_fresh_compare/identity_ledger.py')
    plan={'schema':'otc_static_fresh_compiler_plan_v1',
          'original_source_lock_sha256':sha256(root/'original-source-lock.json'),
          'original_source_frozen_at_ms':lock['frozen_at_ms'],
          'original_files':lock['files'],
          'original_training_sha256':lock['files']['services/otc_research/training.py'],
          'requirements_sha256':sha256(root/'services/otc_research/training_requirements.txt'),
          'compiler_files':{name:sha256(root/name) for name in owned},
          'date_input':'immutable registered seven-day UTC chronology only',
          'outcome_inputs':False,'original_model_procedure_changed':False}
    plan['plan_sha256']=digest(plan)
    return plan

def freeze_plan(output,root=ROOT):
    output=Path(output)
    if output.exists():raise ValueError('Compiler plan is immutable; choose a new file')
    plan=source_plan(root)
    plan['compiler_prepared_at_ms']=time.time_ns()//1000000
    plan['plan_sha256']=digest({key:value for key,value in plan.items() if key!='plan_sha256'})
    output.write_text(canonical(plan)+'\n')
    return plan

def validate_plan(path,root=ROOT):
    plan=strict_json(Path(path).read_text());unlocked=dict(plan);lock=unlocked.pop('plan_sha256',None)
    if lock!=digest(unlocked):raise ValueError('Compiler plan changed')
    current=source_plan(root)
    for key in current:
        if key!='plan_sha256' and plan.get(key)!=current[key]:raise ValueError('Frozen compiler/source changed: '+key)
    return plan

def model_ast(source):
    """Outcome-independent proof: every original model/data/policy function remains exact."""
    tree=ast.parse(source)
    allowed={'sha256','load_inputs'}
    wording={'fresh_exploratory_development_price_proxy':'spent_historical_price_proxy',
        'fresh diagnostic development only; never untouched confirmation or capital permission':'spent diagnostic only; never promotion evidence',
        'fresh_exploratory_development_or_synthetic_eval':'spent_historical_development_or_synthetic_eval',
        'Fresh development partitions cannot establish untouched confirmation or executable-contract profitability.':'All historical partitions are spent; outputs cannot establish future or executable-contract profitability.',
        'This fresh development cohort cannot establish untouched confirmation, capital permission or executable-contract profitability.':'This spent historical cohort cannot establish executable-contract or future profitability.'}
    class RestoreWording(ast.NodeTransformer):
        def visit_Constant(self,node):
            if isinstance(node.value,str):
                for changed,original in wording.items():node.value=node.value.replace(changed,original)
            return node
    tree=RestoreWording().visit(tree)
    result={node.name:ast.dump(node,include_attributes=False) for node in tree.body
            if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name not in allowed}
    module=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)):continue
        if isinstance(node,ast.Assign) and any(isinstance(name,ast.Name) and name.id=='LIMITS' for name in node.targets):continue
        module.append(ast.dump(node,include_attributes=False))
    result['__module_constants_and_imports__']=canonical(module)
    return result

def compile_trainer(registration,plan_path,output,root=ROOT):
    root=Path(root);record=strict_json(Path(registration).read_text())
    limits=validate_registration(record);plan=validate_plan(plan_path,root)
    if type(plan.get('original_source_frozen_at_ms')) is not int or plan['original_source_frozen_at_ms']>=record['start_ms']:
        raise ValueError('Original model source must be frozen before collection start')
    original=Path(root/'services/otc_research/training.py').read_text()
    # Every recorded original research dependency must agree. Additional recorder
    # source files can be registered independently, but never alias these bytes.
    for name,value in plan['original_files'].items():
        if record['research_code_files'].get(name)!=value:raise ValueError('Registration did not freeze original research file: '+name)
    spec={'registration_sha256':record['registration_sha256'], 'limits':[list(item) for item in limits],
          'compiler_plan_sha256':plan['plan_sha256'], 'original_training_sha256':plan['original_training_sha256']}
    tree=ast.parse(original)
    target=next(node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(name,ast.Name) and name.id=='LIMITS' for name in node.targets))
    lines=original.splitlines(keepends=True)
    literal='LIMITS = {\n'+''.join(f'    {name!r}: ({start}, {end}),\n' for name,start,end in limits)+'}\n'
    source=''.join(lines[:target.lineno-1])+literal+''.join(lines[target.end_lineno:])
    old="return hashlib.file_digest(source, 'sha256').hexdigest()"
    if source.count(old)!=1:raise ValueError('Original streaming hash marker changed')
    source=source.replace(old,"value=hashlib.sha256()\n        for block in iter(lambda: source.read(1024*1024), b''):\n            value.update(block)\n        return value.hexdigest()")
    marker='    evidence_class=validate_manifest(manifest)'
    if source.count(marker)!=1:raise ValueError('Original admission marker changed')
    contract_files={name:plan['original_files']['contracts/otc_v1/'+name] for name in ('__init__.py','records.py','training_schema.py')}
    guard="    import contracts.otc_fresh_v1 as fresh_boundary\n    if sha256(Path(fresh_boundary.__file__)) != "+repr(plan['compiler_files']['contracts/otc_fresh_v1.py'])+":\n        raise ValueError('Fresh contract source changed after compilation')\n    for filename, expected_hash in "+repr(contract_files)+".items():\n        if sha256(Path(fresh_boundary.__file__).parent/'otc_v1'/filename)!=expected_hash:\n            raise ValueError('Original shared-contract source changed after compilation')\n    fresh_boundary.validate_manifest_lock(manifest, "+repr(spec)+")\n"
    source=source.replace(marker,guard+marker)
    # Population admission protects the full grid even for callers that invoke
    # the frozen module directly rather than the export/compare command.
    marker='    return rows, manifest'
    if source.count(marker)!=1:raise ValueError('Original row-return marker changed')
    population="    expected={(asset, moment) for moment in range("+str(record['start_ms'])+", "+str(record['end_ms'])+", 120000) for asset in ASSETS}\n    if len(rows)!=len(expected) or {(row.asset,row.decision_ms) for row in rows}!=expected:\n        raise ValueError('Fresh input must retain every registered asset/grid opportunity')\n"
    source=source.replace(marker,population+marker)
    source=source.replace("'evidence':'spent_historical_price_proxy'","'evidence':'fresh_exploratory_development_price_proxy'")
    source=source.replace("'test_role':'spent diagnostic only; never promotion evidence'","'test_role':'fresh diagnostic development only; never untouched confirmation or capital permission'")
    source=source.replace("'cohort_role':'spent_historical_development_or_synthetic_eval'","'cohort_role':'fresh_exploratory_development_or_synthetic_eval'")
    source=source.replace('All historical partitions are spent; outputs cannot establish future or executable-contract profitability.',
        'Fresh development partitions cannot establish untouched confirmation or executable-contract profitability.')
    source=source.replace('This spent historical cohort cannot establish executable-contract or future profitability.',
        'This fresh development cohort cannot establish untouched confirmation, capital permission or executable-contract profitability.')
    original_ast=model_ast(original)
    if original_ast!=model_ast(source):raise ValueError('Static compilation changed original model/data/policy functions')
    output=Path(output)
    if output.exists():raise ValueError('Frozen trainer path must be new')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(source)
    proof={'schema':'otc_static_trainer_transformation_v1','registration_sha256':record['registration_sha256'],
        'compiler_plan_sha256':plan['plan_sha256'],'original_training_sha256':sha256(root/'services/otc_research/training.py'),
        'frozen_training_sha256':sha256(output),'literal_limits':spec['limits'],
        'unchanged_original_function_names':sorted(name for name in original_ast if not name.startswith('__')),
        'unchanged_model_function_ast_sha256':digest(original_ast),
        'module_constants_and_imports_unchanged':True,
        'transformation_inputs':['frozen original source','frozen compiler source','registered UTC dates'],
        'outcomes_or_metrics_used':False,'runtime_global_rebinding':False,'python_minimum':'3.10'}
    proof['original_source_frozen_at_ms']=plan['original_source_frozen_at_ms']
    proof['compiler_prepared_at_ms']=plan['compiler_prepared_at_ms']
    output.with_suffix('.proof.json').write_text(canonical(proof)+'\n')
    output.with_suffix('.plan.json').write_text(canonical(plan)+'\n')
    return proof

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('freeze-plan','compile'))
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--registration',type=Path);parser.add_argument('--plan',type=Path)
    args=parser.parse_args()
    if args.action=='freeze-plan':result=freeze_plan(args.output)
    else:result=compile_trainer(args.registration,args.plan,args.output)
    print(canonical(result))

if __name__=='__main__':main()
