# Crypto evidence, 2026-10-30

These scripts and outputs are the evidence behind
`docs/plans/2026-10-30-crypto-plan.md`. They are deterministic, they use only
public data, and they need no API keys.

| File | What |
|---|---|
| `pull_funding_history.py` | Full funding history: Bybit linear perps (BTC, ETH, SOL, XRP, DOGE) and Hyperliquid (BTC, ETH, SOL) |
| `realized_carry.py` | Realized delta-neutral carry per year, always-on vs regime-gated (enter when trailing 7d > 8% annualized, exit when trailing 3d < 0), net of taker round-trip fees |
| `realized_carry_report.txt` | Output from the 2026-10-30 run |
| `binance_funding_stats.py`, `binance_btc_funding_stats.txt` | Binance BTCUSDT funding from data.binance.vision, 2020-2026 |

Reproduce:

```bash
python3 pull_funding_history.py funding.json   # from a host that can reach the APIs; the VPS works
python3 realized_carry.py funding.json 0.08
```

Returns are per unit of hedged notional (spot long plus 1x perp short).
For fully paid spot plus a separately stablecoin-margined 1x short, required
capital is approximately 2x notional before reserves. Cross-margin offsets
require a separate verified collateral model; do not assume 1.0-1.5x.
These scripts measure a funding-minus-simplified-fees proxy, not full portfolio
returns, drawdown or investability. See the
[2026-10-30 audit](../crypto-review-2026-10-30/README.md) for limitations and
reproducible denominator sensitivities.
