from copy import deepcopy
import json,random
from protocol import register,validate,digest
rng=random.Random(20261109);r=register(1794000000000);checks=0
for _ in range(10000):
 bad=deepcopy(r);stage=rng.randrange(5);field=rng.choice(['start_ms','end_ms','scheduled_opportunities']);bad['stages'][stage][field]+=rng.randrange(1,1000000)
 bad.pop('registration_sha256');bad['registration_sha256']=digest(bad)
 try:validate(bad)
 except ValueError:checks+=1
 else:raise AssertionError('retrospective chronology accepted')
print(json.dumps({'seed':20261109,'checks':checks,'pass':True,'network_calls':0}))
