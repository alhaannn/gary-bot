"""
Trade Manager - Persistent state management for trade groups

Manages trades.json file containing all trade group status.
Provides functions to query, update, and save trade state.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from logger import get_logger
from config import TRADES_FILE

logger = get_logger()


def load_trades() -> List[Dict[str, Any]]:
    """
    Load trades from trades.json file.
    Returns empty list if file doesn't exist or is invalid.
    """
    try:
        trades_file = Path(TRADES_FILE)
        if not trades_file.exists():
            logger.debug("trades.json not found, starting with empty state")
            return []

        with open(trades_file, "r", encoding="utf-8") as f:
            trades = json.load(f)
            if not isinstance(trades, list):
                logger.warning("trades.json invalid format, resetting")
                return []
            logger.debug(f"Loaded {len(trades)} trade groups from trades.json")
            return trades
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse trades.json: {e}")
        return []
    except Exception as e:
        logger.error(f"Failed to load trades: {e}")
        return []


def save_trades(trades: List[Dict[str, Any]]) -> bool:
    """
    Atomically save trades to trades.json.
    Returns True on success, False on failure.
    """
    try:
        temp_file = Path(TRADES_FILE + ".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2)
        temp_file.replace(TRADES_FILE)
        logger.debug(f"Saved {len(trades)} trade groups to trades.json")
        return True
    except Exception as e:
        logger.error(f"Failed to save trades: {e}")
        return False


def add_trade_group(
    signal_id: str,
    direction: str,
    entry_price: float,
    sl: float,
    tp1: Optional[float],
    tp2: Optional[float],
    ticket1: int,
    ticket2: int
) -> bool:
    """
    Add a new trade group to the state.
    Returns True if successfully added and saved.
    """
    trades = load_trades()

    trade_group = {
        "signal_id": signal_id,
        "direction": direction.upper(),
        "entry_price": round(entry_price, 2),
        "sl": round(sl, 2),
        "tp1": round(tp1, 2) if tp1 is not None else None,
        "tp2": round(tp2, 2) if tp2 is not None else None,
        "ticket1": ticket1,
        "ticket2": ticket2,
        "t1_closed": False,
        "t2_closed": False,
        "created_at": datetime.now().isoformat()
    }

    trades.append(trade_group)

    if save_trades(trades):
        logger.info(f"[TRADE MANAGER] ✅ Added trade group {signal_id}: {direction} tickets {ticket1},{ticket2}")
        return True
    return False


def get_open_groups() -> List[Dict[str, Any]]:
    """
    Get all trade groups where T2 is not fully closed.
    Returns list of trade groups.
    """
    trades = load_trades()
    open_groups = [t for t in trades if not t.get("t2_closed", False)]
    logger.debug(f"Found {len(open_groups)} open trade groups (t2_closed=false)")
    return open_groups


def get_partial_eligible_groups() -> List[Dict[str, Any]]:
    """
    Get trade groups eligible for partial close:
    Both T1 and T2 are still open (t1_closed=false, t2_closed=false).
    """
    trades = load_trades()
    eligible = [
        t for t in trades
        if not t.get("t1_closed", False) and not t.get("t2_closed", False)
    ]
    logger.debug(f"Found {len(eligible)} partial-eligible trade groups")
    return eligible


def get_group_by_signal_id(signal_id: str) -> Optional[Dict[str, Any]]:
    """Find a trade group by its signal_id."""
    trades = load_trades()
    for trade in trades:
        if trade.get("signal_id") == signal_id:
            return trade
    return None


def get_group_by_ticket(ticket: int) -> Optional[Dict[str, Any]]:
    """Find a trade group containing the given ticket."""
    trades = load_trades()
    for trade in trades:
        if trade.get("ticket1") == ticket or trade.get("ticket2") == ticket:
            return trade
    return None


def mark_t1_closed(signal_id: str) -> bool:
    """Mark T1 as closed for the given signal_id."""
    trades = load_trades()
    for trade in trades:
        if trade.get("signal_id") == signal_id:
            trade["t1_closed"] = True
            trade["t1_closed_at"] = datetime.now().isoformat()
            if save_trades(trades):
                logger.info(f"[TRADE MANAGER] ✅ Marked T1 closed for {signal_id}")
                return True
    logger.warning(f"[TRADE MANAGER] ⚠️ Trade group {signal_id} not found for mark_t1_closed")
    return False


def mark_t2_closed(signal_id: str) -> bool:
    """Mark T2 as closed for the given signal_id."""
    trades = load_trades()
    for trade in trades:
        if trade.get("signal_id") == signal_id:
            trade["t2_closed"] = True
            trade["t2_closed_at"] = datetime.now().isoformat()
            if save_trades(trades):
                logger.info(f"[TRADE MANAGER] ✅ Marked T2 closed for {signal_id}")
                return True
    logger.warning(f"[TRADE MANAGER] ⚠️ Trade group {signal_id} not found for mark_t2_closed")
    return False


def mark_both_closed(signal_id: str) -> bool:
    """Mark both T1 and T2 as closed for the given signal_id."""
    trades = load_trades()
    for trade in trades:
        if trade.get("signal_id") == signal_id:
            trade["t1_closed"] = True
            trade["t2_closed"] = True
            trade["t1_closed_at"] = datetime.now().isoformat()
            trade["t2_closed_at"] = datetime.now().isoformat()
            if save_trades(trades):
                logger.info(f"[TRADE MANAGER] ✅ Marked both closed for {signal_id}")
                return True
    logger.warning(f"[TRADE MANAGER] ⚠️ Trade group {signal_id} not found for mark_both_closed")
    return False


def get_tickets_for_group(signal_id: str) -> tuple:
    """
    Get (ticket1, ticket2) for a trade group.
    Returns (None, None) if not found.
    """
    group = get_group_by_signal_id(signal_id)
    if group:
        return group.get("ticket1"), group.get("ticket2")
    return None, None


def remove_closed_groups(max_age_days: int = 7) -> int:
    """
    Remove fully closed trade groups older than max_age_days.
    Returns number of groups removed.
    """
    import time
    cutoff = time.time() - (max_age_days * 86400)

    trades = load_trades()
    to_remove = []

    for trade in trades:
        if trade.get("t2_closed", False):
            closed_at = trade.get("t2_closed_at")
            if closed_at:
                try:
                    closed_time = datetime.fromisoformat(closed_at).timestamp()
                    if closed_time < cutoff:
                        to_remove.append(trade)
                except:
                    pass

    if to_remove:
        trades = [t for t in trades if t not in to_remove]
        if save_trades(trades):
            logger.info(f"[TRADE MANAGER] 🗑️ Removed {len(to_remove)} old closed trade groups")
            return len(to_remove)

    return 0
