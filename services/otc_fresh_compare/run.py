"""Original comparison after the fixed registered end and complete source chain."""
from __future__ import annotations
import argparse
from pathlib import Path
import time
from contracts.otc_fresh_v1 import canonical,strict_json,validate_registration
from .compiler import freeze_plan,compile_trainer
from .source_chain import wait_for_chain
from .export import export_matrix,compare

def run_registered(registration,chain,output):
    registration,chain,output=Path(registration),Path(chain),Path(output).resolve()
    record=strict_json(registration.read_text());validate_registration(record)
    if output.exists():raise ValueError('Registered workflow output must be a new directory')
    output.mkdir(parents=True)
    status_path=output/'workflow-status.json'
    stage='compile'
    def status(state,**detail):
        value={'event':'Fixed OTC original comparison','status':state,'stage':stage,
               'at_ms':time.time_ns()//1000000,'registration_sha256':record['registration_sha256'],
               'promotable':False,**detail}
        status_path.write_text(canonical(value)+'\n')
        print(canonical(value),flush=True)
    try:
        status('RUNNING')
        plan=output/'compiler-plan.json';trainer=output/'training.py'
        freeze_plan(plan);compile_trainer(registration,plan,trainer)
        stage='waiting_for_fixed_end_and_complete_chain';status('RUNNING')
        wait_for_chain(chain,record,progress_path=output/'progress.log')
        stage='export';status('RUNNING')
        matrix=output/'matrix'
        audit=export_matrix(chain,registration,plan,matrix)
        stage='compare';status('RUNNING',opportunities=audit['opportunities'])
        report=compare(trainer,matrix/'matrix.csv',matrix/'manifest.json',output/'comparison')
        if report.get('status')!='DONE' or report.get('saved_inference_parity',{}).get('pass') is not True:
            raise ValueError('Original comparison did not pass saved inference parity')
        stage='complete';status('DONE',report=str(output/'comparison'/'report.json'))
        return report
    except Exception as error:
        status('BLOCKED',error_type=type(error).__name__,reason=str(error))
        raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registration',required=True,type=Path)
    parser.add_argument('--chain',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    try:run_registered(args.registration,args.chain,args.output)
    except Exception:return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
