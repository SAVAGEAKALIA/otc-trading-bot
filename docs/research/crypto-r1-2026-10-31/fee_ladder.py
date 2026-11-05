"""Apply ordinary published Bybit rates to the frozen descriptive funding screen."""
from decimal import Decimal
from itertools import product
import json
from pathlib import Path

from carry_cost_screen import clears

# bps per execution. Columns are spot taker, spot maker, perp taker, perp maker.
RATES = {
    'VIP 0': ('10', '10', '5.5', '2'),
    'VIP 1': ('8', '6.75', '4', '1.8'),
    'VIP 2': ('7.75', '6.5', '3.75', '1.6'),
    'VIP 3': ('7.5', '6.25', '3.5', '1.4'),
    'VIP 4': ('6', '5', '3.2', '1.2'),
    'VIP 5': ('5', '4', '3.2', '1'),
    'Supreme VIP': ('4.5', '3', '3', '0'),
}


def fee_cases(screen):
    values = {symbol: [Decimal(row['funding_bps']) for row in result['rows']]
              for symbol, result in screen['results'].items()}
    cases = []
    for tier, rates in RATES.items():
        spot_taker, spot_maker, perp_taker, perp_maker = map(Decimal, rates)
        spot = {'T': spot_taker, 'M': spot_maker}
        perp = {'T': perp_taker, 'M': perp_maker}
        for se, sx, pe, px in product('MT', repeat=4):
            fee = spot[se] + spot[sx] + perp[pe] + perp[px]
            cases.append({
                'tier': tier, 'policy': se + sx + pe + px, 'roundtrip_fee_bps': str(fee),
                'strict_threshold_bps': str(2 * fee),
                'qualifying_proxy_windows': {symbol: sum(clears(x, fee) for x in rows)
                                             for symbol, rows in values.items()},
                'peak_remaining_roundtrip_bps_exclusive': {
                    symbol: str(max(rows) / 2 - fee) for symbol, rows in values.items()
                },
            })
    return cases


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    source = json.loads((root / 'carry_cost_screen.json').read_text())
    print(json.dumps({'as_of': '2026-11-05', 'scope': 'published base fees only',
                      'policy_order': ['spot_entry', 'spot_exit', 'perp_entry', 'perp_exit'],
                      'cases': fee_cases(source), 'r2_freeze_ready': False}, indent=2))
