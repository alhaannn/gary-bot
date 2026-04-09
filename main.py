"""
GaryBot - Automated Gold Trading Bot (Multi-Channel)

Main orchestrator that coordinates MT5, Telegram listener, and signal processing
for multiple channels with isolated state.

Usage:
    python main.py

Ensure MT5 terminal is running and you're logged in before starting.
First run will prompt for Telegram phone verification.
"""

import asyncio
import os
import signal
import sys
from datetime import datetime
from typing import Optional, Dict

# Import config first (others depend on it)
import config

# Import logger and initialize ASAP
from logger import get_logger
logger = get_logger()

# Import other modules
from signal_parser import parse_signal
from trade_manager import (
    load_trades, add_trade_group, save_trades,
    get_open_groups, get_partial_eligible_groups,
    mark_ticket_closed, mark_partial_applied
)
from trade_executor import (
    connect_mt5, disconnect_mt5,
    open_multiple_trades, close_trade, move_sl_to_breakeven, modify_sl,
    calculate_entry_price, calculate_tp_from_pips
)
from telegram_listener import start_multi_listener
from telethon.errors import PersistentTimestampOutdatedError
import MetaTrader5 as mt5


def get_channel_config(channel_name: str) -> Optional[Dict]:
    """Get channel configuration by name. Supports legacy single-channel mode."""
    if config.USE_LEGACY_SINGLE_CHANNEL:
        # In legacy mode, return a default config for 'gary' using legacy channel
        if channel_name == "gary":
            return {
                "name": "gary",
                "username": config.LEGACY_CHANNEL,
                "enabled": True,
                "trades_per_signal": 2,
                "prompt_file": "prompts/gary.txt"
            }
        return None

    # Multi-channel mode: search in CHANNELS list
    for ch in config.CHANNELS:
        if ch["name"] == channel_name:
            return ch
    return None


async def handle_message(message_text: str, channel_name: str):
    """
    Main message handler called from Telegram listener for each new message.

    Args:
        message_text: Raw message from Telegram
        channel_name: Name of the channel this message came from
    """
    try:
        logger.info("=" * 80)
        logger.info(f"[{channel_name}] 📥 Received: {message_text[:100]}{'...' if len(message_text) > 100 else ''}")

        # Parse signal using channel-specific prompt
        parsed = parse_signal(message_text, channel_name)

        signal_type = parsed.get("type", "UNKNOWN")
        logger.info(f"[{channel_name}] 🏷️  Signal type: {signal_type}")

        # Route to appropriate handler
        if signal_type == "ENTRY":
            signal_id = datetime.now().strftime("%Y%m%d%H%M%S")
            await handle_trade_entry(parsed, signal_id, channel_name)

        elif signal_type == "PARTIAL":
            await handle_partial_signal(parsed, channel_name)

        elif signal_type == "CLOSE":
            await handle_close_signal(parsed, channel_name)

        elif signal_type == "SL_HIT":
            await handle_sl_hit_signal(parsed, channel_name)

        elif signal_type == "SL_MODIFY":
            await handle_sl_modify_signal(parsed, channel_name)

        elif signal_type == "IGNORE":
            logger.debug(f"[{channel_name}] ⏭️ IGNORE - Skipping")
        else:
            logger.warning(f"[{channel_name}] ❓ Unknown signal type: {signal_type}")

        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"[{channel_name}] ❌ Unhandled exception in handle_message: {e}")
        import traceback
        logger.debug(f"[{channel_name}] Traceback: {traceback.format_exc()}")


async def handle_trade_entry(parsed: dict, signal_id: str, channel_name: str):
    """
    Handle ENTRY signal: open multiple trades and persist state.

    Args:
        parsed: Parsed signal dictionary
        signal_id: Unique signal identifier
        channel_name: Channel identifier
    """
    logger.info(f"[{channel_name}] 🎯 Processing ENTRY signal {signal_id}")

    direction = parsed["direction"]
    entry_high = parsed["entry_high"]
    entry_low = parsed["entry_low"]
    sl = parsed["sl"]

    # Calculate entry price
    entry_price = calculate_entry_price(entry_high, entry_low)
    logger.info(f"[{channel_name}] Entry price (midpoint): {entry_price:.2f}")

    # Get channel config for number of trades
    channel_config = get_channel_config(channel_name)
    if not channel_config:
        logger.error(f"[{channel_name}] Channel config not found, aborting")
        return

    trades_count = channel_config.get("trades_per_signal", 2)
    if trades_count not in [2, 4]:
        logger.warning(f"[{channel_name}] Unsupported trades_per_signal: {trades_count}, defaulting to 2")
        trades_count = 2

    # Build TP list based on trades_count, supporting both price and pips
    tp_values = []
    for i in range(1, trades_count + 1):
        tp_price = parsed.get(f"tp{i}")
        if tp_price is not None:
            tp_values.append(float(tp_price))
        else:
            tp_pips = parsed.get(f"tp{i}_pips")
            if tp_pips is not None:
                tp = calculate_tp_from_pips(direction, entry_price, int(tp_pips))
                tp_values.append(tp)
            else:
                tp_values.append(None)  # Missing TP

    # If we have trailing None values and some earlier TPs, duplicate last non-None TP for missing ones
    # This ensures we open the requested number of trades
    if any(v is None for v in tp_values):
        # Find last non-None value
        last_valid = None
        for v in tp_values:
            if v is not None:
                last_valid = v
        if last_valid is not None:
            tp_values = [v if v is not None else last_valid for v in tp_values]
        else:
            # All None -> no TPs provided, will open without TP (TP=0.0)
            tp_values = [None] * trades_count

    logger.info(f"[{channel_name}] TP values for {trades_count} trades: {tp_values}")

    # Extract TP1 and TP2 for auto management (first two non-None TPs)
    tp1 = None
    tp2 = None
    for val in tp_values:
        if val is not None:
            if tp1 is None:
                tp1 = float(val)
            elif tp2 is None:
                tp2 = float(val)
                break

    # Open multiple trades (smart routing: market or pending)
    tickets = open_multiple_trades(
        direction=direction,
        sl=sl,
        tps=tp_values,
        signal_id=signal_id,
        channel_name=channel_name,
        count=trades_count,
        entry_high=entry_high,
        entry_low=entry_low
    )

    if not tickets:
        logger.error(f"[{channel_name}] ❌ Failed to open trades for signal {signal_id}")
        return

    # Persist to channel-specific trades file, including TP levels for auto management
    success = add_trade_group(
        signal_id=signal_id,
        direction=direction,
        entry_price=entry_price,
        sl=sl,
        tickets=tickets,
        channel_name=channel_name,
        tp1=tp1,
        tp2=tp2
    )

    if success:
        logger.info(f"[{channel_name}] ✅ ENTRY signal {signal_id} fully processed: {direction} @ {entry_price:.2f}, {len(tickets)} trades opened")
    else:
        logger.error(f"[{channel_name}] ❌ ENTRY signal {signal_id} trades opened but failed to save state")


async def handle_partial_signal(parsed: dict, channel_name: str):
    """
    Handle PARTIAL signal: close half of open trades per group, move remaining to breakeven.

    Args:
        parsed: Parsed signal dictionary
        channel_name: Channel identifier
    """
    logger.info(f"[{channel_name}] 🔄 Processing PARTIAL signal")

    eligible_groups = get_partial_eligible_groups(channel_name)

    if not eligible_groups:
        logger.warning(f"[{channel_name}] ⚠️ No eligible groups for partial close")
        return

    logger.info(f"[{channel_name}] Processing {len(eligible_groups)} eligible group(s)")

    for group in eligible_groups:
        signal_id = group["signal_id"]
        tickets = group.get("tickets", [])
        closed_tickets = group.get("closed_tickets", [])
        open_tickets = [t for t in tickets if t not in closed_tickets]

        if not open_tickets:
            logger.debug(f"[{channel_name}] Group {signal_id} has no open tickets, skipping")
            continue

        # Determine how many to close: close half (floor division) and move half to breakeven
        close_count = len(open_tickets) // 2
        # Ensure at least one closes if there's any open
        if close_count == 0 and len(open_tickets) > 0:
            close_count = 1
        breakeven_count = len(open_tickets) - close_count

        close_tickets = open_tickets[:close_count]
        breakeven_tickets = open_tickets[close_count:]

        logger.info(f"[{channel_name}] Group {signal_id}: closing {close_count} trades, moving {breakeven_count} to breakeven")

        # Close selected tickets
        for ticket in close_tickets:
            if close_trade(ticket, signal_id):
                mark_ticket_closed(signal_id, ticket, channel_name)
            else:
                logger.error(f"[{channel_name}] ❌ Failed to close ticket {ticket} for {signal_id}")

        # Move remaining to breakeven
        entry_price = group["entry_price"]
        for ticket in breakeven_tickets:
            if not move_sl_to_breakeven(ticket, entry_price, signal_id):
                logger.error(f"[{channel_name}] ❌ Failed to move ticket {ticket} to breakeven for {signal_id}")

        # Mark partial applied
        mark_partial_applied(signal_id, channel_name)


async def handle_close_signal(parsed: dict, channel_name: str):
    """
    Handle CLOSE signal: close all remaining open trades.

    Args:
        parsed: Parsed signal dictionary
        channel_name: Channel identifier
    """
    logger.info(f"[{channel_name}] 🔒 Processing CLOSE signal")

    open_groups = get_open_groups(channel_name)

    if not open_groups:
        logger.warning(f"[{channel_name}] ⚠️ No open groups to close")
        return

    logger.info(f"[{channel_name}] Closing {len(open_groups)} open group(s)")

    for group in open_groups:
        signal_id = group["signal_id"]
        tickets = group.get("tickets", [])
        closed_tickets = group.get("closed_tickets", [])
        open_tickets = [t for t in tickets if t not in closed_tickets]

        if not open_tickets:
            logger.debug(f"[{channel_name}] Group {signal_id} has no open tickets")
            continue

        for ticket in open_tickets:
            if close_trade(ticket, signal_id):
                mark_ticket_closed(signal_id, ticket, channel_name)
            else:
                logger.error(f"[{channel_name}] ❌ Failed to close ticket {ticket} for {signal_id}")


async def handle_sl_hit_signal(parsed: dict, channel_name: str):
    """
    Handle SL_HIT signal: MT5 auto-closed via stop loss.
    Mark all open trades as closed in state.

    Args:
        parsed: Parsed signal dictionary
        channel_name: Channel identifier
    """
    logger.info(f"[{channel_name}] ⚠️ Processing SL_HIT signal (MT5 auto-close)")

    open_groups = get_open_groups(channel_name)

    if not open_groups:
        logger.warning(f"[{channel_name}] ⚠️ No open groups to mark as SL-hit")
        return

    logger.info(f"[{channel_name}] Marking {len(open_groups)} group(s) as closed (SL hit)")

    for group in open_groups:
        signal_id = group["signal_id"]
        tickets = group.get("tickets", [])
        closed_tickets = group.get("closed_tickets", [])
        open_tickets = [t for t in tickets if t not in closed_tickets]

        for ticket in open_tickets:
            # MT5 already closed it, just mark in state
            mark_ticket_closed(signal_id, ticket, channel_name)


async def handle_sl_modify_signal(parsed: dict, channel_name: str):
    """
    Handle SL_MODIFY signal: modify stop loss on open positions.
    Supports both absolute price (new_sl) and pips-based (new_sl_pips).

    Args:
        parsed: Parsed signal dictionary
        channel_name: Channel identifier
    """
    logger.info(f"[{channel_name}] 🔧 Processing SL_MODIFY signal")

    new_sl_abs = parsed.get("new_sl")  # May be None if using pips
    new_sl_pips = parsed.get("new_sl_pips")  # May be None if using absolute

    if new_sl_abs is None and new_sl_pips is None:
        logger.warning(f"[{channel_name}] ⚠️ SL_MODIFY: no valid SL value provided")
        return

    open_groups = get_open_groups(channel_name)

    if not open_groups:
        logger.warning(f"[{channel_name}] ⚠️ No open groups to modify SL")
        return

    success_count = 0
    for group in open_groups:
        signal_id = group["signal_id"]
        tickets = group.get("tickets", [])
        closed_tickets = group.get("closed_tickets", [])
        open_tickets = [t for t in tickets if t not in closed_tickets]

        # Compute new_sl for this group if using pips
        group_new_sl = new_sl_abs
        if new_sl_pips is not None:
            direction = group["direction"]
            entry_price = group["entry_price"]
            # Convert pips to price: XAUUSD: 1 pip = 0.1
            pips_price = new_sl_pips * config.PIP_MULTIPLIER
            if direction == "BUY":
                group_new_sl = entry_price - pips_price
            else:  # SELL
                group_new_sl = entry_price + pips_price
            logger.debug(f"[{channel_name}] Computed SL from {new_sl_pips} pips: {group_new_sl:.2f} (entry={entry_price}, dir={direction})")

        for ticket in open_tickets:
            if modify_sl(ticket, group_new_sl, signal_id):
                success_count += 1
            else:
                logger.error(f"[{channel_name}] ❌ Failed to modify SL for ticket {ticket}")

    if success_count > 0:
        logger.info(f"[{channel_name}] ✅ SL_MODIFY: Modified {success_count} position(s) to {group_new_sl:.2f}")
    else:
        logger.warning(f"[{channel_name}] ⚠️ No positions were modified")


# ========== Automatic TP Management ==========
async def tp_monitor():
    """
    Background task that monitors open positions for TP1/TP2 levels.
    Requires AUTO_TP_MANAGEMENT = True in config.
    """
    logger.info("[TP Monitor] ✅ Started")
    while True:
        try:
            await asyncio.sleep(getattr(config, 'TP_MONITOR_INTERVAL', 5))

            # Ensure MT5 is connected; if not, skip this cycle
            if not mt5.initialize(login=config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER):
                logger.error("[TP Monitor] MT5 not initialized, skipping...")
                continue

            tick = mt5.symbol_info_tick(config.SYMBOL)
            if not tick:
                logger.debug("[TP Monitor] No tick data for symbol")
                continue

            bid = tick.bid
            ask = tick.ask

            # Determine channels to monitor
            if config.USE_LEGACY_SINGLE_CHANNEL:
                channels_to_monitor = [{"name": "gary"}]
            else:
                channels_to_monitor = [c for c in config.CHANNELS if c["enabled"]]

            for ch in channels_to_monitor:
                ch_name = ch["name"]
                open_groups = get_open_groups(ch_name)
                for group in open_groups:
                    signal_id = group["signal_id"]
                    tp1 = group.get("tp1")
                    tp2 = group.get("tp2")
                    if tp1 is None or tp2 is None:
                        continue  # this group not set up for auto TP

                    direction = group["direction"]
                    partial_applied = group.get("partial_applied", False)

                    # Check TP1 hit
                    if not partial_applied:
                        if (direction == "BUY" and bid >= tp1) or (direction == "SELL" and ask <= tp1):
                            logger.info(f"[TP Monitor] {ch_name} {signal_id}: TP1 reached ({tp1}) - applying partial close")

                            # Load fresh state
                            trades = load_trades(ch_name)
                            target_group = None
                            for g in trades:
                                if g["signal_id"] == signal_id:
                                    target_group = g
                                    break
                            if not target_group:
                                continue

                            all_tickets = target_group.get("tickets", [])
                            closed_tickets = target_group.get("closed_tickets", [])
                            open_tickets = [t for t in all_tickets if t not in closed_tickets]

                            if not open_tickets:
                                continue

                            # Determine how many to close: half (at least 1)
                            close_count = len(open_tickets) // 2
                            if close_count == 0 and len(open_tickets) > 0:
                                close_count = 1
                            to_close = open_tickets[:close_count]
                            to_be = open_tickets[close_count:]

                            # Close selected tickets
                            for ticket in to_close:
                                if close_trade(ticket, signal_id):
                                    mark_ticket_closed(signal_id, ticket, ch_name)
                                else:
                                    logger.error(f"[TP Monitor] Failed to close ticket {ticket}")

                            # Move remaining to breakeven
                            entry_price = target_group["entry_price"]
                            for ticket in to_be:
                                if not move_sl_to_breakeven(ticket, entry_price, signal_id):
                                    logger.error(f"[TP Monitor] Failed to move ticket {ticket} to BE")

                            # Mark partial applied
                            target_group["partial_applied"] = True
                            save_trades(trades, ch_name)
                            logger.info(f"[TP Monitor] {ch_name} {signal_id}: Partial complete (closed {len(to_close)}, moved {len(to_be)} to BE)")
                            # After partial, skip TP2 for this group in this cycle
                            continue

                    # Check TP2 hit (full close)
                    if (direction == "BUY" and bid >= tp2) or (direction == "SELL" and ask <= tp2):
                        logger.info(f"[TP Monitor] {ch_name} {signal_id}: TP2 reached ({tp2}) - closing all remaining")

                        trades = load_trades(ch_name)
                        target_group = None
                        for g in trades:
                            if g["signal_id"] == signal_id:
                                target_group = g
                                break
                        if not target_group:
                            continue

                        all_tickets = target_group.get("tickets", [])
                        closed_tickets = target_group.get("closed_tickets", [])
                        open_tickets = [t for t in all_tickets if t not in closed_tickets]

                        if not open_tickets:
                            continue

                        # Close all open tickets
                        for ticket in open_tickets:
                            if close_trade(ticket, signal_id):
                                mark_ticket_closed(signal_id, ticket, ch_name)
                            else:
                                logger.error(f"[TP Monitor] Failed to close ticket {ticket}")

                        logger.info(f"[TP Monitor] {ch_name} {signal_id}: Full close complete ({len(open_tickets)} tickets closed)")

        except Exception as e:
            logger.error(f"[TP Monitor] Unexpected error: {e}", exc_info=True)


async def main():
    """
    Main async orchestrator.

    1. Connect to MT5 (abort if fails)
    2. Load existing trades state for all channels
    3. Start multi-channel Telegram listener (blocking)
    4. Handle shutdown gracefully
    """
    logger.info("[MAIN] 🚀 Starting GaryBot Multi-Channel...")

    # Check config placeholders
    if isinstance(config.TELEGRAM_API_ID, str) and "YOUR_" in config.TELEGRAM_API_ID:
        logger.warning("[MAIN] ⚠️ Config placeholders detected! Fill in config.py with your credentials.")
        return 1

    # Connect to MT5
    if not connect_mt5():
        logger.critical("[MAIN] ❌ Cannot start: MT5 connection failed")
        return 1

    # Load existing trades state for all channels (just for logging)
    from trade_manager import get_all_channels_trades
    all_trades = get_all_channels_trades()
    total_open = 0
    for ch_name, trades in all_trades.items():
        open_count = len([t for t in trades if len(t.get("closed_tickets", [])) < len(t.get("tickets", []))])
        total_open += open_count
        logger.info(f"[MAIN] Channel '{ch_name}': {len(trades)} groups ({open_count} open)")
    logger.info(f"[MAIN] Total open groups across all channels: {total_open}")

    # Start TP monitor if enabled (use getattr for backward compatibility)
    if getattr(config, 'AUTO_TP_MANAGEMENT', False):
        asyncio.create_task(tp_monitor())
        logger.info("[MAIN] TP Monitor task started")

    # Set up signal handler for graceful shutdown
    stop_event = asyncio.Event()

    def signal_handler(signum, frame):
        logger.info("[MAIN] Shutdown signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start Telegram listener
    # Note: telegram_listener.py now handles PersistentTimestampOutdatedError
    # reconnection internally with exponential backoff and session cleanup.
    # This outer loop is a safety net for truly unexpected failures only.
    max_outer_retries = 3
    outer_retry_delay = 30  # seconds
    listener_task = None

    try:
        for attempt in range(max_outer_retries):
            logger.info(f"[MAIN] Starting multi-channel listener (attempt {attempt + 1}/{max_outer_retries})")
            listener_task = asyncio.create_task(start_multi_listener(handle_message))

            # Wait for stop event or listener task completion
            stop_wait_task = asyncio.create_task(stop_event.wait())
            done, pending = await asyncio.wait(
                [listener_task, stop_wait_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # If stop event was set, exit the loop
            if stop_event.is_set():
                logger.info("[MAIN] Shutdown signal received")
                break

            # Check if listener task completed with an error
            if listener_task in done:
                try:
                    await listener_task
                    logger.info("[MAIN] Listener exited normally")
                    break
                except PersistentTimestampOutdatedError as e:
                    # This should rarely reach here since telegram_listener handles it internally
                    logger.warning(f"[MAIN] Persistent timestamp error escaped to main: {e}")
                    if attempt < max_outer_retries - 1:
                        logger.info(f"[MAIN] Outer retry in {outer_retry_delay}s...")
                        await asyncio.sleep(outer_retry_delay)
                        continue
                    else:
                        logger.error("[MAIN] Max outer retry attempts reached")
                        raise
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"[MAIN] Listener failed with unexpected error: {e}")
                    if attempt < max_outer_retries - 1:
                        logger.info(f"[MAIN] Outer retry in {outer_retry_delay}s...")
                        await asyncio.sleep(outer_retry_delay)
                        continue
                    raise

            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    except KeyboardInterrupt:
        logger.info("[MAIN] KeyboardInterrupt received")
    except Exception as e:
        logger.error(f"[MAIN] Fatal error: {e}")
    finally:
        # Cleanup
        if listener_task and not listener_task.done():
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
        disconnect_mt5()
        logger.info("[MAIN] GaryBot shutdown complete")

    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("[MAIN] Interrupted")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"[MAIN] Fatal startup error: {e}")
        sys.exit(1)
