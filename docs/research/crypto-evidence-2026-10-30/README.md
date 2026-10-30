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
Required capital is higher, about 1.0-1.5x notional depending on the margin
mode, so divide the returns by that multiplier.
