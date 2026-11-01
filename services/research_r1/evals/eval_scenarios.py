"""Offline adverse-case evaluation. Exact Decimal invariants, no paid LLM."""
import importlib.util
from pathlib import Path
import itertools
import json

spec = importlib.util.spec_from_file_location('scenarios', Path(__file__).resolve().parents[1] / 'scenarios.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
checks = 0
for capital, rate, fixed, reserve in itertools.product(['100','1000','10000'], ['-.1','0','.1'], ['0','120'], ['0','.2','1']):
    row = m.economics(capital, rate, annual_fixed_cost=fixed, reserve_per_notional=reserve)
    assert m.D(row['hedged_notional']) <= m.D(capital) / 2
    if m.D(rate) <= 0: assert m.D(row['annual_net_profit']) <= 0
    higher_cost = m.economics(capital, rate, annual_fixed_cost=str(m.D(fixed)+1), reserve_per_notional=reserve)
    assert m.D(higher_cost['annual_net_profit']) < m.D(row['annual_net_profit'])
    checks += 1
print(json.dumps({'status':'PASS', 'economic_scenarios':checks,
                  'scope':'hypothetical accounting invariants only; no strategy profitability evaluation'}))
