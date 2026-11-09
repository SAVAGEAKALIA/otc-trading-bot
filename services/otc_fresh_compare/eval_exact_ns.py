"""Held-out exact receipt ordering, cutoff and outcome ambiguity eval."""
from pathlib import Path
import argparse
from contracts.otc_fresh_v1 import ASSETS,CONFIG,GRID_MS,canonical
from services.otc_fresh_compare.export import NS_PER_MS,replay_decision
from services.otc_fresh_compare.tests.test_exact_ns import receipt_database,decision_events


def evaluate(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);checks={};cases={}
    decision=1794046080000;ns=decision*NS_PER_MS;expiry=(decision+GRID_MS)*NS_PER_MS
    def replay(label,events):
        connection=receipt_database(output/(label+'.sqlite'),events)
        try:rows,details,stats=replay_decision(connection,decision)
        finally:connection.close()
        cases[label]={'rows':rows,'details':details,'stats':stats}
        return rows,details,stats
    original=decision_events(decision);baseline,base_details,stats=replay('distinct-ns',original)
    checks['distinct_ns_same_ms_are_ordered_not_conflicting']=stats['conflicts']==[]
    checks['true_earliest_entry_for_both_assets']=all(row['lineage']['modeled_strike']==f'a-earliest-{index}' for index,row in enumerate(base_details))
    checks['latest_pre_expiry_quote_and_up_labels']=all(row['label']=='up' and row['terminal_quote']=='102' for row in base_details)
    checks['fractional_receipt_age_is_conservative_ms']=all(row['f_quote_age_ms']==1 for row in baseline)
    for asset_index,asset in enumerate(ASSETS):
        for label,moment in [('entry-conflict',ns+150),('terminal-conflict',expiry-1)]:
            extras=[(asset,'quote',moment,value,f'{label}-{asset_index}-{index}') for index,value in enumerate(('103','104'))]
            rows,details,stats=replay(label+str(asset_index),original+extras)
            prefix=label+'_'+asset
            checks[prefix+'_outcome_unknown']=rows[asset_index]['status']=='unresolved' and details[asset_index]['label'] is None
            checks[prefix+'_decision_features_unchanged']=details[asset_index]['features']==base_details[asset_index]['features']
            checks[prefix+'_other_asset_unchanged']=rows[1-asset_index]==baseline[1-asset_index]
            checks[prefix+'_complete_exact_ns_batch']=len(stats['conflicts'])==1 and stats['conflicts'][0]['received_at_ns']==moment and len(stats['conflicts'][0]['event_ids'])>=2
        no_entries=[event for event in original if not (event[0]==asset and event[1]=='quote' and ns<=event[2]<expiry)]
        for delta in (0,1):
            moment=ns+CONFIG['max_entry_wait_ms']*NS_PER_MS+delta
            rows,details,stats=replay(f'entry-limit-{asset_index}-{delta}',no_entries+[(asset,'quote',moment,'100','entry-limit')])
            checks[f'{asset}_entry_2s_plus_{delta}ns_boundary']=(details[asset_index]['lineage']['modeled_strike']=='entry-limit') if delta==0 else (rows[asset_index]['status']=='unresolved' and details[asset_index]['lineage']['modeled_strike'] is None)
        no_terminal=[event for event in original if not (event[0]==asset and event[1]=='quote' and event[2]>=expiry-1)]
        for delta in (0,1):
            rows,details,stats=replay(f'expiry-limit-{asset_index}-{delta}',no_terminal+[(asset,'quote',expiry+delta,'102','expiry-limit')])
            checks[f'{asset}_expiry_plus_{delta}ns_boundary']=(details[asset_index]['lineage']['terminal_quote']=='expiry-limit') if delta==0 else (rows[asset_index]['status']=='unresolved' and details[asset_index]['lineage']['terminal_quote'] is None)
        for delta in (0,1):
            events=[event for event in original if event[4]!=f'decision-{asset_index}']
            moment=ns-CONFIG['max_age_ms']['quote']*NS_PER_MS-delta
            rows,details,stats=replay(f'age-limit-{asset_index}-{delta}',events+[(asset,'quote',moment,'99','age-limit')])
            checks[f'{asset}_quote_age_plus_{delta}ns_boundary']=(rows[asset_index]['status']=='resolved' and rows[asset_index]['f_quote_age_ms']==CONFIG['max_age_ms']['quote']) if delta==0 else rows[asset_index]['status']=='ineligible'
        future=original+[(asset,'quote',ns+1,'105',f'future-decision-{asset_index}')]
        rows,details,stats=replay('future-decision-'+str(asset_index),future)
        checks[asset+'_future_decision_quote_never_a_feature']=details[asset_index]['lineage']['decision_quote']==f'decision-{asset_index}'
        lookback=ns-CONFIG['lookback_ms']*NS_PER_MS
        rows,details,stats=replay('future-lookback-'+str(asset_index),original+[(asset,'quote',lookback+1,'98','future-lookback')])
        checks[asset+'_future_lookback_quote_never_a_feature']=details[asset_index]['lineage']['lookback_quote'] is None
    result={'schema':'otc_exact_receipt_order_eval_v1','pass':all(checks.values()),'checks':checks,
        'threshold':'all exact cutoff, ordering, age and non-retroactive ambiguity checks pass',
        'fixtures':'synthetic nanosecond receipts; no fits or external calls'}
    (output/'cases.json').write_text(canonical(cases)+'\n');(output/'eval.json').write_text(canonical(result)+'\n')
    print(canonical(result));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    raise SystemExit(0 if evaluate(args.output)['pass'] else 1)
