"""
MetaTrader5 Trade Executor

Handles all MT5 operations: connection, price queries, order placement,
position closing, and stop-loss modification.
"""

import time
import logging
from typing import Optional, Tuple
from datetime import datetime

import MetaTrader5 as mt5

from logger import get_logger
from config import (
    MT5_LOGIN, MT5_PASSWORD, MT5_SERVER,
    SYMBOL, LOT_SIZE, MAGIC_NUMBER, SLIPPAGE,
    ENTRY_PRICE_PRECISION, PIP_MULTIPLIER
)

logger = get_logger()


def connect_mt5() -> bool:
    """
    Initialize MT5 connection and login.
    Returns True on success, False on failure.
    """
    logger.info("[MT5] Connecting to MetaTrader5...")

    try:
        # Initialize MT5
        if not mt5.initialize():
            logger.error(f"[MT5] ❌ initialize() failed: {mt5.last_error()}")
            return False

        # Login
        login_ok = mt5.login(
            login=int(MT5_LOGIN),
            password=MT5_PASSWORD,
            server=MT5_SERVER
        )

        if not login_ok:
            logger.error(f"[MT5] ❌ login() failed: {mt5.last_error()}")
            mt5.shutdown()
            return False

        # Get account info
        account_info = mt5.account_info()
        if account_info:
            logger.info(f"[MT5] ✅ Connected - Account: {account_info.login}, Balance: {account_info.balance}")
        else:
            logger.warning("[MT5] ✅ Connected but could not fetch account info")

        return True

    except Exception as e:
        logger.error(f"[MT5] ❌ Connection exception: {e}")
        try:
            mt5.shutdown()
        except:
            pass
        return False


def disconnect_mt5():
    """Shutdown MT5 connection."""
    try:
        mt5.shutdown()
        logger.info("[MT5] Disconnected")
    except Exception as e:
        logger.error(f"[MT5] Error during disconnect: {e}")


def get_current_price(direction: str) -> Optional[float]:
    """
    Get current market price for symbol.
    For BUY: returns ASK price
    For SELL: returns BID price
    """
    try:
        symbol_info = mt5.symbol_info_tick(SYMBOL)
        if symbol_info is None:
            logger.error(f"[MT5] Symbol {SYMBOL} not found or no tick data")
            return None

        if direction.upper() == "BUY":
            price = symbol_info.ask
        else:
            price = symbol_info.bid

        logger.debug(f"[MT5] Current {'ASK' if direction.upper()=='BUY' else 'BID'} for {SYMBOL}: {price}")
        return price

    except Exception as e:
        logger.error(f"[MT5] Error getting price: {e}")
        return None


def open_trade(
    direction: str,
    sl: float,
    tp: Optional[float],
    comment: str,
    signal_id: str
) -> int:
    """
    Open a single market order.

    Args:
        direction: "BUY" or "SELL"
        sl: Stop loss price (float)
        tp: Take profit price (float or None)
        comment: Trade comment (max 32 chars, will be truncated)
        signal_id: Signal ID for logging

    Returns:
        Ticket number (int) on success, -1 on failure
    """
    try:
        # Determine order type
        order_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL

        # Get current price for volume normalization
        price = get_current_price(direction)
        if price is None:
            logger.error(f"[MT5] [{signal_id}] Cannot open trade: no price available")
            return -1

        # Prepare request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": LOT_SIZE,
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp) if tp is not None else 0.0,
            "deviation": SLIPPAGE,
            "magic": MAGIC_NUMBER,
            "comment": comment[:32],  # MT5 comment limit
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        logger.info(f"[MT5] [{signal_id}] Opening {direction} {LOT_SIZE} lot @ {price:.2f}, SL:{sl:.2f}, TP:{tp if tp else 'None'}")

        # Send order
        result = mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"[MT5] [{signal_id}] order_send failed: {result.comment} (code {result.retcode})")
            return -1

        ticket = result.order
        logger.info(f"[MT5] [{signal_id}] ✅ Trade opened successfully - Ticket: {ticket}")
        return ticket

    except Exception as e:
        logger.error(f"[MT5] [{signal_id}] Exception opening trade: {e}")
        return -1


def open_two_trades(
    direction: str,
    sl: float,
    tp1: Optional[float],
    tp2: Optional[float],
    signal_id: str
) -> Tuple[int, int]:
    """
    Open two trades (T1 and T2) with the same parameters but different TP.
    T1 opens first, then after 200ms delay T2 opens.

    Returns:
        (ticket1, ticket2) - both -1 if either fails
    """
    logger.info(f"[MT5] [{signal_id}] Opening two trades: {direction} SL={sl:.2f} TP1={tp1} TP2={tp2}")

    # Open T1
    ticket1 = open_trade(
        direction=direction,
        sl=sl,
        tp=tp1,
        comment=f"Gary_T1_{signal_id}",
        signal_id=signal_id
    )

    if ticket1 == -1:
        logger.error(f"[MT5] [{signal_id}] Failed to open T1, aborting T2")
        return -1, -1

    # Delay before T2
    time.sleep(0.2)

    # Open T2
    ticket2 = open_trade(
        direction=direction,
        sl=sl,
        tp=tp2,
        comment=f"Gary_T2_{signal_id}",
        signal_id=signal_id
    )

    if ticket2 == -1:
        logger.error(f"[MT5] [{signal_id}] T1 opened successfully but T2 failed")
        # T1 remains open, trade_group will still be added
        # User may want to manually close T1 or let it run

    return ticket1, ticket2


def close_trade(ticket: int, signal_id: str = "") -> bool:
    """
    Close an open position by ticket.

    Args:
        ticket: Position ticket to close
        signal_id: Optional signal ID for logging context

    Returns:
        True if closed or already not found, False on failure
    """
    try:
        # Find position
        position = mt5.positions_get(ticket=ticket)

        if position is None or len(position) == 0:
            logger.info(f"[MT5] [{signal_id}] Ticket {ticket} not found (possibly already closed)")
            return True  # Treat as success - already closed

        pos = position[0]

        # Determine close order type (opposite of current position)
        if pos.type == mt5.POSITION_TYPE_BUY:
            close_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(SYMBOL).bid
        else:
            close_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(SYMBOL).ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": SLIPPAGE,
            "magic": MAGIC_NUMBER,
            "comment": f"Gary_Close_{signal_id}"[:32],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        logger.info(f"[MT5] [{signal_id}] Closing ticket {ticket} ({pos.type}, vol={pos.volume})")
        result = mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"[MT5] [{signal_id}] Close failed: {result.comment} (code {result.retcode})")
            return False

        logger.info(f"[MT5] [{signal_id}] ✅ Ticket {ticket} closed successfully")
        return True

    except Exception as e:
        logger.error(f"[MT5] [{signal_id}] Exception closing ticket {ticket}: {e}")
        return False


def move_sl_to_breakeven(ticket: int, entry_price: float, signal_id: str = "") -> bool:
    """
    Move stop loss to breakeven (entry price).

    Args:
        ticket: Position ticket to modify
        entry_price: Breakeven price (original entry)
        signal_id: Optional signal ID for logging context

    Returns:
        True on success, False on failure
    """
    try:
        # Find position
        position = mt5.positions_get(ticket=ticket)

        if position is None or len(position) == 0:
            logger.warning(f"[MT5] [{signal_id}] Ticket {ticket} not found for SL modification")
            return False

        pos = position[0]

        # Keep existing TP, only change SL
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": SYMBOL,
            "sl": round(entry_price, ENTRY_PRICE_PRECISION),
            "tp": pos.tp,  # Keep existing TP
            "deviation": SLIPPAGE,
            "magic": MAGIC_NUMBER,
        }

        logger.info(f"[MT5] [{signal_id}] Moving SL to breakeven: {entry_price:.2f} (current TP: {pos.tp})")
        result = mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"[MT5] [{signal_id}] SL modification failed: {result.comment} (code {result.retcode})")
            return False

        logger.info(f"[MT5] [{signal_id}] ✅ SL moved to breakeven for ticket {ticket}")
        return True

    except Exception as e:
        logger.error(f"[MT5] [{signal_id}] Exception modifying SL: {e}")
        return False


def modify_sl(ticket: int, new_sl: float, signal_id: str = "") -> bool:
    """
    Modify stop loss of an open position.

    Args:
        ticket: Position ticket to modify
        new_sl: New stop loss price (float)
        signal_id: Optional signal ID for logging context

    Returns:
        True on success, False on failure
    """
    try:
        # Find position
        position = mt5.positions_get(ticket=ticket)

        if position is None or len(position) == 0:
            logger.warning(f"[MT5] [{signal_id}] Ticket {ticket} not found for SL modification")
            return False

        pos = position[0]

        # Keep existing TP, change SL
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": SYMBOL,
            "sl": round(new_sl, ENTRY_PRICE_PRECISION),
            "tp": pos.tp,  # Keep existing TP
            "deviation": SLIPPAGE,
            "magic": MAGIC_NUMBER,
        }

        logger.info(f"[MT5] [{signal_id}] Modifying SL for ticket {ticket}: {pos.sl:.2f} -> {new_sl:.2f} (TP: {pos.tp})")
        result = mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"[MT5] [{signal_id}] SL modification failed: {result.comment} (code {result.retcode})")
            return False

        logger.info(f"[MT5] [{signal_id}] ✅ SL modified successfully for ticket {ticket}")
        return True

    except Exception as e:
        logger.error(f"[MT5] [{signal_id}] Exception modifying SL: {e}")
        return False


def calculate_entry_price(entry_high: float, entry_low: float) -> float:
    """Calculate entry price as midpoint, rounded to 2 decimals."""
    price = (float(entry_high) + float(entry_low)) / 2
    return round(price, ENTRY_PRICE_PRECISION)


def calculate_tp_from_pips(direction: str, entry_price: float, pips: int) -> float:
    """
    Calculate take profit price based on pips.
    XAUUSD: 1 pip = 0.1

    BUY: TP = entry + (pips * 0.1)
    SELL: TP = entry - (pips * 0.1)
    """
    entry_price = float(entry_price)
    pips = int(pips)
    tp_offset = pips * PIP_MULTIPLIER

    if direction.upper() == "BUY":
        tp = entry_price + tp_offset
    else:
        tp = entry_price - tp_offset

    return round(tp, ENTRY_PRICE_PRECISION)
