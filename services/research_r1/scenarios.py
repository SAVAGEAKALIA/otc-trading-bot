"""R1 hypothetical total-capital economics. No exchange or execution imports."""
import argparse
import csv
from decimal import Decimal, InvalidOperation, localcontext
import itertools
import json
from pathlib import Path


def D(value):
    if isinstance(value, bool):
        raise ValueError('boolean is not a numeric assumption')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('invalid numeric assumption') from exc
    if not result.is_finite():
        raise ValueError('nonfinite numeric assumption')
    return result


def text(value):
    return format(value.normalize(), 'f')


def economics(capital, net_notional_apr, *, annual_fixed_cost='0', benchmark_apr='0',
              short_leverage='1', reserve_per_notional='.5'):
    """Rates are hypothetical after variable trading costs, not estimated returns.

    Fully paid spot + separate stablecoin short collateral. Reserve receives
    zero interest; no borrowing or collateral offset. Profit excludes FX/depeg
    and taxes, so this is a screen only, never portfolio P&L or a loss bound.
    """
    capital, rate, fixed, benchmark, leverage, reserve = map(D, (
        capital, net_notional_apr, annual_fixed_cost, benchmark_apr,
        short_leverage, reserve_per_notional))
    if capital <= 0 or fixed < 0 or not 0 < leverage <= 1 or reserve < 0:
        raise ValueError('capital > 0, fixed/reserve >= 0, and 0 < leverage <= 1 required')
    with localcontext() as context:
        context.prec = 28
        multiplier = 1 + 1 / leverage + reserve
        notional = capital / multiplier
        income = notional * rate
        net = income - fixed
        excess = net - capital * benchmark
        marginal_excess = rate / multiplier - benchmark
        breakeven = fixed / marginal_excess if marginal_excess > 0 else None
        return {'capital_usdt': text(capital), 'net_notional_apr_after_variable_costs': text(rate),
                'annual_fixed_cost_usdt': text(fixed), 'benchmark_apr': text(benchmark),
                'capital_multiplier': text(multiplier), 'hedged_notional': text(notional),
                'reserve_usdt': text(notional * reserve), 'annual_net_profit': text(net),
                'net_capital_apr': text(net / capital), 'annual_excess_profit': text(excess),
                'break_even_capital': text(breakeven) if breakeven is not None else None,
                'interpretation': 'hypothetical USDT-unit screen; no price/basis/depeg/tax loss model'}


def example_config():
    return {'schema_version': 1, 'mode': 'research', 'live_enabled': False,
            'residence': 'Nigeria', 'reference_currency': 'USDT',
            'user_reported_accounts': ['Bybit', 'WEEX', 'Binance'],
            'benchmark': 'non-interest-bearing USDT holding, not USD risk-free',
            'benchmark_apr': '0', 'capital_budget_usdt': None, 'max_loss_usdt': None,
            'max_drawdown_pct': None, 'venue_loss_budget_usdt': None, 'stablecoin_loss_budget_usdt': None,
            'risk_premium_bps': None, 'minimum_profit_usdt_year': None,
            'research_external_spend_usd': '0', 'eligibility_verified': False,
            'fees_verified': False, 'data_quality_passed': False,
            'trial_spec_signed': False,
            'scenario_capital_usdt': ['1000', '5000', '10000'],
            'scenario_net_notional_apr': ['-.05', '0', '.02', '.05', '.10', '.20'],
            'scenario_annual_fixed_cost_usdt': ['0', '120', '360'],
            'scenario_reserve_per_notional': '.5',
            'scenario_short_leverage': '1'}


def configuration_status(config):
    required = set(example_config())
    if required - set(config):
        raise ValueError('missing configuration fields: ' + ', '.join(sorted(required - set(config))))
    if config['schema_version'] != 1 or isinstance(config['schema_version'], bool):
        raise ValueError('unsupported schema')
    if config['mode'] != 'research' or config['live_enabled'] is not False:
        raise ValueError('R1 supports research only and never enables trading')
    if config['reference_currency'] != 'USDT' or config['residence'] != 'Nigeria':
        raise ValueError('this contract is scoped to confirmed Nigeria/USDT context')
    if D(config['research_external_spend_usd']) != 0:
        raise ValueError('no external paid service authorized by this R1 configuration')
    unresolved = []
    for key in ('capital_budget_usdt', 'max_loss_usdt', 'max_drawdown_pct',
                'venue_loss_budget_usdt', 'stablecoin_loss_budget_usdt', 'risk_premium_bps', 'minimum_profit_usdt_year'):
        value = config[key]
        if value is None:
            unresolved.append(key)
        elif D(value) <= 0:
            raise ValueError(key + ' must be positive or explicitly unset')
    if config['max_drawdown_pct'] is not None and D(config['max_drawdown_pct']) > 100:
        raise ValueError('drawdown percent must not exceed 100')
    capital = config['capital_budget_usdt']
    if capital is not None:
        for key in ('max_loss_usdt', 'venue_loss_budget_usdt', 'stablecoin_loss_budget_usdt'):
            if config[key] is not None and D(config[key]) > D(capital):
                raise ValueError(key + ' exceeds total programme capital')
    for key in ('eligibility_verified', 'fees_verified', 'data_quality_passed', 'trial_spec_signed'):
        if type(config[key]) is not bool:
            raise ValueError(key + ' must be boolean')
        if not config[key]: unresolved.append(key)
    D(config['benchmark_apr'])
    for key in ('scenario_capital_usdt', 'scenario_net_notional_apr', 'scenario_annual_fixed_cost_usdt'):
        if not isinstance(config[key], list) or not config[key]:
            raise ValueError('nonempty scenario list required: ' + key)
    for value in config['scenario_capital_usdt']:
        if D(value) <= 0: raise ValueError('scenario capital must be positive')
    for value in config['scenario_net_notional_apr']: D(value)
    for value in config['scenario_annual_fixed_cost_usdt']:
        if D(value) < 0: raise ValueError('scenario cost cannot be negative')
    if not 0 < D(config['scenario_short_leverage']) <= 1 or D(config['scenario_reserve_per_notional']) < 0:
        raise ValueError('invalid scenario collateral assumptions')
    return {'schema_version': 1, 'research_scenarios_ready': True,
            'configuration_complete': not unresolved, 'r2_freeze_ready': False, 'unresolved': unresolved, 'live_enabled': False,
            'warning': 'scenario values are not approved allocations; final R2 lock requires independent evidence/signature outside this diagnostic'}


def scenario_rows(config):
    configuration_status(config)
    return [economics(capital, rate, annual_fixed_cost=cost,
                      benchmark_apr=config['benchmark_apr'],
                      short_leverage=config['scenario_short_leverage'],
                      reserve_per_notional=config['scenario_reserve_per_notional'])
            for capital, rate, cost in itertools.product(config['scenario_capital_usdt'],
                    config['scenario_net_notional_apr'], config['scenario_annual_fixed_cost_usdt'])]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    rows = scenario_rows(config)
    with Path(args.output).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    print(json.dumps({'rows': len(rows), 'configuration': configuration_status(config)}, indent=2))
