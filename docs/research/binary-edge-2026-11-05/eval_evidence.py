"""Deterministic neighboring-case eval; no LLM calls, training or trading-edge claim."""
import argparse
import json
from pathlib import Path
from evidence import edge_function,expiry_cases,payout_probe


def evaluate(repo):
    audit,edge_source=edge_function(repo)
    payouts=[payout_probe(audit,*pair) for pair in ((.55,.95),(.50,.99),(.65,.65),(.75,.55),(.95,.55))]
    clocks,expiry_source=expiry_cases(repo,shifts=(-2,0,2),seconds=(29,30,31))
    checks={
        'negative_correlated_payouts_reproduce_false_positive':all(r['false_positive'] for r in payouts[:2]),
        'negative_fixed_payout_control_rejected':payouts[2]['actual_mean_unit_pnl']<0 and not payouts[2]['helper_clears'],
        'strong_positive_control_positive':payouts[-1]['actual_mean_unit_pnl']>0 and payouts[-1]['helper_clears'],
        'nearby_clock_cases_minute_aligned_future_expiry':all(0<c['holding_seconds']<=180 and c['expiry_utc'].endswith(':00+00:00') for c in clocks),
        'clock_dependency_on_three_adjacent_seconds':all(len({c['holding_seconds'] for c in clocks if c['supplied_utc']==s})>1 for s in {c['supplied_utc'] for c in clocks}),
    }
    return {'kind':'source_probe_eval_not_edge_eval','sources':[edge_source,expiry_source],
            'pass_threshold':'all checks true','pass':all(checks.values()),'checks':checks,
            'payout_cases':payouts,'clock_cases':clocks,
            'limitations':'Passing preserves the investigation, not a runtime fix or positive trading edge.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=evaluate(args.repo)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(args.output)
    if not result['pass']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
