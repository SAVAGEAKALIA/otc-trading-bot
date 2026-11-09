"""Read-only binary source probes and optional archived arithmetic audit."""
from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types

EDGE_PATH = 'trading_platform/research/validation/edge_audit.py'
EXPIRY_PATH = 'trading_platform/vendor/iqoptionapi/iqoptionapi/expiration.py'
ARCHIVE_TAG = 'otc-binary-final-2026-10-30'


def unit_return(outcome, payout, *, tie_refund=1., cost=0.):
    """Net return per stake; payout is net win profit, refund includes returned stake."""
    if not all(math.isfinite(v) for v in (payout,tie_refund,cost)):
        raise ValueError('Inputs must be finite')
    if payout <= 0 or not 0 <= tie_refund <= 1 or cost < 0:
        raise ValueError('Invalid payout, refund or cost')
    gross={'win':payout,'loss':-1.,'tie':tie_refund-1}
    if outcome not in gross:
        raise ValueError('Unresolved outcomes are not settled PnL')
    return gross[outcome]-cost


def expectancy(p_win,payout,*,p_tie=0.,tie_refund=1.,cost=0.):
    if not all(math.isfinite(v) for v in (p_win,p_tie)):
        raise ValueError('Probabilities must be finite')
    if p_win<0 or p_tie<0 or p_win+p_tie>1:
        raise ValueError('Invalid probabilities')
    return (p_win*unit_return('win',payout,cost=cost)
            +p_tie*unit_return('tie',payout,tie_refund=tie_refund,cost=cost)
            +(1-p_win-p_tie)*unit_return('loss',payout,cost=cost))


def iid_sample_size(payout,target_ev,alpha=.05,power=.8):
    """Educational normal approximation: one fixed IID Bernoulli hypothesis, no ties."""
    if payout<=0 or target_ev<=0 or not 0<alpha<.5 or not .5<power<1:
        raise ValueError('Invalid power inputs')
    p0,p1=1/(1+payout),(1+target_ev)/(1+payout)
    if not p0<p1<1:
        raise ValueError('Invalid alternative')
    z=statistics.NormalDist()
    numerator=z.inv_cdf(1-alpha)*math.sqrt(p0*(1-p0))+z.inv_cdf(power)*math.sqrt(p1*(1-p1))
    return {'payout':payout,'target_ev':target_ev,'p_null':p0,'p_alternative':p1,
            'alpha_one_sided':alpha,'power':power,
            'approximate_independent_trades':math.ceil((numerator/(p1-p0))**2)}


def read_source(repo,ref,path):
    commit=subprocess.check_output(['git','rev-parse',ref],cwd=repo,text=True).strip()
    source=subprocess.check_output(['git','show',f'{commit}:{path}'],cwd=repo,text=True)
    return source,{'commit':commit,'path':path,'sha256':hashlib.sha256(source.encode()).hexdigest()}


def extract(source,path,names,initial):
    """Extract actual definitions without importing trading runtime or its dependencies."""
    nodes=[]
    for n in ast.parse(source).body:
        if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names:
            nodes.append(n)
        elif isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets):
            nodes.append(n)
    found={n.name for n in nodes if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    if not names-{'Z_95'} <= found:
        raise ValueError('Source definition contract changed')
    name='_binary_research_probe'
    module=types.ModuleType(name);module.__dict__.update(initial)
    previous=sys.modules.get(name);sys.modules[name]=module
    try:
        exec(compile(ast.Module(body=nodes,type_ignores=[]),path,'exec'),module.__dict__)
    finally:
        if previous is None:
            del sys.modules[name]
        else:
            sys.modules[name]=previous
    return module.__dict__


def edge_function(repo):
    source,provenance=read_source(repo,'HEAD',EDGE_PATH)
    ns=extract(source,EDGE_PATH,{'Z_95','RuleResult','breakeven_win_rate','wilson_interval','_result','audit_trade_log'},
               {'math':math,'dataclass':dataclass,'Iterable':Iterable,'Mapping':Mapping})
    return ns['audit_trade_log'],provenance


def payout_probe(audit,win_payout=.55,loss_payout=.95):
    rows=[{'result':'win','payout_rate':win_payout}]*6000+[{'result':'loss','payout_rate':loss_payout}]*4000
    r=audit(rows,default_payout=.85)
    pnl=.6*unit_return('win',win_payout)+.4*unit_return('loss',loss_payout)
    return {'wins':6000,'losses':4000,'win_payout':win_payout,'loss_payout':loss_payout,
            'win_rate':r.win_rate,'wilson_lower':r.ci_low,'averaged_payout_breakeven':r.breakeven,
            'helper_clears':r.clears_breakeven,'actual_mean_unit_pnl':pnl,
            'false_positive':r.clears_breakeven and pnl<0}


def expiry_cases(repo,shifts=(0,2),seconds=(29,)):
    source,provenance=read_source(repo,ARCHIVE_TAG,EXPIRY_PATH)
    ns=extract(source,EXPIRY_PATH,{'date_to_timestamp','get_expiration_time'},
               {'datetime':dt.datetime,'timedelta':dt.timedelta})
    cases=[]
    for second in seconds:
        stamp=dt.datetime(2026,11,5,12,0,second,tzinfo=dt.timezone.utc).timestamp()
        for shift in shifts:
            ns['time']=types.SimpleNamespace(time=lambda s=shift:stamp+s,mktime=time.mktime)
            expiry,index=ns['get_expiration_time'](stamp,2)
            cases.append({'supplied_utc':dt.datetime.fromtimestamp(stamp,dt.timezone.utc).isoformat(),
                          'wall_clock_shift_s':shift,'holding_seconds':expiry-stamp,
                          'expiry_utc':dt.datetime.fromtimestamp(expiry,dt.timezone.utc).isoformat(),'index':index})
    return cases,provenance


def raw_archive_audit(root):
    if root is None:
        return {'status':'NOT_CHECKED','reason':'No --archive-root supplied'}
    names=['run1/results.json','run2/tournament_results.json','round3/crowd_results.json']
    missing=[name for name in names if not (root/name).is_file()]
    if missing:
        return {'status':'NOT_CHECKED','reason':'Missing raw reports','missing':missing}
    r1,r2,r3=[json.loads((root/name).read_text()) for name in names]
    hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}
    best=max(r1['results'],key=lambda r:r['holdout_roi'])
    p=best['holdout_wins']/best['holdout_trades']
    if not math.isclose(1.85*p-1,best['holdout_roi'],rel_tol=0,abs_tol=1e-12):
        raise AssertionError('Run1 fixed payout accounting mismatch')
    result={'status':'REPORTS_CHECKED','source_hashes':hashes,
            'report_entries':[len(r1['results']),len(r2['results']),len(r3['results'])],
            'best_run1':{'strategy':best['strategy'],'tf_sec':best['tf_sec'],'n':best['holdout_trades'],
                         'wins':best['holdout_wins'],'win_rate':p,'mean_unit_pnl_assumed85':1.85*p-1},
            'all_report_entries_rejected':not r1['any_edge'] and not r2['any_candidate']
                and all(not r['candidate'] for r in r3['results'].values())}
    try:
        import pandas as pd
    except ImportError:
        result['parquet']={'status':'NOT_CHECKED','reason':'pandas/parquet reader unavailable'}
        return result
    result['parquet']={'status':'CHECKED','rows':[],'missing':[]}
    for family in ('lightgbm','xgboost','logistic'):
        name=f'round3/trades_{family}.parquet'
        if not (root/name).is_file():
            result['parquet']['missing'].append(name);continue
        hashes[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
        try:
            frame=pd.read_parquet(root/name)
        except ImportError:
            result['parquet'].update(
                status='PARTLY_CHECKED' if result['parquet']['rows'] else 'NOT_CHECKED',
                reason='Parquet reader unavailable', failed_file=name)
            return result
        if not ((frame.pnl-frame.payout.where(frame.win,-1)).abs()<1e-12).all():
            raise AssertionError(f'{family}: per-row accounting mismatch')
        for split,mask in [('unseen',frame.week<=5),('seen',frame.week>=6)]:
            sample=frame.loc[mask];n=len(sample);wins=int(sample.win.sum());expected=r3['results'][family][split]
            if not (n==expected['trades'] and math.isclose(wins/n,expected['win_rate'],rel_tol=0,abs_tol=1e-12)
                    and math.isclose(float(sample.pnl.mean()),expected['roi'],rel_tol=0,abs_tol=1e-12)):
                raise AssertionError(f'{family}/{split}: report mismatch')
            result['parquet']['rows'].append({'family':family,'split':split,'n':n,'wins':wins,
                                             'win_rate':wins/n,'mean_unit_pnl':float(sample.pnl.mean()),
                                             'assets':int(sample.asset.nunique()),
                                             'distinct_target_times':int(sample.target_start_ms.nunique())})
    if result['parquet']['missing']:
        result['parquet']['status']='PARTLY_CHECKED' if result['parquet']['rows'] else 'NOT_CHECKED'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--archive-root',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    audit,edge_source=edge_function(args.repo);clock,expiry_source=expiry_cases(args.repo)
    probe=payout_probe(audit)
    if not probe['false_positive'] or not math.isclose(probe['actual_mean_unit_pnl'],-.07,rel_tol=0,abs_tol=1e-12):
        raise AssertionError('Current source counterexample no longer reproduced')
    if [c['holding_seconds'] for c in clock]!=[91.,151.]:
        raise AssertionError('Archived clock counterexample no longer reproduced')
    result={'kind':'research_probe_evidence_not_runtime_fix','sources':[edge_source,expiry_source],
            'payout_covariance_probe':probe,'expiry_clock_probe':clock,
            'payout_table':[{'payout':r,'breakeven_no_ties':1/(1+r),'ev_at_hypothetical_54_9pct_wins':expectancy(.549,r),'win_rate_for_3pct_ev_no_ties':1.03/(1+r)}
                            for r in (.70,.75,.80,.82,.85,.90,.95)],
            'iid_power_illustration':[iid_sample_size(.85,e) for e in (.01,.03,.05)],
            'raw_archive':raw_archive_audit(args.archive_root),
            'limitations':['Synthetic counterexamples do not measure dataset prevalence.',
                           'Saved candle PnL is not broker-accepted contract PnL.',
                           'IID power ignores dependence, selection, costs, ties and variable payouts.',
                           'No runtime fix or trading-edge claim is made.']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(args.output)


if __name__=='__main__':
    main()
