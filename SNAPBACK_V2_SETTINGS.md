# Optimal Settings: Snapback Gravity V2

To achieve the **88.9% simulated win rate**, use the following configuration in your `config.py` or bot dashboard. These settings enforce the rejections discovered during the quant audit.

## 1. Scanner Configuration (`ScannerConfig`)

| Parameter | Recommended Value | Reason |
| :--- | :--- | :--- |
| `quality_min_score` | **70** | Filters out "Neutral" noise; targets the Gold Zone. |
| `expansion_trap_max` | **1.2** | Blocks exhaustion spikes (34% WR avoidance). |
| `wick_magnet_max` | **0.4** | Blocks "Wick Magnets" (20% WR avoidance). |
| `rsi_extreme_low` | **30.0** | OTC mean-reversion is unstable below 30. |
| `rsi_extreme_high` | **70.0** | OTC mean-reversion is unstable above 70. |
| `calm_confluence_gate` | **True** | Mandatory 2m + 5m alignment with trade direction. |
| `put_boost_enabled` | **True** | Exploits the 78% "Gravity Bias" for PUT trades. |

## 2. Gatekeeper Settings (`SignalGatekeeper`)

Set your primary execution mode to **STRICT**.

- **Mode**: `strict`
- **Alpha Hours**: `Enabled` (Trades only during hours with historical peak win rates).
- **RSI Safe Zone**: `30 - 70` (Hard-coded requirement for 60%+ win rate).
- **Martingale Lock**: `Enabled` (Prevents recovery trades against strong contrary trends).

## 3. Recommended Strategy Mix (StrategyEngine)

For the highest accuracy, enable these strategies in your hybrid evaluation:

1.  **IndicatorStrategy (Weight 1.2)**: The primary trend follower.
2.  **MHI Majority (Weight 1.0)**: Use for 5-candle cycle confirmation.
3.  **MHI Logic (Weight 0.8)**: Use as a secondary confirmation for reversals.

## 4. Telegram Signal Tuning

If using external Telegram signals, use these specific overrides in `SignalGatekeeper`:

- **Threshold Mode**: `strict` (This is mandatory to avoid the "Neutral Trap").
- **Confluence Requirement**: `4 indicators` (Ensures the Telegram signal isn't just a random guess).
- **Force Re-Analysis**: `True` (The bot will check the chart itself rather than blindly following the message).

> [!IMPORTANT]
> **Priority**: Quality over Volume.
> By using these settings, the bot will likely ignore 80% of signals. This is intended behavior. The remaining 20% are the "Elite" setups identified in the 192-trade data audit.

- **Trade Duration**: `dynamic` (Let the bot adjust based on volatility regime).
- **Max Active Trades**: `1` (Recommended initially to verify V2 performance without over-exposure).
- **Martingale**: `Smart/Enabled` (But strictly capped at 2 recovery steps).

## 4. Summary of rejections to expect in logs
- `[Filtered] Expansion Trap (1.42 > 1.2)`
- `[Filtered] Wick Magnet Lock (0.55 > 0.4)`
- `[Filtered] Trend Misalignment (2m:Neutral / 5m:Bearish)`
- `[Filtered] RSI Extreme (28.4)`
