"""
Result Checker Module — Handles trade result determination.

Extracted from worker.py to reduce the god object. Contains:
- Balance-based result checking (v1 and v2)
- Force result determination
- Single result API checks
- Result checking loop
"""

import time
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .worker import APIWorker

logger = logging.getLogger(__name__)


class ResultChecker:
    """Checks trade results using balance comparison and API methods."""

    def __init__(self, worker: "APIWorker"):
        self._w = worker  # Parent worker reference for shared state

    @property
    def api(self):
        return self._w.api

    async def check_results_loop(self):
        """
        Periodically check results of active trades.

        Strategy: Try API-based check first (more reliable), fall back
        to balance comparison if API returns pending.

        For multi-trade scenarios:
        - Process trades ONE AT A TIME in order of expiry
        - Take a balance snapshot BEFORE checking each trade
        - After determining result, update snapshot for next trade
        """
        print("📊 Result checker started (using balance comparison)")
        last_status_time = 0

        while self._w.running:
            try:
                await asyncio.sleep(3)

                loop = asyncio.get_event_loop()
                current_time = time.time()
                completed = []

                # Status update every 30 seconds
                if self._w.active_trades and current_time - last_status_time > 30:
                    last_status_time = current_time
                    pending_info = []
                    for oid, info in self._w.active_trades.items():
                        time_left = info['expiry_time'] - current_time
                        if time_left > 0:
                            pending_info.append(f"{info['asset']}:{time_left:.0f}s")
                        else:
                            pending_info.append(f"{info['asset']}:checking")
                    if pending_info:
                        print(f"\n📋 Active trades ({len(pending_info)}): {', '.join(pending_info[:5])}")

                # Get expired trades sorted by expiry time (oldest first)
                expired_trades = [
                    (oid, info) for oid, info in self._w.active_trades.items()
                    if current_time >= info['expiry_time']
                ]
                expired_trades.sort(key=lambda x: x[1]['expiry_time'])

                # Process expired trades ONE AT A TIME with balance lock
                for order_id, trade_info in expired_trades:
                    try:
                        trade_info['order_id'] = order_id
                        async with self._w.balance_check_lock:
                            trade_info['check_attempts'] = trade_info.get('check_attempts', 0) + 1
    
                            if trade_info['check_attempts'] == 1:
                                print(f"\n⏳ Checking result for Trade {order_id} ({trade_info['asset']} {trade_info['direction'].upper()})...")
                                # Take fresh balance snapshot for this check
                                try:
                                    self._w.last_known_balance = await loop.run_in_executor(None, self.api.get_balance)
                                    trade_info['balance_snapshot'] = self._w.last_known_balance
                                except Exception:
                                    pass
    
                            # Try API check first (most reliable) — retry up to 3 times
                            result = "pending"
                            profit = 0
                            result_method = "api"
                            for _api_attempt in range(3):
                                try:
                                    result, profit = await self.check_single_result(order_id, trade_info['amount'])
                                except Exception:
                                    result = "pending"
                                    profit = 0
                                if result != "pending":
                                    break
                                await asyncio.sleep(3)

                            # Fall back to balance comparison if API exhausted
                            if result == "pending":
                                result, profit = await self.check_result_by_balance_v2(trade_info)
                                result_method = "balance"
    
                            # If still pending and deadline not reached, continue waiting
                            result_deadline = trade_info.get('result_deadline', trade_info['expiry_time'] + 60)
                            if result == "pending":
                                if current_time > result_deadline:
                                    # Deadline exceeded - force determination
                                    print(f"   ⚠️ Result check inconclusive after {trade_info['check_attempts']} attempts, forcing...")
                                    result, profit = await self.force_result_determination(trade_info)
                                    result_method = "forced"

                                    if result == "pending" or result == "unknown":
                                        # Still can't determine — assume TIE (not loss).
                                        # A false tie (0 PnL) is far less damaging to
                                        # session stats and fingerprint data quality than
                                        # a false loss (-$amount).
                                        print(f"\n⏰ Trade {order_id} result unknown — assuming tie (money returned)")
                                        result = "tie"
                                        profit = 0
                                        result_method = "forced"
                                else:
                                    # Still waiting - log periodically
                                    if trade_info['check_attempts'] % 3 == 0:
                                        time_left = result_deadline - current_time
                                        print(f"   ⏳ Trade {order_id} pending (attempt {trade_info['check_attempts']}, {time_left:.0f}s to deadline)...")
                                    continue
    
                            # Store result_method on trade_info so _handle_result can access it
                            trade_info['result_method'] = result_method

                            # Trade result determined - update balance snapshot for next trade
                            try:
                                # Brief delay to let API balance settle before next check
                                await asyncio.sleep(0.5)
                                self._w.last_known_balance = await loop.run_in_executor(None, self.api.get_balance)
                            except Exception:
                                pass
    
                            completed.append(order_id)
                            if result != "pending":
                                print(f"   📋 Result determined via {result_method} method")
    
                        # Get current balance for notifications (outside lock)
                        if result != "pending":
                            try:
                                current_balance = await loop.run_in_executor(None, self.api.get_balance)
                            except Exception:
                                current_balance = self._w.last_known_balance or 0
                        else:
                            current_balance = self._w.last_known_balance or 0
    
                        # Process the result via the worker's handler
                        await self._handle_result(order_id, trade_info, result, profit, current_balance)
                    
                    except Exception as loop_e:
                        print(f"   ⚠️ Error processing trade {order_id}: {loop_e}")
                        import traceback
                        traceback.print_exc()

                # Remove completed trades
                for order_id in completed:
                    del self._w.active_trades[order_id]

            except Exception as e:
                error_str = str(e).lower()
                # Detect connection errors
                if 'closed' in error_str or 'connection' in error_str:
                    self._w.is_connected = False
                    print(f"⚠️ Connection lost during result check - will retry after reconnect")
                    await asyncio.sleep(5)
                    continue

                import traceback
                print(f"⚠️ Result checker error: {e}")
                traceback.print_exc()

    async def _handle_result(self, order_id: int, trade_info: dict,
                             result: str, profit: float, current_balance: float):
        """Process a determined trade result — notifications, session, martingale."""
        
        # Update Session Cumulative PnL (for accurate result verification of concurrent trades)
        if result in ("win", "lose", "tie"):
            current_pnl = getattr(self._w, "cumulative_pnl", 0.0)
            self._w.cumulative_pnl = current_pnl + profit
            
        # Extract martingale info
        martingale_step = trade_info.get('martingale_step', 0)
        series_id = trade_info.get('martingale_series_id')
        is_in_martingale_series = series_id is not None
        step_label = f" [M{martingale_step}]" if martingale_step > 0 else ""

        # Generate notification
        notification_msg = None
        if result == "win":
            print(f"\n🎉 TRADE WON!{step_label}")
            print(f"   Order: {order_id}")
            print(f"   Asset: {trade_info['asset']} {trade_info['direction'].upper()}")
            print(f"   Profit: +${profit:.2f}")
            print(f"   Balance: ${current_balance:.2f}")
            notification_msg = f"🎉 *TRADE WON!{step_label}*\n\nAsset: {trade_info['asset']}\nDirection: {trade_info['direction'].upper()}\nAmount: ${trade_info['amount']:.2f}\nProfit: +${profit:.2f}\n💰 Balance: ${current_balance:.2f}"

            # Martingale series won - finalize and report
            if is_in_martingale_series and series_id in self._w.active_martingale_series:
                series_data = self._w.active_martingale_series[series_id]
                net_result = profit - series_data.get('cumulative_loss', 0)
                notification_msg += f"\n\n🔁 *Martingale Recovery Successful!*\nSeries Net: ${net_result:.2f}"
                print(f"   🔁 Martingale series {series_id} WON - Net: ${net_result:.2f}")
                self._w.martingale.finalize_series(series_id, "won")

        elif result == "lose":
            print(f"\n😔 TRADE LOST!{step_label}")
            print(f"   Order: {order_id}")
            print(f"   Asset: {trade_info['asset']} {trade_info['direction'].upper()}")
            print(f"   Loss: -${abs(profit):.2f}")
            print(f"   Balance: ${current_balance:.2f}")
            notification_msg = f"😔 *TRADE LOST{step_label}*\n\nAsset: {trade_info['asset']}\nDirection: {trade_info['direction'].upper()}\nAmount: ${trade_info['amount']:.2f}\nLoss: -${abs(profit):.2f}\n💰 Balance: ${current_balance:.2f}"

            # Handle martingale on loss
            if is_in_martingale_series or self._w.martingale_enabled:
                await self._w.martingale.handle_loss(trade_info, series_id, notification_msg)

        elif result == "tie":
            print(f"\n🔄 TRADE TIE!{step_label}")
            print(f"   Order: {order_id}")
            print(f"   Asset: {trade_info['asset']} {trade_info['direction'].upper()}")
            print(f"   Amount returned.")
            print(f"   Balance: ${current_balance:.2f}")
            profit = 0
            notification_msg = f"🔄 *TRADE TIE{step_label}*\n\nAsset: {trade_info['asset']}\nDirection: {trade_info['direction'].upper()}\nAmount returned.\n💰 Balance: ${current_balance:.2f}"

            # Tie ends the martingale series (money returned, no loss to recover)
            if is_in_martingale_series:
                self._w.martingale.finalize_series(series_id, "tie")
        else:
            print(f"\n❓ Trade {order_id} result: {result}")
            notification_msg = f"❓ *Trade Result Unknown*\n\nAsset: {trade_info['asset']}\nDirection: {trade_info['direction'].upper()}"

        # Update logger
        self._w.logger.update_result(order_id, result, profit)

        # Update confidence tracker
        if result in ("win", "lose"):
            confidence = trade_info.get('confidence', 0.0)
            source = trade_info.get('source', 'telegram')
            self._w.confidence_tracker.record(confidence, source, result == "win")

        # Update per-asset performance tracking (for scanner auto-blacklist)
        asset_name = trade_info.get('asset', '')
        if result in ("win", "lose"):
            if asset_name and hasattr(self._w, 'scanner'):
                self._w.scanner.record_asset_result(asset_name, result == "win")

        # Update StrategyEngine win/loss tracking for dynamic effective_weight calculation
        if result in ("win", "lose", "tie"):
            if not trade_info.get('result_recorded', False):
                engine = None
                if hasattr(self._w, 'scanner') and self._w.scanner and hasattr(self._w.scanner, 'strategy_engine'):
                    engine = self._w.scanner.strategy_engine
                elif hasattr(self._w, 'strategy_engine') and self._w.strategy_engine:
                    engine = self._w.strategy_engine

                if engine:
                    winning_strat = trade_info.get('winning_strategy', '') or trade_info.get('strategy_used', '')
                    if winning_strat:
                        strat_name = winning_strat.split('+')[0].strip()
                        is_martingale = (martingale_step > 0)
                        engine.record_result(strat_name, result, is_martingale=is_martingale)
                        print(f"   📊 StrategyEngine recorded {result.upper()} for [{strat_name}] (Martingale: {is_martingale})")

                trade_info['result_recorded'] = True

        # Phase 3 Fingerprint Saving
        if result in ("win", "lose", "tie"):

            # Ensure we only log the fingerprint once per trade
            if not trade_info.get('fingerprinted', False):
                fingerprint = trade_info.get('fingerprint')
                if fingerprint:
                    # Update fingerprint with the final result
                    fingerprint.result = result
                    fingerprint.profit = profit
                    # Tag how the result was determined (api / balance / forced)
                    fingerprint.result_method = trade_info.get('result_method', 'unknown')

                    # Retrieve the global Fingerprint Database from the worker
                    if hasattr(self._w, 'fingerprint_db'):
                        self._w.fingerprint_db.add_fingerprint(fingerprint)
                        print(f"   🧠 Fingerprint saved: {result.upper()} ({asset_name}) [via {fingerprint.result_method}]")

                # Lock the save so subsequent balance checks don't re-trigger it
                trade_info['fingerprinted'] = True

        # Update session manager
        # Losses during martingale are registered by the martingale module
        # (either per-step or as cumulative series loss at finalization).
        # We must NOT register them here to avoid double-counting.
        should_register_session = True
        if result == "lose" and (is_in_martingale_series or self._w.martingale_enabled):
            should_register_session = False  # Martingale module handles loss PnL

        if self._w.session_manager and should_register_session:
            self._w.session_manager.register_result(profit)
            stats = self._w.session_manager.get_session_stats()
            win_rate = self._w.logger.get_win_rate() * 100
            print(f"   📊 Session: ${stats['pnl']:.2f} | Trades: {stats['trades']} | Win Rate: {win_rate:.1f}% | Streak: {stats['consecutive_losses']}L")
            if notification_msg:
                notification_msg += f"\n\n📊 *Session Stats:*\nPnL: ${stats['pnl']:.2f} | Trades: {stats['trades']}\nWin Rate: {win_rate:.1f}% | Losses: {stats['consecutive_losses']}L"

        # Update gatekeeper for loss streak tracking
        if self._w.use_gatekeeper:
            # Only record Win or Loss. Ties are neutral and should not reset streak OR count as loss.
            if result in ("win", "lose"):
                won = result == "win"
                source = trade_info.get('source', 'telegram')
                
                # Select appropriate gatekeeper
                target_gatekeeper = None
                if source == 'scanner':
                     target_gatekeeper = getattr(self._w, 'gatekeeper_scanner', None)
                else:
                     target_gatekeeper = getattr(self._w, 'gatekeeper_telegram', None)
                
                # Fallback for backward compatibility
                if not target_gatekeeper and hasattr(self._w, 'gatekeeper'):
                     target_gatekeeper = self._w.gatekeeper

                if target_gatekeeper:
                    target_gatekeeper.record_result(won)
                    gk_stats = target_gatekeeper.get_stats()
                    pass # Cooldown active print logic removed
            elif result == "tie":
                 print(f"   ⚖️ Tie result - Gatekeeper streak preserved (Neutral)")

        # Send notification
        if notification_msg and self._w.notification_callback:
            try:
                await self._w.notification_callback(notification_msg)
                print(f"   ✅ Notification sent to Telegram")
            except Exception as e:
                print(f"   ⚠️ Could not send notification: {e}")
        elif notification_msg:
            print(f"   ⚠️ No notification callback configured")

    async def check_result_by_balance_v2(self, trade_info: dict) -> Tuple[str, float]:
        """
        Robust balance check using 'Book Value' (Cash + Active Stakes) to handle concurrent trades.
        
        Logic:
        1. Calculate Current Book Value = Current Cash + Sum(Stakes of OTHER active trades)
        2. Calculate Expected Book Value = Original Book Value + (Current PnL - Start PnL)
        
        This invariant holds true regardless of other trades winning/losing/opening.
        """
        loop = asyncio.get_event_loop()

        try:
            current_time = time.time()

            # SAFEGUARD: Check if other trades expired within 10 seconds
            this_expiry = trade_info.get('expiry_time', 0)
            overlapping_trades = [
                oid for oid, info in self._w.active_trades.items()
                if oid != trade_info.get('order_id') and
                abs(info.get('expiry_time', 0) - this_expiry) < 10 and
                current_time >= info.get('expiry_time', 0)
            ]

            if overlapping_trades and trade_info.get('check_attempts', 0) < 3:
                return "pending", 0.0

            # Get current balance
            current_balance = await loop.run_in_executor(None, self.api.get_balance)
            
            # 1. Calculate Current Book Value (Cash + Other Active Stakes)
            current_active_stakes = sum(
                info['amount'] for oid, info in self._w.active_trades.items()
                if oid != trade_info.get('order_id')
            )
            current_book_value = current_balance + current_active_stakes
            
            # 2. Calculate Expected Reference Book Value
            # Original Book Value = (Balance_After + Amount + Other_Stakes_At_Placement)
            balance_after = trade_info.get('after_trade_balance', 0)
            amount = trade_info.get('amount', 0)
            other_stakes_at_start = trade_info.get('active_stakes_at_placement', 0)
            
            # Fallback if fields missing (old trades)
            if balance_after == 0: 
                balance_after = trade_info.get('balance_snapshot', 0)
            
            original_book_value = balance_after + amount + other_stakes_at_start
            
            # Adjust for PnL realized since placement
            start_pnl = trade_info.get('started_with_pnl', 0.0)
            current_pnl = getattr(self._w, 'cumulative_pnl', 0.0)
            pnl_drift = current_pnl - start_pnl
            
            reference_book_value = original_book_value + pnl_drift
            
            # Compare
            diff = current_book_value - reference_book_value
            payout_rate = trade_info.get('payout_rate', self._w.payout_rate)
            expected_profit = amount * payout_rate
            
            print(f"   💰 Book Value Check: Current=${current_book_value:.2f}, Ref=${reference_book_value:.2f}, Diff=${diff:+.2f}")
            print(f"      (Cash=${current_balance:.2f}, Actives=${current_active_stakes:.2f}, PnL Drift=${pnl_drift:+.2f})")

            # Win: Book Value increases by Profit
            if diff >= expected_profit * 0.8:
                return "win", diff # Return actual profit diff

            # Tie: Book Value stays same (diff ~ 0)
            if abs(diff) < amount * 0.3:
                 return "tie", 0.0
                 
            # Loss: Book Value decreases by Amount
            # But wait! original_book_value included the amount (as stake).
            # If lost, the stake is gone. 
            # So current_book_value should be original_book_value - amount.
            # So diff should be -amount.
            
            if diff <= -amount * 0.8:
                return "lose", diff # Return actual loss diff

            return "pending", 0.0


        except Exception as e:
            error_str = str(e).lower()
            if 'closed' in error_str or 'connection' in error_str:
                self._w.is_connected = False
            return "pending", 0.0

    async def check_result_by_balance(self, trade_info: dict) -> Tuple[str, float]:
        """
        Determine trade result by comparing current balance with pre-trade balance.
        NOTE: Less reliable with multiple concurrent trades — prefer v2.
        """
        loop = asyncio.get_event_loop()

        try:
            current_balance = await loop.run_in_executor(None, self.api.get_balance)
            balance_before = trade_info.get('balance_before', 0)
            amount = trade_info.get('amount', 0)
            payout_rate = trade_info.get('payout_rate', self._w.payout_rate)

            if balance_before == 0:
                return "pending", 0.0

            expected_win_amount = amount * payout_rate
            balance_change = current_balance - balance_before
            win_threshold = expected_win_amount * 0.8
            tie_threshold = 0.50
            loss_threshold = amount * 0.8

            print(f"   💰 Balance check: Before=${balance_before:.2f}, Now=${current_balance:.2f}, Change=${balance_change:.2f}")

            if balance_change >= win_threshold:
                return "win", balance_change
            elif abs(balance_change) <= tie_threshold:
                return "tie", 0.0
            elif balance_change <= -loss_threshold:
                return "lose", balance_change
            else:
                return "pending", 0.0

        except Exception as e:
            error_str = str(e).lower()
            if 'closed' in error_str or 'connection' in error_str:
                self._w.is_connected = False
            else:
                print(f"   ⚠️ Balance check error: {e}")
            return "pending", 0.0

    async def force_result_determination(self, trade_info: dict) -> Tuple[str, float]:
        """Force a result determination when deadline exceeded."""
        loop = asyncio.get_event_loop()

        try:
            current_balance = await loop.run_in_executor(None, self.api.get_balance)

            baseline = trade_info.get('balance_after_trade')
            if baseline is None or baseline == 0:
                balance_before = trade_info.get('balance_before', 0)
                amount = trade_info.get('amount', 0)
                baseline = balance_before - amount if balance_before > 0 else 0

            amount = trade_info.get('amount', 0)
            payout_rate = trade_info.get('payout_rate', self._w.payout_rate)

            if baseline == 0 or amount == 0:
                return "unknown", 0.0

            expected_win_return = amount * (1 + payout_rate)
            balance_change = current_balance - baseline

            print(f"   💰 Force check: Baseline=${baseline:.2f}, Now=${current_balance:.2f}, Change=${balance_change:+.2f}")

            if balance_change >= expected_win_return * 0.6:
                profit = balance_change - amount
                return "win", profit

            if balance_change >= amount * 0.6 and balance_change < expected_win_return * 0.6:
                return "tie", 0.0

            if abs(balance_change) < amount * 0.4:
                return "lose", -amount

            return "lose", -amount

        except Exception as e:
            print(f"   ⚠️ Force determination error: {e}")
            return "unknown", 0.0

    async def check_single_result(self, order_id: int, amount: float) -> Tuple[str, float]:
        """Check result of a single trade via API."""
        loop = asyncio.get_event_loop()

        try:
            # Timeout to prevent hanging on unresponsive API
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda oid=order_id: self.api.check_win_v4(oid)
                ),
                timeout=4.0
            )

            print(f"   🔍 API check_win_v4 returned: {result!r} (type: {type(result).__name__})")

            if result is None:
                return "pending", 0.0

            # Handle tuple results: ('win', 0.85) or ('loose', -1.0)
            if isinstance(result, tuple):
                if len(result) >= 2:
                    status_str = str(result[0]).lower()
                    api_profit = float(result[1])
                    
                    if status_str in ('win', 'won'):
                        # Use API profit if it looks valid, otherwise calculate
                        profit = api_profit if api_profit > 0 else amount * self._w.payout_rate
                        return "win", profit
                    elif status_str in ('lose', 'lost', 'loss', 'loose'):
                        return "lose", -amount
                    elif status_str in ('tie', 'equal', 'draw'):
                        return "tie", 0.0
                    else:
                        return "pending", 0.0
                elif len(result) == 1:
                    result = result[0]
                else:
                    return "pending", 0.0

            if isinstance(result, str):
                result_lower = result.lower()
                if result_lower in ('win', 'won'):
                    return "win", amount * self._w.payout_rate
                elif result_lower in ('lose', 'lost', 'loss', 'loose'):
                    return "lose", -amount
                elif result_lower in ('tie', 'equal', 'draw'):
                    return "tie", 0.0
                else:
                    return "pending", 0.0

            if isinstance(result, (int, float)):
                if result > 0:
                    return "win", float(result)
                elif result < 0:
                    return "lose", float(result)
                else:
                    # result == 0 means tie (amount returned, no profit)
                    return "tie", 0.0

            return "pending", 0.0

        except asyncio.TimeoutError:
            print(f"   ⚠️ API check_win_v4 timed out (3s) for order {order_id}")
            return "pending", 0.0
        except Exception as e:
            print(f"   ⚠️ API check error: {e}")
            return "pending", 0.0

    async def check_single_result_aggressive(self, order_id: int, amount: float) -> Tuple[str, float]:
        """Aggressive result check using multiple methods."""
        loop = asyncio.get_event_loop()

        # Try check_win_v4 first
        result, profit = await self.check_single_result(order_id, amount)
        if result != "pending":
            return result, profit

        try:
            if hasattr(self.api, 'check_win_v4'):
                try:
                    api_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda oid=order_id: self.api.check_win_v4(oid)
                        ),
                        timeout=8.0
                    )
                    if api_result is not None and api_result != 0:
                        if isinstance(api_result, (int, float)):
                            if api_result > 0:
                                return "win", float(api_result)
                            elif api_result < 0:
                                return "lose", float(api_result)
                except asyncio.TimeoutError:
                    print(f"   ⚠️ check_win_v4 timed out for order {order_id}")

            if hasattr(self.api, 'check_win'):
                try:
                    api_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda oid=order_id: self.api.check_win(oid)
                        ),
                        timeout=8.0
                    )
                    if api_result is not None:
                        if isinstance(api_result, bool):
                            if api_result:
                                return "win", amount * self._w.payout_rate
                            else:
                                return "lose", -amount
                        elif isinstance(api_result, (int, float)) and api_result != 0:
                            if api_result > 0:
                                return "win", float(api_result)
                            else:
                                return "lose", float(api_result)
                except asyncio.TimeoutError:
                    print(f"   ⚠️ check_win timed out for order {order_id}")

        except Exception as e:
            error_str = str(e).lower()
            if 'closed' in error_str or 'connection' in error_str:
                self._w.is_connected = False

        return "pending", 0.0
