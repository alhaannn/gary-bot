"""
Trade Manager - Persistent state management for trade groups

Manages trades per channel with isolated state files and dynamic ticket counts.
Provides functions to query, update, and save trade state.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
import math

from logger import get_logger
from config import TRADES_FILE, CHANNELS, USE_LEGACY_SINGLE_CHANNEL

logger = get_logger()


def _get_trades_file_for_channel(channel_name: str) -> str:
    """
    Get the trades file path for a specific channel.

    Args:
        channel_name: Channel identifier

    Returns:
        Path to the trades JSON file for that channel
    """
    if USE_LEGACY_SINGLE_CHANNEL:
        return TRADES_FILE
    return f"trades_{channel_name}.json"


def load_trades(channel_name: str = "gary") -> List[Dict[str, Any]]:
    """
    Load trades from trades file for a specific channel.
    Returns empty list if file doesn't exist or is invalid.

    Args:
        channel_name: Channel identifier

    Returns:
        List of trade groups
    """
    trades_file = _get_trades_file_for_channel(channel_name)

    try:
        trades_path = Path(trades_file)
        if not trades_path.exists():
            # If using multi-channel and legacy trades.json exists for 'gary', migrate it
            if channel_name == "gary" and not USE_LEGACY_SINGLE_CHANNEL:
                legacy_path = Path(TRADES_FILE)
                if legacy_path.exists():
                    logger.info(f"[TRADE] Migrating legacy file {TRADES_FILE} to {trades_file}")
                    try:
                        import shutil
                        shutil.copy2(legacy_path, trades_path)
                        logger.info(f"[TRADE] Migration copy successful")
                    except Exception as e:
                        logger.error(f"[TRADE] Failed to copy legacy file: {e}")
                        return []
                else:
                    logger.debug(f"[TRADE] trades file not found for {channel_name}: {trades_file}, starting with empty state")
                    return []
            else:
                logger.debug(f"[TRADE] trades file not found for {channel_name}: {trades_file}, starting with empty state")
                return []

        with open(trades_path, "r", encoding="utf-8") as f:
            trades = json.load(f)
            if not isinstance(trades, list):
                logger.warning(f"[TRADE] Invalid format in {trades_file}, resetting")
                return []

            # Migrate legacy format if needed
            migrated = False
            for trade in trades:
                if "ticket1" in trade and "tickets" not in trade:
                    # Legacy format detected: convert to new format
                    ticket1 = trade.get("ticket1")
                    ticket2 = trade.get("ticket2")
                    tickets = [ticket1, ticket2] if ticket1 and ticket2 else []
                    closed_tickets = []
                    if trade.get("t1_closed", False) and ticket1:
                        closed_tickets.append(ticket1)
                    if trade.get("t2_closed", False) and ticket2:
                        closed_tickets.append(ticket2)
                    # Partial applied if t1 was closed (partial logic was to close T1)
                    partial_applied = trade.get("t1_closed", False)

                    trade["tickets"] = tickets
                    trade["closed_tickets"] = closed_tickets
                    trade["partial_applied"] = partial_applied
                    migrated = True

            if migrated:
                logger.info(f"[TRADE] Migrated legacy trade format for {channel_name}")
                # Save the migrated format
                save_trades(trades, channel_name)

            logger.debug(f"[TRADE] Loaded {len(trades)} trade groups for {channel_name} from {trades_file}")
            return trades
    except json.JSONDecodeError as e:
        logger.error(f"[TRADE] Failed to parse {trades_file}: {e}")
        return []
    except Exception as e:
        logger.error(f"[TRADE] Failed to load trades for {channel_name}: {e}")
        return []


def save_trades(trades: List[Dict[str, Any]], channel_name: str = "gary") -> bool:
    """
    Atomically save trades to channel-specific trades file.
    Returns True on success, False on failure.

    Args:
        trades: List of trade groups to save
        channel_name: Channel identifier

    Returns:
        True if saved successfully, False otherwise
    """
    trades_file = _get_trades_file_for_channel(channel_name)

    try:
        temp_file = Path(trades_file + ".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2)
        temp_file.replace(trades_file)
        logger.debug(f"[TRADE] Saved {len(trades)} trade groups for {channel_name} to {trades_file}")
        return True
    except Exception as e:
        logger.error(f"[TRADE] Failed to save trades for {channel_name}: {e}")
        return False


def add_trade_group(
    signal_id: str,
    direction: str,
    entry_price: float,
    sl: float,
    tickets: List[int],
    channel_name: str = "gary",
    tp1: Optional[float] = None,
    tp2: Optional[float] = None
) -> bool:
    """
    Add a new trade group to the state for a specific channel.
    Returns True if successfully added and saved.

    Args:
        signal_id: Unique signal identifier
        direction: "BUY" or "SELL"
        entry_price: Entry price
        sl: Stop loss price
        tickets: List of ticket numbers opened for this signal
        channel_name: Channel identifier
        tp1: First take profit level (optional, for auto TP management)
        tp2: Second take profit level (optional, for auto TP management)

    Returns:
        True if successful, False otherwise
    """
    trades = load_trades(channel_name)

    trade_group = {
        "signal_id": signal_id,
        "direction": direction.upper(),
        "entry_price": round(entry_price, 2),
        "sl": round(sl, 2),
        "tickets": tickets,  # List of all ticket numbers
        "closed_tickets": [],  # Subset of tickets that have been closed
        "partial_applied": False,  # Whether partial close logic has been applied
        "channel": channel_name,
        "created_at": datetime.now().isoformat(),
        "tp1": round(tp1, 2) if tp1 is not None else None,
        "tp2": round(tp2, 2) if tp2 is not None else None
    }

    trades.append(trade_group)

    if save_trades(trades, channel_name):
        logger.info(f"[TRADE] ✅ Added trade group {signal_id} for {channel_name}: {direction} tickets {tickets} TP1={tp1} TP2={tp2}")
        return True
    return False


def get_open_groups(channel_name: str = "gary") -> List[Dict[str, Any]]:
    """
    Get all trade groups that have at least one ticket still open.
    A group is open if not all tickets are closed.

    Args:
        channel_name: Channel identifier

    Returns:
        List of open trade groups
    """
    trades = load_trades(channel_name)
    open_groups = [t for t in trades if len(t.get("closed_tickets", [])) < len(t.get("tickets", []))]
    logger.debug(f"[TRADE] Found {len(open_groups)} open trade groups for {channel_name}")
    return open_groups


def get_partial_eligible_groups(channel_name: str = "gary") -> List[Dict[str, Any]]:
    """
    Get trade groups eligible for partial close.
    Eligible if partial has NOT been applied yet and there is at least one open ticket.

    Args:
        channel_name: Channel identifier

    Returns:
        List of eligible trade groups
    """
    trades = load_trades(channel_name)
    eligible = [
        t for t in trades
        if not t.get("partial_applied", False) and
           len(t.get("closed_tickets", [])) < len(t.get("tickets", []))
    ]
    logger.debug(f"[TRADE] Found {len(eligible)} partial-eligible trade groups for {channel_name}")
    return eligible


def get_group_by_signal_id(signal_id: str, channel_name: str = "gary") -> Optional[Dict[str, Any]]:
    """
    Find a trade group by its signal_id for a specific channel.

    Args:
        signal_id: Signal identifier to search
        channel_name: Channel identifier

    Returns:
        Trade group dict or None if not found
    """
    trades = load_trades(channel_name)
    for trade in trades:
        if trade.get("signal_id") == signal_id:
            return trade
    return None


def get_tickets_for_group(group: Dict[str, Any]) -> List[int]:
    """
    Get list of all ticket numbers for a trade group.

    Args:
        group: Trade group dictionary

    Returns:
        List of ticket numbers
    """
    return group.get("tickets", [])


def mark_ticket_closed(signal_id: str, ticket: int, channel_name: str = "gary") -> bool:
    """
    Mark a specific ticket as closed for the given signal_id.

    Args:
        signal_id: Signal identifier
        ticket: Ticket number to mark as closed
        channel_name: Channel identifier

    Returns:
        True if successful, False otherwise
    """
    trades = load_trades(channel_name)
    for trade in trades:
        if trade.get("signal_id") == signal_id:
            closed_tickets = trade.get("closed_tickets", [])
            if ticket not in closed_tickets:
                closed_tickets.append(ticket)
                trade["closed_tickets"] = closed_tickets
                # Check if all tickets are now closed
                tickets = trade.get("tickets", [])
                if len(closed_tickets) >= len(tickets):
                    trade["fully_closed_at"] = datetime.now().isoformat()
                if save_trades(trades, channel_name):
                    logger.info(f"[TRADE] ✅ Marked ticket {ticket} closed for {signal_id} in {channel_name}")
                    return True
            else:
                logger.debug(f"[TRADE] Ticket {ticket} already marked closed for {signal_id}")
                return True
    logger.warning(f"[TRADE] ⚠️ Trade group {signal_id} not found for mark_ticket_closed in {channel_name}")
    return False


def mark_partial_applied(signal_id: str, channel_name: str = "gary") -> bool:
    """
    Mark that partial logic has been applied to this trade group.

    Args:
        signal_id: Signal identifier
        channel_name: Channel identifier

    Returns:
        True if successful, False otherwise
    """
    trades = load_trades(channel_name)
    for trade in trades:
        if trade.get("signal_id") == signal_id:
            trade["partial_applied"] = True
            if save_trades(trades, channel_name):
                logger.info(f"[TRADE] ✅ Marked partial applied for {signal_id} in {channel_name}")
                return True
    logger.warning(f"[TRADE] ⚠️ Trade group {signal_id} not found for mark_partial_applied in {channel_name}")
    return False


def remove_closed_groups(channel_name: str = "gary", max_age_days: int = 7) -> int:
    """
    Remove fully closed trade groups older than max_age_days for a specific channel.

    Args:
        channel_name: Channel identifier
        max_age_days: Maximum age in days to keep closed trades

    Returns:
        Number of groups removed
    """
    import time
    cutoff = time.time() - (max_age_days * 86400)

    trades = load_trades(channel_name)
    to_remove = []

    for trade in trades:
        tickets = trade.get("tickets", [])
        closed_tickets = trade.get("closed_tickets", [])
        # Consider group closed if all tickets are closed
        if len(closed_tickets) >= len(tickets):
            closed_at = trade.get("fully_closed_at")
            if closed_at:
                try:
                    closed_time = datetime.fromisoformat(closed_at).timestamp()
                    if closed_time < cutoff:
                        to_remove.append(trade)
                except:
                    pass

    if to_remove:
        trades = [t for t in trades if t not in to_remove]
        if save_trades(trades, channel_name):
            logger.info(f"[TRADE] 🗑️ Removed {len(to_remove)} old closed trade groups for {channel_name}")
            return len(to_remove)

    return 0


def get_all_channels_trades() -> Dict[str, List[Dict[str, Any]]]:
    """
    Get all trades from all enabled channels.
    Useful for consolidated reporting.

    Returns:
        Dict mapping channel_name -> list of trades
    """
    all_trades = {}
    for channel in CHANNELS:
        if channel["enabled"]:
            all_trades[channel["name"]] = load_trades(channel["name"])
    return all_trades


# ========== Martingale State Management ==========

def _get_martingale_file(channel_name: str) -> str:
    """Get the martingale state file path for a channel."""
    return f"martingale_{channel_name}.json"


def load_martingale_state(channel_name: str) -> Dict[str, Any]:
    """
    Load martingale state for a channel.

    Returns:
        Dict with 'active' (bool), 'triggered_by' (str), 'triggered_at' (str)
    """
    filepath = _get_martingale_file(channel_name)
    try:
        path = Path(filepath)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
                return state
    except Exception as e:
        logger.error(f"[MARTINGALE] Error loading state for {channel_name}: {e}")
    return {"active": False}


def set_martingale_active(channel_name: str, signal_id: str) -> bool:
    """
    Activate martingale for a channel (next trade will be doubled).

    Args:
        channel_name: Channel identifier
        signal_id: The signal that triggered SL (for logging)

    Returns:
        True if saved successfully
    """
    filepath = _get_martingale_file(channel_name)
    state = {
        "active": True,
        "triggered_by": signal_id,
        "triggered_at": datetime.now().isoformat()
    }
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        logger.info(f"[MARTINGALE] Activated for {channel_name} (triggered by {signal_id})")
        return True
    except Exception as e:
        logger.error(f"[MARTINGALE] Failed to save state for {channel_name}: {e}")
        return False


def reset_martingale(channel_name: str) -> bool:
    """
    Reset martingale for a channel (back to normal lot).

    Returns:
        True if saved successfully
    """
    filepath = _get_martingale_file(channel_name)
    state = {"active": False}
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        logger.info(f"[MARTINGALE] Reset for {channel_name} (back to base lot)")
        return True
    except Exception as e:
        logger.error(f"[MARTINGALE] Failed to reset state for {channel_name}: {e}")
        return False
