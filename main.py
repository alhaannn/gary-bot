"""
GaryBot - Automated Gold Trading Bot

Main orchestrator that coordinates MT5, Telegram listener, and signal processing.

Usage:
    python main.py

Ensure MT5 terminal is running and you're logged in before starting.
First run will prompt for Telegram phone verification.
"""

import asyncio
import signal
import sys
from datetime import datetime

# Import config first (others depend on it)
import config

# Import logger and initialize ASAP
from logger import get_logger
logger = get_logger()

# Import other modules
from signal_parser import parse_signal
from trade_manager import (
    load_trades, add_trade_group,
    get_open_groups, get_partial_eligible_groups,
    mark_t1_closed, mark_t2_closed, mark_both_closed
)
from trade_executor import (
    connect_mt5, disconnect_mt5,
    open_two_trades, close_trade, move_sl_to_breakeven, modify_sl,
    calculate_entry_price, calculate_tp_from_pips
)
from telegram_listener import start_listener
from telethon.errors import PersistentTimestampOutdatedError


async def handle_trade_entry(parsed: dict, signal_id: str):
    """
    Handle ENTRY signal: open two trades and persist state.
    """
    logger.info(f"[MAIN] 🎯 Processing ENTRY signal {signal_id}")

    direction = parsed["direction"]
    entry_high = parsed["entry_high"]
    entry_low = parsed["entry_low"]
    sl = parsed["sl"]

    # Calculate entry price
    entry_price = calculate_entry_price(entry_high, entry_low)
    logger.info(f"[MAIN] Entry price (midpoint): {entry_price:.2f}")

    # Calculate TPs
    tp1 = None
    tp2 = None

    # Priority: explicit prices > pips
    if parsed.get("tp1") is not None:
        tp1 = parsed["tp1"]
        logger.info(f"[MAIN] TP1 from price: {tp1:.2f}")
    elif parsed.get("tp1_pips") is not None:
        tp1 = calculate_tp_from_pips(direction, entry_price, parsed["tp1_pips"])
        logger.info(f"[MAIN] TP1 from {parsed['tp1_pips']} pips: {tp1:.2f}")

    if parsed.get("tp2") is not None:
        tp2 = parsed["tp2"]
        logger.info(f"[MAIN] TP2 from price: {tp2:.2f}")
    elif parsed.get("tp2_pips") is not None:
        tp2 = calculate_tp_from_pips(direction, entry_price, parsed["tp2_pips"])
        logger.info(f"[MAIN] TP2 from {parsed['tp2_pips']} pips: {tp2:.2f}")

    # Open two trades
    ticket1, ticket2 = open_two_trades(direction, sl, tp1, tp2, signal_id)

    if ticket1 == -1 or ticket2 == -1:
        logger.error(f"[MAIN] ❌ Failed to open trades for signal {signal_id}")
        return

    # Persist to trades.json
    success = add_trade_group(
        signal_id=signal_id,
        direction=direction,
        entry_price=entry_price,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        ticket1=ticket1,
        ticket2=ticket2
    )

    if success:
        logger.info(f"[MAIN] ✅ ENTRY signal {signal_id} fully processed: {direction} @ {entry_price:.2f}, T1:{ticket1} T2:{ticket2}")
    else:
        logger.error(f"[MAIN] ❌ ENTRY signal {signal_id} trades opened but failed to save state")


async def handle_partial_signal(parsed: dict):
    """
    Handle PARTIAL signal: close T1, move T2 to breakeven.
    """
    logger.info("[MAIN] 🔄 Processing PARTIAL signal")

    eligible_groups = get_partial_eligible_groups()

    if not eligible_groups:
        logger.warning("[MAIN] ⚠️ No eligible groups for partial close")
        return

    logger.info(f"[MAIN] Processing {len(eligible_groups)} eligible group(s)")

    for group in eligible_groups:
        signal_id = group["signal_id"]
        ticket1 = group["ticket1"]
        ticket2 = group["ticket2"]
        entry_price = group["entry_price"]

        # Close T1
        if close_trade(ticket1, signal_id):
            mark_t1_closed(signal_id)
        else:
            logger.error(f"[MAIN] ❌ Failed to close T1 for {signal_id}")

        # Move T2 to breakeven
        if move_sl_to_breakeven(ticket2, entry_price, signal_id):
            # T2 still open, T1 closed → eligible status updated via mark_t1_closed
            pass
        else:
            logger.error(f"[MAIN] ❌ Failed to move T2 to breakeven for {signal_id}")


async def handle_close_signal(parsed: dict):
    """
    Handle CLOSE signal: close all remaining trades.
    """
    logger.info("[MAIN] 🔒 Processing CLOSE signal")

    open_groups = get_open_groups()

    if not open_groups:
        logger.warning("[MAIN] ⚠️ No open groups to close")
        return

    logger.info(f"[MAIN] Closing {len(open_groups)} open group(s)")

    for group in open_groups:
        signal_id = group["signal_id"]
        t1_closed = group.get("t1_closed", False)
        t2_closed = group.get("t2_closed", False)
        ticket1 = group.get("ticket1")
        ticket2 = group.get("ticket2")

        # Close T1 if still open
        if not t1_closed and ticket1 is not None:
            if close_trade(ticket1, signal_id):
                mark_t1_closed(signal_id)
            else:
                logger.error(f"[MAIN] ❌ Failed to close T1 for {signal_id}")

        # Close T2 if still open
        if not t2_closed and ticket2 is not None:
            if close_trade(ticket2, signal_id):
                mark_t2_closed(signal_id)
            else:
                logger.error(f"[MAIN] ❌ Failed to close T2 for {signal_id}")


async def handle_sl_hit_signal(parsed: dict):
    """
    Handle SL_HIT signal: MT5 auto-closed via stop loss.
    Mark all trades as closed in state.
    """
    logger.info("[MAIN] ⚠️ Processing SL_HIT signal (MT5 auto-close)")

    open_groups = get_open_groups()

    if not open_groups:
        logger.warning("[MAIN] ⚠️ No open groups to mark as SL-hit")
        return

    logger.info(f"[MAIN] Marking {len(open_groups)} group(s) as closed (SL hit)")

    for group in open_groups:
        signal_id = group["signal_id"]
        mark_both_closed(signal_id)


async def handle_sl_modify_signal(parsed: dict):
    """
    Handle SL_MODIFY signal: modify stop loss on open positions.
    """
    logger.info("[MAIN] 🔧 Processing SL_MODIFY signal")

    new_sl = parsed["new_sl"]
    open_groups = get_open_groups()

    if not open_groups:
        logger.warning("[MAIN] ⚠️ No open groups to modify SL")
        return

    logger.info(f"[MAIN] Modifying SL to {new_sl:.2f} for {len(open_groups)} open group(s)")

    success_count = 0
    for group in open_groups:
        signal_id = group["signal_id"]
        ticket1 = group.get("ticket1")
        ticket2 = group.get("ticket2")

        # Modify SL for T1 if still open
        if ticket1 is not None and not group.get("t1_closed", False):
            if modify_sl(ticket1, new_sl, signal_id):
                success_count += 1
            else:
                logger.error(f"[MAIN] ❌ Failed to modify SL for T1 {ticket1}")

        # Modify SL for T2 if still open
        if ticket2 is not None and not group.get("t2_closed", False):
            if modify_sl(ticket2, new_sl, signal_id):
                success_count += 1
            else:
                logger.error(f"[MAIN] ❌ Failed to modify SL for T2 {ticket2}")

    if success_count > 0:
        logger.info(f"[MAIN] ✅ SL_MODIFY: Modified {success_count} position(s) to {new_sl:.2f}")
    else:
        logger.warning("[MAIN] ⚠️ No positions were modified")


async def handle_ignore_signal(parsed: dict):
    """Handle IGNORE signal: do nothing."""
    logger.debug("[MAIN] ⏭️ IGNORE - Skipping")


async def handle_message(message_text: str):
    """
    Main message handler called from Telegram listener for each new message.

    Flow:
    1. Parse signal via Groq
    2. Route to appropriate handler based on type
    3. Log outcomes with ✅/❌ emojis
    4. Never raise exception (catch all to keep listener alive)
    """
    try:
        logger.info("=" * 80)
        logger.info(f"[MAIN] 📥 Received message: {message_text[:100]}{'...' if len(message_text) > 100 else ''}")

        # Parse signal
        parsed = parse_signal(message_text)

        signal_type = parsed.get("type", "UNKNOWN")
        logger.info(f"[MAIN] 🏷️  Signal type: {signal_type}")

        # Route to handler
        if signal_type == "ENTRY":
            signal_id = datetime.now().strftime("%Y%m%d%H%M%S")
            await handle_trade_entry(parsed, signal_id)

        elif signal_type == "PARTIAL":
            await handle_partial_signal(parsed)

        elif signal_type == "CLOSE":
            await handle_close_signal(parsed)

        elif signal_type == "SL_HIT":
            await handle_sl_hit_signal(parsed)

        elif signal_type == "SL_MODIFY":
            await handle_sl_modify_signal(parsed)

        elif signal_type == "IGNORE":
            await handle_ignore_signal(parsed)

        else:
            logger.warning(f"[MAIN] ❓ Unknown signal type: {signal_type}")

        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"[MAIN] ❌ Unhandled exception in handle_message: {e}")
        import traceback
        logger.debug(f"[MAIN] Traceback: {traceback.format_exc()}")


async def main():
    """
    Main async orchestrator.

    1. Connect to MT5 (abort if fails)
    2. Load existing trades state
    3. Start Telegram listener (blocking)
    4. Handle shutdown gracefully
    """
    logger.info("[MAIN] 🚀 Starting GaryBot...")

    # Check config placeholders
    if isinstance(config.TELEGRAM_API_ID, str) and "YOUR_" in config.TELEGRAM_API_ID:
        logger.warning("[MAIN] ⚠️ Config placeholders detected! Fill in config.py with your credentials.")

    # Connect to MT5
    if not connect_mt5():
        logger.critical("[MAIN] ❌ Cannot start: MT5 connection failed")
        return 1

    # Load existing trades state
    trades = load_trades()
    open_count = len([t for t in trades if not t.get("t2_closed", False)])
    logger.info(f"[MAIN] Loaded {len(trades)} trade groups ({open_count} open)")

    # Set up signal handler for graceful shutdown
    stop_event = asyncio.Event()

    def signal_handler(signum, frame):
        logger.info("[MAIN] Shutdown signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start Telegram listener with auto-reconnect on PersistentTimestampOutdatedError
    max_reconnect_attempts = 3
    reconnect_delay = 5  # seconds
    listener_task = None

    try:
        for attempt in range(max_reconnect_attempts):
            logger.info(f"[MAIN] Starting Telegram listener (attempt {attempt + 1}/{max_reconnect_attempts})")
            listener_task = asyncio.create_task(start_listener(handle_message))

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
                    # This will raise the exception if the task failed
                    await listener_task
                    # If we get here, the listener exited normally (unlikely)
                    logger.info("[MAIN] Listener exited normally")
                    break
                except PersistentTimestampOutdatedError as e:
                    logger.warning(f"[MAIN] Persistent timestamp error: {e}")
                    if attempt < max_reconnect_attempts - 1:
                        logger.info(f"[MAIN] Reconnecting in {reconnect_delay} seconds...")
                        await asyncio.sleep(reconnect_delay)
                        continue
                    else:
                        logger.error("[MAIN] Max reconnection attempts reached")
                        raise
                except asyncio.CancelledError:
                    # Listener was cancelled, exit quietly
                    break
                except Exception as e:
                    logger.error(f"[MAIN] Listener failed with unexpected error: {e}")
                    # For other errors, don't retry automatically
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
