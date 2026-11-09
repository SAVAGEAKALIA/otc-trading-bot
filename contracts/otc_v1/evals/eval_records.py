"""Neighboring cash/clock cases and an old ambient-rounding mutant."""
import argparse
from dataclasses import replace
from decimal import Decimal, ROUND_DOWN, ROUND_UP, localcontext
import json
from pathlib import Path
from contracts.otc_v1 import Observation, Settlement


def evaluate():
    checks={}
    row=Settlement('b','practice','broker_api','tie','3','1','0','USD',100,'e')
    values=[];mutant=[]
    for rounding in (ROUND_DOWN,ROUND_UP):
        with localcontext() as ctx:
            ctx.prec=2;ctx.rounding=rounding
            values.append(str(row.unit_return))
            mutant.append(str((Decimal(row.gross_return)-Decimal(row.stake))/Decimal(row.stake)))
    checks['caller_context_cannot_change_cash_return']=len(set(values))==1
    checks['old_ambient_rounding_mutant_caught']=len(set(mutant))>1
    for outcome,gross,fee,expected in [('win','1.8','0','0.8'),('loss','0','0','-1'),
                                      ('tie','1','0','0'),('tie','0.5','0.1','-0.6'),
                                      ('void','1','0.01','-0.01')]:
        actual=replace(row,outcome=outcome,stake='1',gross_return=gross,separately_charged_fee=fee).unit_return
        checks[f'{outcome}_{gross}_{fee}_cash_preserved']=actual==Decimal(expected)
    observation=Observation('q','iqoption','X','turbo-option','quotes','quote',250,200,'1','receiver_utc')
    for received,valid in [(199,False),(200,True),(201,True),(None,True)]:
        try: replace(observation,available_ms=received);accepted=True
        except ValueError: accepted=False
        checks[f'receipt_{received}_boundary']=accepted==valid
    checks['unknown_availability_not_reconstructed']=replace(observation,available_ms=None).available_ms is None
    return {'schema':'otc_contract_eval_v1','pass':all(checks.values()),'threshold':'all checks pass','checks':checks,
            'cash_precision':34,'reference':'immutable received/source and reported cash boundary'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=evaluate();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps(report))
    if not report['pass']: raise SystemExit(1)


if __name__=='__main__': main()
