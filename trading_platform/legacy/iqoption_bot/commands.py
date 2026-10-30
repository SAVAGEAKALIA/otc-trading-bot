"""
Command handler module — extracted from bot.py.

All Telegram command handlers live here.  The CommandHandler holds a
back-reference to the bot so it can read/write state (worker, sizer, etc.).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Any, Optional
from .scanner import ScannerProfile, ScannerTradeMode

if TYPE_CHECKING:
    from .bot import OTCTradingBot


class CommandHandler:
    """Dispatches and executes all /commands from Telegram."""

    def __init__(self, bot: "OTCTradingBot"):
        self.bot = bot

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------
    async def handle(self, event, command: str, args: str) -> str:
        user_id = event.sender_id
        bot = self.bot

        admin_commands = [
            'pause', 'resume', 'start', 'stop', 'reset', 'dryrun',
            'martingale', 'sizing', 'scanner', 'weights',
            'telegram', 'martingale_mode', 'cache',
            'gatekeeper', 'threshold', 'alphahours',
        ]
        if command in admin_commands and not bot.is_admin(user_id):
            return "⛔ You don't have permission to use this command."

        dispatch = {
            'help': lambda: self._cmd_help(),
            'myid': lambda: self._cmd_myid(event),
            'status': lambda: self._cmd_status(),
            'stats': lambda: self._cmd_stats(),
            'breakdown': lambda: self._cmd_breakdown(),
            'session': lambda: self._cmd_session(args),
            'trades': lambda: self._cmd_open_trades(),
            'pause': lambda: self._cmd_pause(args),
            'resume': lambda: self._cmd_resume(),
            'start': lambda: self._cmd_resume(),
            'dryrun': lambda: self._cmd_dryrun(args),
            'martingale': lambda: self._cmd_martingale(args),
            'sizing': lambda: self._cmd_sizing(args),
            'scanner': lambda: self._cmd_scanner(args),
            'gatekeeper': lambda: self._cmd_gatekeeper(args),
            'threshold': lambda: self._cmd_threshold(args),
            'martingale_mode': lambda: self._cmd_martingale_mode(args),
            'cache': lambda: self._cmd_cache(),
            'weights': lambda: self._cmd_weights(args),
            'telegram': lambda: self._cmd_telegram(args),
            'reset': lambda: self._cmd_reset_session(args),
            'alphahours': lambda: self._cmd_alphahours(args),
            'fpstats': lambda: self._cmd_fpstats(args),
        }

        # Async commands need await
        async_commands = {
            'stop': lambda: self._cmd_stop(),
            'balance': lambda: self._cmd_account(),
            'account': lambda: self._cmd_account(args),
            'patterns': lambda: self._cmd_patterns(args),
        }

        if command in dispatch:
            return dispatch[command]()
        if command in async_commands:
            return await async_commands[command]()

        return f"❓ Unknown command: /{command}\nType /help for available commands."

    # ------------------------------------------------------------------
    # Simple / status commands
    # ------------------------------------------------------------------
    def _cmd_help(self) -> str:
        return """🤖 *OTC Trading Bot v3.0*

📊 *Status Commands:*
/status - Bot state & connection
/stats - Win/loss & profit
/breakdown - Win rate by source/asset/duration
/session - PnL, streak, limits
/trades - Active positions
/balance - Account balance
/patterns EURUSD - Technical analysis

🎮 *Control:*
/telegram on|off - Signal listener
/pause [reason] - Stop trading
/resume - Continue trading  
/reset [mode] - Clear stats/state
_Modes: session, scanner, all_
/dryrun on|off - Test mode

🔁 *Martingale:*
/martingale on|off - Toggle
/martingale steps 4 - Max steps (1-10)
/martingale multiplier 2.5 - Multiplier
/martingale duration 2 - Fixed duration
/martingale_mode classic|pullback - Recovery strategy

💰 *Position Sizing:*
/sizing - Show current
/sizing fixed 5 - $5 per trade
/sizing percent 2 - 2% of balance
/sizing kelly 0.25 - Quarter Kelly

📊 *Session Limits:*
/session maxloss 50 - Max daily loss
/session maxstreak 3 - Max consecutive losses
/session target 100 - Daily profit target

🔍 *Gatekeeper (Risk Control):*
/gatekeeper on|off
/gatekeeper mode strict|normal|relaxed|very_relaxed
/threshold <scanner|telegram> <value>
/alphahours on|off - Time-of-day filter

🔍 *Scanner (Auto-Discovery):*
/scanner on|off - Toggle
/scanner status - Show settings
/scanner strategy indicators|mhi|hybrid|r7|majority|ccv2|adaptive|squeeze|rubber|apex|exhaustion|ml_lstm|ml_catboost
/scanner strategy cascade+sniper+compression+exhaustion - Custom combo
/scanner scan_mode voting|tournament
/scanner agreement 1-6 - Required agreeing strategies
/scanner families 1-6 - Required independent evidence families
/scanner profile trend|reversal|mixed
/scanner mode single|multi
/scanner timeframe fixed|2 - Fixed, whitelisted expiry
/scanner maxduration 1-5
/scanner interval 15-600
/scanner top 15 - Top N pairs
/scanner expiryconfluence 2-6 - Fast-expiry confidence threshold
/scanner confidence 50-100
/scanner precision on|off - Second 58 Rule
/scanner autostop on|off
/scanner mlbypass on|off - ML-only scanner hard-gate override
/scanner mlthreshold 70 - Temporary LSTM action threshold (practice)
/scanner mlsignal lstm|catboost|both|off - Directional ML source
/scanner mlgate off|shadow|enforce - Conditional CatBoost gate
/scanner mlpayout 75 - Minimum current payout
/scanner mledge 2 - Minimum model EV percentage
/scanner regime on|off - ATR Regime Routing
/scanner rsiextreme on|off - Block RSI extremes
/scanner expansion on|off - Block trap candles
/scanner wick on|off - Block directional rejection wicks
/scanner calmconfluence on|off - Block TF misalignment
/scanner quality on|off - Quality Score Overlay
/scanner qualitymin 50 - Min quality score
/scanner putboost on|off - PUT alignment bonus
/scanner stoch on|off - Stochastic tiebreaker
/scanner runcap 4 - Run-length cap
/scanner blacklist - Per-asset stats
/scanner research - Paper outcomes by strategy

⚡ *System:*
/cache - Cache statistics
/account - Account info & mode switch
/account switch - Toggle Practice/Real
/fpstats - Fingerprint DB analytics
/myid - Show your Telegram ID & admin status

⚖️ *Signal Weights:*
/weights - Show current weights
/weights adx 0 - Set ADX weight to 0
/weights reset - Reset to defaults

💡 Type any command alone for help."""

    def _cmd_myid(self, event) -> str:
        bot = self.bot
        user_id = bot.my_telegram_id or event.sender_id
        is_admin = bot.is_admin(user_id)
        admin_status = "✅ You ARE an admin" if is_admin else "❌ You are NOT an admin"
        return f"""🆔 *Your Telegram Info*

User ID: `{user_id}`
{admin_status}

Since this is a self-bot, you are automatically an admin!
Control the bot by typing commands here in Saved Messages."""

    def _cmd_status(self) -> str:
        bot = self.bot
        uptime = datetime.now() - bot.started_at
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        if bot.paused:
            status = f"⏸️ PAUSED"
            if bot.pause_reason:
                status += f" ({bot.pause_reason})"
        else:
            status = "🟢 RUNNING"

        dry_run_status = "🧪 ON" if bot.dry_run else "OFF"
        session_active = "🟢 Active" if bot.session_manager and bot.session_manager.is_active else "🔴 Stopped"

        connection_status = "🟢 Connected"
        pending_signals = 0
        if bot.api_worker:
            if not bot.api_worker.is_connected:
                connection_status = "🔴 Disconnected"
            pending_signals = bot.api_worker.trade_queue.qsize()

        return f"""📊 *Bot Status*

State: {status}
Uptime: {hours}h {minutes}m
Mode: {dry_run_status}
Session: {session_active}
Connection: {connection_status}
Queue: {pending_signals} signals pending"""

    def _cmd_stats(self) -> str:
        bot = self.bot
        if not bot.trade_logger:
            return "❌ Trade logger not initialized"

        stats = bot.trade_logger.get_statistics()
        win_rate = stats.get('win_rate', 0)
        profit = stats.get('total_profit', 0)
        profit_emoji = "📈" if profit >= 0 else "📉"

        cal_summary = ""
        if bot.api_worker and hasattr(bot.api_worker, 'confidence_tracker'):
            cal_summary = "\n\n" + bot.api_worker.confidence_tracker.get_summary()

        return f"""📊 *Trading Statistics*

Verified Trades: {stats.get('total', 0)}
✅ Wins: {stats.get('wins', 0)}
❌ Losses: {stats.get('losses', 0)}
↔️ Ties: {stats.get('ties', 0)}
📊 Win Rate: {win_rate}%

{profit_emoji} Verified Profit: ${profit:.2f}
⚠️ Excluded from Win Rate: {stats.get('excluded_settlements', 0)}
⏳ Pending: {stats.get('pending', 0)}{cal_summary}"""

    def _cmd_breakdown(self) -> str:
        bot = self.bot
        if not bot.trade_logger:
            return "❌ Trade logger not initialized"
        return bot.trade_logger.format_breakdown()

    def _cmd_session(self, args: str = "") -> str:
        bot = self.bot
        if not bot.session_manager:
            return "❌ Session manager not initialized"

        args = args.strip().lower()
        parts = args.split()

        if len(parts) >= 2:
            cmd = parts[0]
            try:
                val = float(parts[1])
                if cmd == 'maxloss':
                    bot.api_worker.set_session_limits('max_loss', val)
                    return f"✅ Session max daily loss set to ${val:.2f}"
                elif cmd == 'maxstreak':
                    bot.api_worker.set_session_limits('max_streak', int(val))
                    return f"✅ Session max consecutive losses set to {int(val)}"
                elif cmd == 'target':
                    bot.api_worker.set_session_limits('profit_target', val)
                    return f"✅ Session profit target set to ${val:.2f}"
            except ValueError:
                return "❌ Invalid value provided."

        stats = bot.session_manager.get_session_stats()
        status = "🟢 Active" if stats['is_active'] else f"🔴 Stopped: {stats['stop_reason']}"
        pnl = stats['pnl']
        pnl_emoji = "📈" if pnl >= 0 else "📉"

        return f"""📊 *Session Info*

Status: {status}
{pnl_emoji} Session PnL: ${pnl:.2f}
📋 Trades Taken: {stats['trades']}
🔥 Loss Streak: {stats['consecutive_losses']}
⏱️ Duration: {stats['duration_minutes']:.1f} min

⚙️ *Limits:*
Max Daily Loss: ${bot.session_manager.max_daily_loss:.2f} (/session maxloss)
Max Consecutive Losses: {bot.session_manager.max_consecutive_losses} (/session maxstreak)
Profit Target: ${bot.session_manager.profit_target:.2f} (/session target)"""

    def _cmd_open_trades(self) -> str:
        bot = self.bot
        if not bot.api_worker:
            return "❌ API worker not initialized"

        import time
        active = bot.api_worker.active_trades
        if not active:
            return "📋 No trades currently being monitored."

        lines = ["📋 *Active Trades:*\n"]
        for order_id, info in active.items():
            time_left = info['expiry_time'] - time.time()
            if time_left > 0:
                status = f"⏳ {time_left:.0f}s left"
            else:
                status = f"🔍 Checking result..."
            lines.append(f"• {info['asset']} {info['direction'].upper()}")
            lines.append(f"  ${info['amount']:.2f} | {status}")
        return "\n".join(lines)

    def _cmd_pause(self, reason: str = "") -> str:
        bot = self.bot
        if bot.paused:
            return f"⏸️ Bot is already paused. Reason: {bot.pause_reason or 'No reason given'}"
        bot.paused = True
        bot.pause_reason = reason.strip() if reason else "Manual pause"
        return f"""⏸️ *Trading Paused*

Reason: {bot.pause_reason}

The bot will continue monitoring but won't execute new trades.
Use /resume to continue trading."""

    def _cmd_resume(self) -> str:
        bot = self.bot
        if not bot.paused:
            return "🟢 Bot is already running!"
        bot.paused = False
        old_reason = bot.pause_reason
        bot.pause_reason = ""
        return f"""▶️ *Trading Resumed*

Previous pause reason: {old_reason or 'None'}

Bot is now actively trading signals."""

    async def _cmd_stop(self) -> str:
        await self.bot.stop()
        return """🛑 *Bot Stopping*

Cancelling scheduled trades...
Saving statistics...
Disconnecting...

Goodbye! 👋"""

    def _cmd_dryrun(self, args: str) -> str:
        bot = self.bot
        args = args.strip().lower()
        if args == 'on':
            bot.dry_run = True
            return "🧪 *Dry Run Mode: ON*\n\nBot will analyze signals but NOT place real trades."
        elif args == 'off':
            bot.dry_run = False
            return "🧪 *Dry Run Mode: OFF*\n\nBot will now place real trades."
        else:
            status = "ON" if bot.dry_run else "OFF"
            return f"""🧪 *Dry Run Mode: {status}*

Usage: /dryrun on or /dryrun off"""

    def _cmd_telegram(self, args: str) -> str:
        bot = self.bot
        args = args.lower().strip()
        if args == 'on':
            bot.telegram_signals_enabled = True
            return "✅ *Telegram Signals:* `ON`"
        elif args == 'off':
            bot.telegram_signals_enabled = False
            return "❌ *Telegram Signals:* `OFF`"
        else:
            status = "ON" if bot.telegram_signals_enabled else "OFF"
            return f"""📨 *Telegram Signals*

Status: `{status}`

*Usage:*
`/telegram on` - Enable
`/telegram off` - Disable"""

    # ------------------------------------------------------------------
    # Reset / Session Management
    # ------------------------------------------------------------------
    def _cmd_reset_session(self, args: str = "") -> str:
        bot = self.bot
        if not bot.session_manager:
            return "❌ Session manager not initialized"

        args = args.strip().lower()
        reset_session = reset_scanner = False

        if args == 'session':
            reset_session = True
            msg = "✅ **Session** statistics reset."
        elif args == 'scanner':
            reset_scanner = True
            msg = "✅ **Scanner** (asset cooldowns) reset."
        elif args in ('all', ''):
            reset_session = reset_scanner = True
            msg = "✅ **ALL** systems reset (Session, Scanner)."
        else:
            return """⚠️ Unknown reset mode.
            
Usage:
`/reset session` - Clear PnL/Stats
`/reset scanner` - Clear asset timers
`/reset all` - Reset everything"""

        if reset_session:
            bot.session_manager.reset_session()
            bot.signals_received = 0
            bot.signals_skipped = 0
            if bot.api_worker:
                bot.api_worker.active_trades.clear()
                if hasattr(bot.api_worker, 'cumulative_pnl'):
                    bot.api_worker.cumulative_pnl = 0.0

        if reset_scanner and bot.api_worker and bot.api_worker.scanner:
            bot.api_worker.scanner.asset_cooldowns.clear()

        if reset_session and bot.api_worker and bot.api_worker.scanner:
            if getattr(bot.api_worker, 'scanner_autostop_notified', False):
                bot.api_worker.set_scanner_enabled(True)
                bot.api_worker.scanner_autostop_notified = False
                msg += "\n🔍 Scanner re-enabled."
            else:
                msg += "\n🔍 Scanner is active."

        return msg

    # ------------------------------------------------------------------
    # Martingale
    # ------------------------------------------------------------------
    def _cmd_martingale(self, args: str) -> str:
        bot = self.bot
        if not bot.api_worker:
            return "❌ API worker not initialized"

        args = args.strip().lower()

        if args == 'on':
            bot.config['martingale_enabled'] = True
            bot.api_worker.set_martingale_enabled(True)

            base_amount = bot.config.get('position_sizing', {}).get('min_trade', 1.0)
            multiplier = bot.config.get('martingale_multiplier', 2.0)
            max_steps = bot.config.get('martingale_max_steps', 3)
            duration = bot.config.get('martingale_duration', 2)
            total_risk = sum(base_amount * (multiplier ** i) for i in range(max_steps + 1))

            worker = bot.api_worker
            scanner = getattr(worker, 'scanner', None)
            is_pullback = getattr(scanner, 'martingale_wait_for_pullback', False) if scanner else False
            pullback_str = '🟢 ON' if is_pullback else '🔴 OFF'

            return f"""🔁 *Martingale: ON*

Recovery up to {max_steps} steps on loss.
Multiplier: {multiplier}x
Duration: {duration}M (fixed)
Smart Pullback Mode: {pullback_str}
Gatekeeper Check: {'🟢 ON' if bot.api_worker.martingale_gatekeeper_enabled else '🔴 OFF (Bypass)'}

⚠️ Max risk per series: ~${total_risk:.2f}
(based on ${base_amount:.2f} min trade)"""

        elif args == 'off':
            bot.config['martingale_enabled'] = False
            bot.api_worker.set_martingale_enabled(False)
            return "🔁 *Martingale: OFF*\n\nLosses will not trigger recovery trades."

        parts = args.split()
        if len(parts) >= 2:
            cmd = parts[0]
            val = parts[1]
            try:
                if cmd == 'steps':
                    bot.api_worker.set_martingale_params('steps', int(val))
                    return f"✅ Martingale max steps set to {int(val)}"
                elif cmd == 'multiplier':
                    bot.api_worker.set_martingale_params('multiplier', float(val))
                    return f"✅ Martingale multiplier set to {val}x"
                elif cmd == 'duration':
                    duration = int(val)
                    allowed = tuple(
                        getattr(bot.api_worker, 'allowed_trade_durations', (2,))
                    )
                    if duration not in allowed:
                        return (
                            f"❌ {duration}m is outside the execution whitelist "
                            f"({', '.join(map(str, allowed))}m)."
                        )
                    bot.api_worker.set_martingale_params('duration', duration)
                    return f"✅ Martingale duration set to {duration}M"
                elif cmd == 'gatekeeper':
                    if val.lower() == 'on':
                        bot.api_worker.martingale_gatekeeper_enabled = True
                        return "✅ Martingale Gatekeeper: ON (Trades checked)"
                    elif val.lower() == 'off':
                        bot.api_worker.martingale_gatekeeper_enabled = False
                        return "✅ Martingale Gatekeeper: OFF (Trades bypassed)"
                    else:
                        return "❌ Usage: /martingale gatekeeper on|off"
            except ValueError:
                return "❌ Invalid number provided."

        status = bot.api_worker.get_martingale_status()
        enabled = "ON" if status['enabled'] else "OFF"
        worker = bot.api_worker
        scanner = getattr(worker, 'scanner', None)
        is_pullback = getattr(scanner, 'martingale_wait_for_pullback', False) if scanner else False
        pullback_str = '🟢 ON' if is_pullback else '🔴 OFF'

        return f"""🔁 *Martingale: {enabled}*

Max Steps: {status['max_steps']} (/martingale steps N)
Multiplier: {status['multiplier']}x (/martingale multiplier N)
Duration: {status['duration']}M (/martingale duration N)
Active Series: {status['active_series']}
Smart Pullback Mode: {pullback_str}
Gatekeeper Check: {'🟢 ON' if getattr(bot.api_worker, 'martingale_gatekeeper_enabled', False) else '🔴 OFF'}

Usage: /martingale on|off
       /martingale gatekeeper on|off"""




    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------
    def _cmd_sizing(self, args: str) -> str:
        bot = self.bot
        if not bot.position_sizer:
            return "❌ Position sizer not initialized"

        args = args.strip().lower()
        parts = args.split()
        cmd = parts[0] if parts else ""

        if not cmd:
            return f"💰 *Position Sizing*\n\nCurrent: {bot.position_sizer.get_description()}\n\nCommands:\n/sizing fixed <amount>\n/sizing percent <percentage>\n/sizing kelly <fraction>"

        if len(parts) >= 2:
            try:
                val = float(parts[1])
                from .models import SizingMethod
                if cmd == "fixed":
                    bot.position_sizer.method = SizingMethod.FIXED_AMOUNT
                    bot.position_sizer.fixed_amount = val
                    return f"✅ Sizing set to FIXED: ${val:.2f}"
                elif cmd == "percent":
                    bot.position_sizer.method = SizingMethod.FIXED_PERCENTAGE
                    bot.position_sizer.fixed_percentage = val / 100.0
                    return f"✅ Sizing set to PERCENTAGE: {val:.2f}%"
                elif cmd == "kelly":
                    bot.position_sizer.method = SizingMethod.FRACTIONAL_KELLY
                    bot.position_sizer.kelly_fraction = val
                    return f"✅ Sizing set to KELLY: {val:.2f} fraction"
            except Exception:
                return "❌ Invalid value"

        return "❌ Usage: /sizing fixed 5 | /sizing percent 2 | /sizing kelly 0.25"

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    async def _cmd_account(self, args: str = "") -> str:
        bot = self.bot
        if not bot.iq_api:
            return "❌ Not connected to IQ Option"
        try:
            balance = bot.iq_api.get_balance()
            mode = bot.iq_api.get_balance_mode() if hasattr(bot.iq_api, "get_balance_mode") else "UNKNOWN"
            mode_str = "🟢 REAL MONEY" if mode == "REAL" else "🟠 PRACTICE"
            
            if args.strip().lower() == "switch":
                new_mode = "PRACTICE" if mode == "REAL" else "REAL"
                bot.iq_api.change_balance(new_mode)
                balance = bot.iq_api.get_balance()
                return f"🔄 Account switched to: {new_mode}\n\n💰 Balance: ${balance:.2f}"
            
            return f"💰 *Account Info*\n\nMode: {mode_str}\nBalance: ${balance:.2f}\n\nType `/account switch` to toggle."
        except Exception as e:
            return f"❌ Error: {e}"

    # ------------------------------------------------------------------
    # Scanner
    # ------------------------------------------------------------------
    def _cmd_scanner(self, args: str) -> str:
        bot = self.bot
        if not bot.api_worker or not bot.api_worker.scanner:
            return "❌ Scanner not initialized"
        scanner = bot.api_worker.scanner
        
        args = args.strip().lower()
        parts = args.split()
        cmd = parts[0] if parts else ""
        value = parts[1] if len(parts) > 1 else ""
        
        if not cmd or cmd == 'status':
            enabled_str = "🟢 ON" if scanner.config.enabled else "🔴 OFF"
            profile = scanner.config.profile.value
            mode_val = getattr(getattr(scanner.config, "trade_mode", None), "value", "unknown")
            interval = scanner.config.interval
            
            # Strategy display
            strategy_str = scanner.config.scanner_strategy.upper()
            if scanner.config.active_strategies:
                strategy_str = f"HYBRID ({'+'.join(scanner.config.active_strategies)})"
            
            top_pairs = scanner.config.top_n_pairs or "all"
            tf_mode = "DYNAMIC" if scanner.config.dynamic_timeframe else "FIXED"
            base_dur = scanner.config.fixed_duration
            max_dur = scanner.config.max_duration
            
            scan_mode = scanner.config.scan_mode.upper()
            confluence = scanner.config.min_confluence
            autostop = "ON" if scanner.config.autostop_on_session_block else "OFF"
            regime_routing = "🟢 ON" if scanner.config.regime_routing_enabled else "🔴 OFF"
            ml_bypass = "⚠️ ON" if scanner.config.ml_bypass_risk_gates else "OFF"
            ml_signal_source = scanner.config.ml_signal_source.upper()
            ml_meta_gate = scanner.config.ml_meta_gate_mode.upper()
            catboost_state = (
                "ready"
                if scanner.catboost_gate.available
                else f"unavailable: {scanner.catboost_gate.disabled_reason}"
            )
            if scanner.catboost_gate.available:
                catboost_state += (
                    ", offline-approved"
                    if scanner.catboost_gate.offline_approved
                    else ", shadow-only"
                )
            directional_slot = scanner.strategy_engine.strategies.get(
                "ML_CatBoost_Directional"
            )
            directional_strategy = (
                directional_slot.strategy if directional_slot else None
            )
            directional_state = "not registered"
            if directional_strategy is not None:
                directional_state = (
                    "ready"
                    if directional_strategy.is_available
                    else f"unavailable: {directional_strategy.disabled_reason}"
                )
                if directional_strategy.is_available:
                    directional_state += (
                        ", offline-approved"
                        if directional_strategy.offline_approved
                        else ", research-only"
                    )
            ml_thresholds = scanner.get_ml_lstm_thresholds()
            ml_threshold = (
                f"{ml_thresholds[0]:.0%} (artifact: {ml_thresholds[1]:.0%})"
                if ml_thresholds else "unavailable"
            )

            # Sprint 1 Hard Gates
            rsi_extreme = "🟢 ON" if scanner.config.rsi_extreme_block else "🔴 OFF"
            exp_trap = "🟢 ON" if scanner.config.expansion_trap_block else "🔴 OFF"
            calm_conf = "🟢 ON" if scanner.config.calm_confluence_gate else "🔴 OFF"

            # Sprint 2 Quality Overlay
            quality_on = "🟢 ON" if scanner.config.quality_score_enabled else "🔴 OFF"
            put_boost = "🟢 ON" if scanner.config.put_boost_enabled else "🔴 OFF"
            stoch_tie = "🟢 ON" if scanner.config.stoch_tiebreaker else "🔴 OFF"
            run_cap_val = scanner.config.run_length_cap

            # Runtime info
            active_trades = len(bot.api_worker.active_trades) if bot.api_worker else 0
            otc_pairs_count = len(scanner.get_otc_pairs_callback()) if scanner.get_otc_pairs_callback else 0
            
            # Determine gate mode based on settings
            if scanner.config.rsi_extreme_block and scanner.config.run_length_cap == 4:
                gate_mode_str = "STRICT (All Sprint 1 & 2 gates enabled)"
            elif scanner.config.quality_score_enabled and scanner.config.calm_confluence_gate:
                gate_mode_str = "NORMAL (Quality Overlay & Calm Confluence enabled)"
            elif scanner.config.quality_score_enabled:
                gate_mode_str = "RELAXED (Only Quality Overlay enabled)"
            else:
                gate_mode_str = "OFF (No hard gates or quality scoring)"

            return f"""🔍 *OTC Scanner: {enabled_str}*

⚙️ *Settings:*
├ Profile: `{profile}`
├ Mode: `{mode_val} (concurrent)`
├ Interval: `{interval}s`
├ Strategy: `{strategy_str}`
├ Top Pairs: `{top_pairs}`
├ Timeframe: `{tf_mode}`
├ Base Expiry: `{base_dur}m`
├ Max Duration: `{max_dur}m`
├ Regime Routing: `{regime_routing}`
├ Scan Mode: `{scan_mode}`
├ Agreement: `{scanner.config.min_agreement}` strategies
├ Independent Families: `{scanner.config.min_independent_families}`
├ Fast-expiry Confluence: `{confluence}`
├ Auto-stop: `{autostop}`
├ ML Hard-Gate Bypass: `{ml_bypass}`
├ ML Signal Source: `{ml_signal_source}`
├ Directional CatBoost: `{directional_state}`
├ CatBoost Meta-Gate: `{ml_meta_gate}`
├ CatBoost Artifact: `{catboost_state}`
├ Minimum Payout: `{scanner.config.ml_min_payout:.0%}`
├ Minimum Model EV: `{scanner.config.ml_min_expected_value:.3f}`
└ LSTM Action Threshold: `{ml_threshold}`

🛡️ *Filter Gates:* `{gate_mode_str}`

📊 *Runtime:*
├ Status: `Running`
├ Active Trades: `{active_trades}`
└ OTC Pairs: `{otc_pairs_count}`

📋 *Commands:*
`/scanner on|off` - Toggle
`/scanner strategy indicators|mhi|adaptive|ccv2|hybrid|r7|majority|squeeze|rubber|apex|cascade|compression|sniper|exhaustion|ml_lstm|ml_catboost`
`/scanner strategy cascade+sniper+compression+exhaustion` - Custom combo
`/scanner scan_mode voting|tournament`
`/scanner agreement 1-6` - Min strategies that must agree (voting)
`/scanner families 1-6` - Min independent evidence families
`/scanner profile trend|reversal|mixed`
`/scanner mode single|multi`
`/scanner expiryconfluence 2-6` - Fast-expiry confidence threshold
`/scanner gates strict|normal|relaxed|off` - Consolidate filter gates
`/scanner mlsignal lstm|catboost|both|off` - Directional ML registration
`/scanner mlgate off|shadow|enforce` - Conditional CatBoost gate
`/scanner mlpayout 50-100` - Minimum accepted payout
`/scanner mledge 0-50` - Minimum EV percentage
`/scanner qualitymin 0-100` - Min quality score (when gates >= relaxed)
`/scanner regime on|off` - ATR Regime Routing
`/scanner interval 15-600`
`/scanner confidence 50-100`
`/scanner top 0-50 (0=all)`
`/scanner timeframe fixed|2` - Fixed, whitelisted expiry
`/scanner maxduration 1-5`
`/scanner precision on|off` - Second 58 Rule
`/scanner autostop on|off`
`/scanner mlbypass on|off` - ML-only hard-gate override (default on)
`/scanner mlthreshold 50-99` - Temporary LSTM action threshold
`/scanner blacklist` - Per-asset win tracking
`/scanner research` - Paper-only outcomes by strategy
`/scanner blacklist_min 12` - Min trades before blacklisting
`/scanner blacklist_rate 0.38` - Min win rate required
`/scanner blacklist_reset` - Clear all performance data

Use `/scanner on|off` to toggle."""

        if cmd == 'on':
            bot.api_worker.set_scanner_enabled(True)
            return "✅ *Scanner:* `ON`"
            
        if cmd == 'off':
            bot.api_worker.set_scanner_enabled(False)
            return "❌ *Scanner:* `OFF`"

        if cmd == 'mode':
            if value not in ('single', 'multi'):
                return "❌ Use `single` or `multi`"
            bot.api_worker.set_scanner_trade_mode(value)
            return f"🔍 *Mode:* `{value}`"
            
        if cmd == 'strategy':
            valid_strategies = ['indicators', 'mhi', 'majority', 'r7', 'ccv2', 'adaptive', 'hybrid', 'squeeze', 'rubber', 'apex', 'cascade', 'compression', 'sniper', 'exhaustion', 'ml_lstm', 'ml_catboost']

            if '+' in value:
                combo = value.split('+')
                invalid = [s for s in combo if s not in valid_strategies]
                if invalid:
                    return f"❌ Invalid strategy in combo: {', '.join(invalid)}"
                combo_ml = {item for item in combo if item in {'ml_lstm', 'ml_catboost'}}
                if combo_ml == {'ml_lstm', 'ml_catboost'}:
                    scanner.configure_ml(signal_source='both')
                elif combo_ml == {'ml_lstm'}:
                    scanner.configure_ml(signal_source='lstm')
                elif combo_ml == {'ml_catboost'}:
                    scanner.configure_ml(signal_source='catboost')

                # Map standard names to engine names exactly
                name_map = {
                    'indicators': 'Indicators', 'mhi': 'MHI', 'majority': 'Majority',
                    'r7': 'R7', 'ccv2': 'CCV2', 'adaptive': 'Adaptive',
                    'squeeze': 'Squeeze Breakout', 'rubber': 'Rubber Band', 'apex': 'Apex Exhaustion',
                    'cascade': 'Momentum Cascade', 'compression': 'Compression Breakout',
                    'sniper': 'Late Candle Sniper', 'exhaustion': 'Exhaustion Fade',
                    'ml_lstm': 'ML_LSTM',
                    'ml_catboost': 'ML_CatBoost_Directional',
                }
                
                scanner.config.scanner_strategy = 'hybrid'
                scanner.config.active_strategies = [name_map.get(c, c.upper()) for c in combo]
                return f"🔍 *Strategy:* `HYBRID (CUSTOM)`\n\nActive: {', '.join(scanner.config.active_strategies)}"
            else:
                if value not in valid_strategies:
                    return f"❌ Invalid strategy. Use: {', '.join(valid_strategies)}"
                if value == 'ml_catboost' and scanner.config.ml_signal_source not in ('catboost', 'both'):
                    scanner.configure_ml(signal_source='catboost')
                elif value == 'ml_lstm' and scanner.config.ml_signal_source not in ('lstm', 'both'):
                    scanner.configure_ml(signal_source='lstm')
                scanner.config.scanner_strategy = value
                scanner.config.active_strategies = []
                return f"🔍 *Strategy:* `{value.upper()}`"

        if cmd == 'scan_mode':
            if value not in ('voting', 'tournament'):
                return f"❌ Invalid mode. Use: voting, tournament"
            scanner.config.scan_mode = value
            return f"🔍 *Scan Mode:* `{value.upper()}`"
            
        if cmd == 'profile':
            valid = ('trend', 'reversal', 'mixed')
            if value not in valid:
                return f"❌ Invalid profile. Use: {', '.join(valid)}"
            scanner.config.profile = ScannerProfile(value)
            return f"🔍 *Profile:* `{value.upper()}`"

        if cmd == 'pullback':
            return "❌ `/scanner pullback` is unavailable: it has no scanner decision path."

        if cmd == 'interval':
            try:
                secs = int(value)
                bot.api_worker.set_scanner_interval(secs)
                return f"🔍 *Interval:* `{secs}s`"
            except ValueError:
                return "❌ Invalid number"

        if cmd in ('confluence', 'expiryconfluence'):
            try:
                c = int(value)
                scanner.config.min_confluence = max(2, min(6, c))
                return f"🔍 *Fast-expiry Confluence:* `{scanner.config.min_confluence}`"
            except ValueError:
                return "❌ Invalid number"

        if cmd == 'agreement':
            try:
                n = int(value)
                active_names = scanner._get_active_strategy_names()
                if scanner.config.scanner_strategy.lower() == 'hybrid' and not scanner.config.active_strategies:
                    max_agreement = len(scanner.strategy_engine.strategies)
                else:
                    max_agreement = len(active_names)
                if not 1 <= n <= max_agreement:
                    return f"❌ Min agreement must be between 1 and {max_agreement}"
                scanner.config.min_agreement = n
                return f"🔍 *Min Agreement:* `{n}` strategies must agree to trade"
            except ValueError:
                return "❌ Invalid number. Usage: `/scanner agreement 2`"

        if cmd in ('families', 'independent'):
            try:
                n = int(value)
                if not 1 <= n <= 6:
                    return "❌ Independent families must be between 1 and 6"
                scanner.config.min_independent_families = n
                return (
                    f"🔍 *Independent Families:* `{n}` distinct evidence "
                    "families must agree in multi-strategy voting"
                )
            except ValueError:
                return "❌ Usage: `/scanner families 2`"

        if cmd == 'confidence':
            try:
                val = float(value.replace('%', ''))
                if val > 1: val = val / 100.0
                scanner.set_confidence(val)
                return f"🔍 *Min Confidence:* `{val:.0%}`"
            except ValueError:
                return "❌ Invalid number"

        if cmd == 'top':
            try:
                n = int(value)
                scanner.config.top_n_pairs = n
                return f"🔍 *Top Assets:* `{n if n > 0 else 'All'}`"
            except ValueError:
                return "❌ Invalid number"
                
        if cmd == 'timeframe':
            allowed_durations = tuple(
                getattr(bot.api_worker, 'allowed_trade_durations', (2,))
            )
            if value == 'dynamic':
                return (
                    "❌ Dynamic duration is disabled for the verified cohort. "
                    f"Allowed execution duration(s): {', '.join(map(str, allowed_durations))}m"
                )
            elif value == 'fixed':
                scanner.set_timeframe_mode(False)
                return f"🔍 *Timeframe:* `FIXED ({scanner.config.fixed_duration}m)`"
            else:
                try:
                    mins = int(value)
                    if mins not in allowed_durations:
                        return (
                            f"❌ {mins}m is outside the execution whitelist "
                            f"({', '.join(map(str, allowed_durations))}m)."
                        )
                    scanner.set_fixed_duration(mins)
                    scanner.set_timeframe_mode(False)
                    return f"🔍 *Timeframe:* `FIXED ({mins}m)`"
                except ValueError:
                    return "❌ Use `dynamic`, `fixed`, or a number 1-5"

        if cmd == 'maxduration':
            try:
                m = int(value)
                if not 1 <= m <= 5:
                    return "❌ Max duration must be between 1 and 5 minutes"
                scanner.config.max_duration = m
                return f"⏱️ *Max Duration:* `{m} min`"
            except ValueError:
                return "❌ Invalid number"



        if cmd == 'precision':
            enabled = value in ('on', 'true', '1')
            scanner.config.scanner_precision_timing = enabled
            return f"✅ Precision Execution (Sec 58 Rule): **{'ON' if enabled else 'OFF'}**"

        if cmd == 'autostop':
            enabled = value in ('on', 'true', '1')
            scanner.config.autostop_on_session_block = enabled
            return f"🛑 Auto-stop on Session Limit: **{'ON' if enabled else 'OFF'}**"

        if cmd == 'mlbypass':
            if value not in ('on', 'off'):
                return "❌ Usage: `/scanner mlbypass on|off`"
            enabled = value == 'on'
            scanner.set_ml_bypass_risk_gates(enabled)
            if enabled:
                return (
                    "⚠️ *ML Scanner Hard-Gate Bypass:* **ON**\n\n"
                    "Applies only when an LSTM or directional CatBoost model "
                    "wins a scanner decision. "
                    "It skips scanner hard/quality filters only; strategy agreement, "
                    "session limits, sizing, cooldowns, and execution safeguards remain active."
                )
            return "✅ *ML Scanner Hard-Gate Bypass:* **OFF**"

        if cmd == 'mlthreshold':
            try:
                threshold = float(value)
                if threshold > 1:
                    threshold /= 100.0
                current, artifact = scanner.set_ml_lstm_threshold(threshold)
                return (
                    f"⚠️ *LSTM Runtime Threshold:* **{current:.0%}**\n\n"
                    f"Artifact threshold: `{artifact:.0%}`. This change is practice-only "
                    "operator state and resets on restart; it does not alter the model file."
                )
            except ValueError:
                return "❌ Usage: `/scanner mlthreshold 50-99`"
            except RuntimeError as exc:
                return f"❌ {exc}"

        if cmd == 'gates':
            if value not in ('strict', 'normal', 'relaxed', 'off'):
                return "❌ Usage: `/scanner gates [strict|normal|relaxed|off]`"

            if value == 'strict':
                scanner.config.rsi_extreme_block = True
                scanner.config.expansion_trap_block = True
                scanner.config.wick_magnet_block = True
                scanner.config.calm_confluence_gate = True
                scanner.config.quality_score_enabled = True
                scanner.config.put_boost_enabled = True
                scanner.config.stoch_tiebreaker = True
                scanner.config.run_length_cap = 4
                return "🛡️ *Gates:* `STRICT` (All Sprint 1 & 2 gates ENABLED)"
            elif value == 'normal':
                scanner.config.rsi_extreme_block = False
                scanner.config.expansion_trap_block = False
                scanner.config.wick_magnet_block = False
                scanner.config.calm_confluence_gate = True
                scanner.config.quality_score_enabled = True
                scanner.config.put_boost_enabled = True
                scanner.config.stoch_tiebreaker = False
                scanner.config.run_length_cap = 6
                return "🛡️ *Gates:* `NORMAL` (Quality Overlay & Calm Confluence ENABLED)"
            elif value == 'relaxed':
                scanner.config.rsi_extreme_block = False
                scanner.config.expansion_trap_block = False
                scanner.config.wick_magnet_block = False
                scanner.config.calm_confluence_gate = False
                scanner.config.quality_score_enabled = True
                scanner.config.put_boost_enabled = False
                scanner.config.stoch_tiebreaker = False
                scanner.config.run_length_cap = 8
                return "🛡️ *Gates:* `RELAXED` (Only Quality Overlay ENABLED)"
            else:
                scanner.config.rsi_extreme_block = False
                scanner.config.expansion_trap_block = False
                scanner.config.wick_magnet_block = False
                scanner.config.calm_confluence_gate = False
                scanner.config.quality_score_enabled = False
                scanner.config.put_boost_enabled = False
                scanner.config.stoch_tiebreaker = False
                scanner.config.run_length_cap = 0
                return "🛡️ *Gates:* `OFF` (All hard gates and quality scoring DISABLED)"

        if cmd == 'mlgate':
            valid_modes = ('off', 'shadow', 'enforce')
            if value not in valid_modes:
                return f"❌ Usage: `/scanner mlgate [{'|'.join(valid_modes)}]`"
            scanner.configure_ml(meta_gate_mode=value)
            warning = (
                "\n⚠️ Enforce fails closed unless the artifact is offline-approved."
                if value == 'enforce' else ""
            )
            return f"🤖 *CatBoost Meta-Gate:* `{value.upper()}`{warning}"

        if cmd == 'mlsignal':
            if value not in ('lstm', 'catboost', 'both', 'off'):
                return "❌ Usage: `/scanner mlsignal lstm|catboost|both|off`"
            scanner.configure_ml(signal_source=value)
            return f"🤖 *ML Signal Source:* `{value.upper()}`"

        if cmd == 'mlpayout':
            try:
                payout = float(value)
                if payout > 1:
                    payout /= 100.0
                if not 0.50 <= payout <= 1.0:
                    raise ValueError
                scanner.config.ml_min_payout = payout
                return f"💰 *CatBoost Minimum Payout:* `{payout:.0%}`"
            except ValueError:
                return "❌ Usage: `/scanner mlpayout 50-100`"

        if cmd == 'mledge':
            try:
                edge = float(value)
                if edge > 1:
                    edge /= 100.0
                if not 0.0 <= edge <= 0.50:
                    raise ValueError
                scanner.config.ml_min_expected_value = edge
                return f"📈 *CatBoost Minimum Expected Value:* `{edge:.3f}`"
            except ValueError:
                return "❌ Usage: `/scanner mledge 0-50`"

        if cmd == 'regime':
            enabled = value in ('on', 'true', '1')
            scanner.config.regime_routing_enabled = enabled
            if enabled:
                return ("🔀 *Regime Routing:* **ON**\n\n"
                        "📈 *Trending* (ATR > avg + directional candles):\n"
                        "  → Cascade, Compression, Squeeze, Sniper, Indicators (2/5)\n"
                        "📊 *Ranging* (ATR ≤ avg):\n"
                        "  → Exhaustion Fade, Adaptive, CCV2, Rubber Band, Apex (2/5)\n\n"
                        "⚠️ Overrides strategy combo per-asset. Disable to use manual combo.")
            else:
                return "🔀 *Regime Routing:* **OFF**\n\nUsing configured strategy combo."

        if cmd == 'blacklist':
            # Show top 5 worst performing assets
            stats = getattr(scanner, 'asset_performance', {})
            if not stats:
                return "🔍 *Scanner Blacklist*\n\nNo performance data yet."
            
            worst = []
            for asset, data in stats.items():
                w, l = data.get('wins', 0), data.get('losses', 0)
                if w + l >= 3:
                    wr = w / (w + l)
                    if wr < 0.4:
                        worst.append((asset, wr, w + l))
            
            worst.sort(key=lambda x: x[1])
            if not worst:
                return "🔍 *Scanner Blacklist*\n\nAll assets performing within thresholds."
            
            output = "🔍 *Asset Blacklist (Low WR)*\n\n"
            count = 0
            for a, r, t in worst:
                output += f"├ `{a}`: {r:.0%} win rate ({t} trades)\n"
                count += 1
                if count >= 8:
                    break
            return output.strip()

        if cmd == 'research':
            logger = getattr(scanner, 'candidate_research', None)
            if logger is None or not logger.enabled:
                return (
                    "🧪 *Strategy Research*\n\n"
                    "Candidate research is disabled. Set "
                    "`CANDIDATE_RESEARCH_ENABLED=true` and restart."
                )
            rows = logger.strategy_summary()
            if not rows:
                return (
                    "🧪 *Strategy Research*\n\n"
                    "No paper candidates have been resolved yet."
                )

            payout = float(
                getattr(bot.api_worker, 'payout_rate', 0.80) or 0.80
            )
            breakeven = 1.0 / (1.0 + payout)
            lines = [
                "🧪 *Paper Strategy Outcomes*",
                "",
                f"Assumed payout: `{payout:.0%}` | "
                f"Breakeven: `{breakeven:.1%}`",
                "",
            ]
            for row in rows[:20]:
                decided = row["wins"] + row["losses"]
                win_rate = row["wins"] / decided if decided else 0.0
                lines.append(
                    f"`{row['strategy']}` — {row['wins']}W/"
                    f"{row['losses']}L/{row['ties']}T "
                    f"({win_rate:.1%}, n={decided}, "
                    f"pending={row['pending']})"
                )
            lines.extend([
                "",
                "Paper candle outcomes are research data, not broker-verified "
                "execution results. Do not promote a strategy from a small "
                "sample or raw win rate alone.",
            ])
            return "\n".join(lines)

        if cmd == 'blacklist_min':
            try:
                n = int(value)
                scanner.config.blacklist_min_trades = n
                return f"🛡️ *Blacklist Min Trades:* `{n}`"
            except ValueError:
                return "❌ Usage: `/scanner blacklist_min 12`"

        if cmd == 'blacklist_rate':
            try:
                r = float(value)
                if r > 1: r /= 100.0
                scanner.config.blacklist_win_rate = r
                return f"🛡️ *Blacklist Win Rate:* `{r:.0%}`"
            except ValueError:
                return "❌ Usage: `/scanner blacklist_rate 0.38`"

        if cmd == 'blacklist_reset':
            scanner.asset_performance.clear()
            return "✅ *Scanner Blacklist:* `RESET` (all historical performance cleared)"
            
        return f"🔍 *Scanner*\n\nUnknown command: `{cmd}`"

    # ------------------------------------------------------------------
    # Gatekeeper & Threshold
    # ------------------------------------------------------------------
    def _cmd_gatekeeper(self, args: str) -> str:
        bot = self.bot
        if not bot.api_worker:
            return "❌ API worker not initialized"
        
        args = args.strip().lower()
        parts = args.split()
        cmd = parts[0] if parts else ""
        value = parts[1] if len(parts) > 1 else None
        
        worker = bot.api_worker
        valid_modes = ('strict', 'normal', 'relaxed', 'very_relaxed')
        
        if cmd == 'on':
            worker.use_gatekeeper = True
            return "🔍 *Gatekeeper: ON*\n\nGlobal risk limits and cooldowns are active."
            
        if cmd == 'off':
            worker.use_gatekeeper = False
            return "🔍 *Gatekeeper: OFF*\n\n⚠️ Global risk filters bypassed."
            
        if cmd == 'mode' and value in valid_modes:
            worker.set_gatekeeper_mode_telegram(value)
            worker.set_gatekeeper_mode_scanner(value)
            return f"🔍 *Gatekeeper Mode:* `{value.upper()}`\n\nGlobal risk thresholds updated."
            
        status = worker.get_gatekeeper_status()
        enabled = "🟢 ON" if status['enabled'] else "🔴 OFF"
        mode_val = status.get('mode_scanner') or 'unknown'
        alpha = "🟢 ON" if getattr(worker.gatekeeper_scanner, 'alpha_hours_enabled', False) else "🔴 OFF"
        
        gatekeeper = worker.gatekeeper_scanner
        threshold = gatekeeper._manual_threshold or "Auto"

        return f"""🔍 *Gatekeeper: {enabled}*

⚙️ *Settings:*
├ Mode: `{mode_val.upper()}`
├ Alpha Hours: `{alpha}`
├ Threshold Override: `{threshold}`
└ Loss Streak Cooldown: `{status['loss_streak_cooldown']} trades`

📋 *Commands:*
/gatekeeper on|off
/gatekeeper mode strict|normal|relaxed|very_relaxed
/threshold scanner 80
/alphahours on|off"""

    def _cmd_alphahours(self, args: str) -> str:
        bot = self.bot
        if not bot.api_worker:
            return "❌ API worker not initialized"
        
        args = args.strip().lower()
        worker = bot.api_worker
        
        if args == 'on':
            worker.gatekeeper_scanner.alpha_hours_enabled = True
            worker.gatekeeper_telegram.alpha_hours_enabled = True
            return "✅ *Alpha Hours Gatekeeper:* `ON`\n\nTrades will only execute during historically favorable hours."
        elif args == 'off':
            worker.gatekeeper_scanner.alpha_hours_enabled = False
            worker.gatekeeper_telegram.alpha_hours_enabled = False
            return "❌ *Alpha Hours Gatekeeper:* `OFF`\n\n⚠️ Bot will trade 24/7 without time-of-day filtering."
        else:
            status = "ON" if worker.gatekeeper_scanner.alpha_hours_enabled else "OFF"
            return f"🕒 *Alpha Hours Gatekeeper:* `{status}`\n\nUsage: `/alphahours on|off`"

    def _cmd_threshold(self, args: str) -> str:
        bot = self.bot
        if not bot.api_worker:
            return "❌ API worker not initialized"
            
        parts = args.split()
        if len(parts) != 2:
            return "⚠️ Usage:\n`/threshold scanner 80`\n`/threshold telegram 25`\n`/threshold <target> none`"
            
        target, value_str = parts[0].lower(), parts[1].lower()
        gatekeeper = bot.api_worker.gatekeeper_scanner if target == 'scanner' else bot.api_worker.gatekeeper_telegram if target == 'telegram' else None
        
        if not gatekeeper:
            return "⚠️ Target must be 'scanner' or 'telegram'"
            
        if value_str in ('none', 'default', 'reset'):
            gatekeeper.set_manual_threshold(None)
            return f"✅ {target.capitalize()} threshold override removed."
            
        try:
            val = float(value_str)
            gatekeeper.set_manual_threshold(val)
            return f"✅ {target.capitalize()} threshold set to **{val}**."
        except ValueError:
            return "⚠️ Threshold must be a number."

    # ------------------------------------------------------------------
    # Martingale Mode
    # ------------------------------------------------------------------
    def _cmd_martingale_mode(self, args: str) -> str:
        """Switch martingale recovery strategy: classic or pullback."""
        bot = self.bot
        if not bot.api_worker:
            return "❌ API worker not initialized"

        args = args.strip().lower()
        scanner = getattr(bot.api_worker, 'scanner', None)

        if args == 'classic':
            if scanner:
                scanner.martingale_wait_for_pullback = False
            bot.config['martingale_wait_for_pullback'] = False
            return "🔁 *Martingale Mode:* `CLASSIC`\n\nImmediate recovery on loss (same direction or flip)."
        elif args == 'pullback':
            if scanner:
                scanner.martingale_wait_for_pullback = True
            bot.config['martingale_wait_for_pullback'] = True
            return "🔁 *Martingale Mode:* `PULLBACK`\n\nWaits for validated scanner signal before recovery step."
        else:
            current = "PULLBACK" if bot.config.get('martingale_wait_for_pullback', False) else "CLASSIC"
            return f"""🔁 *Martingale Mode:* `{current}`

Usage:
`/martingale_mode classic` - Immediate recovery
`/martingale_mode pullback` - Wait for scanner signal"""

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    def _cmd_cache(self) -> str:
        """Show data provider cache statistics."""
        bot = self.bot
        if not bot.api_worker:
            return "❌ API worker not initialized"

        dp = bot.api_worker.data_provider
        status = dp.get_status()

        return f"""📦 *Cache Statistics*

MTF Enabled: `{'YES' if status['mtf_enabled'] else 'NO'}`
Cache Entries: `{status['cache_entries']}`
Cache TTL: `{status['cache_ttl']}s`
Cache Hits: `{status['cache_hits']}`
Cache Misses: `{status['cache_misses']}`
Hit Rate: `{status['cache_hit_rate']:.1f}%`"""

    # ------------------------------------------------------------------
    # Weights
    # ------------------------------------------------------------------
    def _cmd_weights(self, args: str) -> str:
        """Show or adjust strategy weights in the strategy engine."""
        bot = self.bot
        if not bot.api_worker or not bot.api_worker.scanner:
            return "❌ Scanner not initialized"

        engine = bot.api_worker.scanner.strategy_engine
        args = args.strip().lower()

        if args == 'reset':
            # Reset all strategy weights to their initial values
            for slot in engine.strategies.values():
                slot.wins = 0
                slot.losses = 0
                slot.ties = 0
            return "✅ Strategy performance stats reset. Weights return to base values."

        parts = args.split()
        if len(parts) == 2:
            # Set weight for a specific strategy: /weights cascade 1.5
            name_input = parts[0]
            try:
                new_weight = float(parts[1])
            except ValueError:
                return "❌ Invalid weight value. Usage: `/weights cascade 1.5`"

            # Find strategy by partial name match (case-insensitive)
            found = None
            for reg_name, slot in engine.strategies.items():
                if name_input in reg_name.lower():
                    found = (reg_name, slot)
                    break

            if not found:
                return f"❌ Strategy `{name_input}` not found. Use `/weights` to see all."

            found[1].weight = max(0.0, min(5.0, new_weight))
            return f"✅ `{found[0]}` weight set to `{found[1].weight:.1f}` (effective: `{found[1].effective_weight:.2f}`)"

        # Default: show all strategy weights
        stats = engine.get_stats()
        if not stats:
            return "⚖️ No strategies registered."

        lines = ["⚖️ *Strategy Weights*\n"]
        for name, s in sorted(stats.items()):
            wr = s['win_rate']
            eff = s['effective_weight']
            lines.append(
                f"├ `{name}`: base=`{s['weight']:.1f}` eff=`{eff}` "
                f"| {s['wins']}W/{s['losses']}L ({wr})"
            )
        lines.append(f"\n*Commands:*")
        lines.append(f"`/weights` - Show all")
        lines.append(f"`/weights <name> <value>` - Set weight (0-5)")
        lines.append(f"`/weights reset` - Reset performance stats")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Patterns
    # ------------------------------------------------------------------
    async def _cmd_patterns(self, args: str) -> str:
        """Show technical analysis / patterns for a given asset."""
        bot = self.bot
        if not bot.api_worker:
            return "❌ API worker not initialized"

        asset = args.strip().upper()
        if not asset:
            return "❌ Usage: `/patterns EURUSD`\n\nShows candlestick patterns and indicator analysis for the asset."

        # Normalize to OTC
        if not asset.endswith('-OTC') and not asset.endswith('-OP'):
            asset = f"{asset}-OTC"

        try:
            candles = await bot.api_worker.get_market_data(
                asset.replace("-OTC", "").replace("-OP", ""),
                timeframe=120,
                candle_count=50
            )
            if not candles or len(candles) < 10:
                return f"❌ Not enough candle data for `{asset}`."

            # Indicator analysis
            indicators = bot.market_analyzer.calculate_indicators(candles, symbol=asset)
            if not indicators:
                return f"❌ Could not calculate indicators for `{asset}`."

            # Pattern analysis
            pattern_result = bot.pattern_analyzer.analyze(candles)
            patterns = pattern_result.get('patterns', [])
            pattern_names = [p.get('name', 'Unknown') for p in patterns[:5]]

            rsi = indicators.get('rsi', 'N/A')
            trend = indicators.get('trend', 'N/A')
            adx = indicators.get('adx', 'N/A')
            momentum = indicators.get('momentum', 'N/A')
            bb_pos = indicators.get('bb_position', 'N/A')
            stoch_k = indicators.get('stoch_k', 'N/A')
            stoch_d = indicators.get('stoch_d', 'N/A')
            vol = indicators.get('volatility_regime', 'N/A')

            return f"""📊 *Technical Analysis: {asset}*

📈 *Indicators:*
├ RSI: `{rsi:.2f if isinstance(rsi, float) else rsi}`
├ Trend: `{trend}`
├ ADX: `{adx:.1f if isinstance(adx, float) else adx}`
├ Momentum: `{momentum:.4f if isinstance(momentum, float) else momentum}%`
├ BB Position: `{bb_pos:.2f if isinstance(bb_pos, float) else bb_pos}`
├ Stoch K/D: `{stoch_k:.1f if isinstance(stoch_k, float) else stoch_k}`/`{stoch_d:.1f if isinstance(stoch_d, float) else stoch_d}`
└ Volatility: `{vol}`

🔍 *Patterns Detected:*
{chr(10).join(f'├ {p}' for p in pattern_names) if pattern_names else '└ None detected'}"""

        except Exception as e:
            return f"❌ Error analyzing `{asset}`: {e}"

    # ------------------------------------------------------------------
    # Fingerprint Stats
    # ------------------------------------------------------------------
    def _cmd_fpstats(self, args: str) -> str:
        """Show fingerprint database statistics and field coverage."""
        bot = self.bot
        if not bot.api_worker:
            return "❌ API worker not initialized"

        db = getattr(bot.api_worker, 'fingerprint_db', None)
        if not db:
            return "❌ Fingerprint database not initialized"

        records = db.records
        total = len(records)
        if total == 0:
            return "🧠 *Fingerprint DB*\n\nNo records yet."

        # Count wins/losses
        wins = sum(1 for r in records if r.result == 'win')
        losses = sum(1 for r in records if r.result == 'loss')
        pending = sum(1 for r in records if not r.result)

        # Sprint 4 field coverage
        has_source = sum(1 for r in records if r.source)
        has_quality = sum(1 for r in records if r.quality_score is not None)
        has_regime = sum(1 for r in records if r.regime)
        has_expansion = sum(1 for r in records if r.body_expansion is not None)
        has_run = sum(1 for r in records if r.run_length is not None)
        has_adx = sum(1 for r in records if r.adx is not None and r.adx > 0)
        has_strategy = sum(1 for r in records if r.strategy_used and r.strategy_used not in ('', 'unknown', 'scanner', 'telegram'))

        # Win rate by source (Sprint 4 field)
        scanner_records = [r for r in records if r.source == 'scanner' and r.result in ('win', 'loss')]
        telegram_records = [r for r in records if r.source == 'telegram' and r.result in ('win', 'loss')]
        scanner_wr = (sum(1 for r in scanner_records if r.result == 'win') / len(scanner_records) * 100) if scanner_records else 0
        telegram_wr = (sum(1 for r in telegram_records if r.result == 'win') / len(telegram_records) * 100) if telegram_records else 0

        # Win rate by regime (Sprint 4 field)
        trending_records = [r for r in records if r.regime == 'trending' and r.result in ('win', 'loss')]
        ranging_records = [r for r in records if r.regime == 'ranging' and r.result in ('win', 'loss')]
        trending_wr = (sum(1 for r in trending_records if r.result == 'win') / len(trending_records) * 100) if trending_records else 0
        ranging_wr = (sum(1 for r in ranging_records if r.result == 'win') / len(ranging_records) * 100) if ranging_records else 0

        # Average quality score by outcome
        win_q = [r.quality_score for r in records if r.result == 'win' and r.quality_score is not None]
        loss_q = [r.quality_score for r in records if r.result == 'loss' and r.quality_score is not None]
        avg_win_q = sum(win_q) / len(win_q) if win_q else 0
        avg_loss_q = sum(loss_q) / len(loss_q) if loss_q else 0

        return f"""🧠 *Fingerprint DB Stats*

📊 *Records:* {total} ({wins}W / {losses}L / {pending} pending)

📈 *Win Rate by Source:*
├ Scanner: {scanner_wr:.1f}% ({len(scanner_records)} trades)
└ Telegram: {telegram_wr:.1f}% ({len(telegram_records)} trades)

🔀 *Win Rate by Regime:*
├ Trending: {trending_wr:.1f}% ({len(trending_records)} trades)
└ Ranging: {ranging_wr:.1f}% ({len(ranging_records)} trades)

⭐ *Avg Quality Score:*
├ Winners: {avg_win_q:.1f}
└ Losers: {avg_loss_q:.1f}

🔧 *Sprint 4 Field Coverage:*
├ source: {has_source}/{total}
├ quality_score: {has_quality}/{total}
├ regime: {has_regime}/{total}
├ body_expansion: {has_expansion}/{total}
├ run_length: {has_run}/{total}
├ adx: {has_adx}/{total}
└ strategy_used: {has_strategy}/{total}"""
