"""
MetaTrader5 Trade Executor

Handles all MT5 operations: connection, price queries, order placement,
position closing, and stop-loss modification. Supports variable trade counts.
"""

import time
import logging
from typing import Optional, List, Tuple
from datetime import datetime

import MetaTrader5 as mt5

from logger import get_logger
from config import (
    MT5_LOGIN, MT5_PASSWORD, MT5_SERVER,
    SYMBOL, LOT_SIZE, MAGIC_NUMBER, SLIPPAGE,
    ENTRY_PRICE_PRECISION, PIP_MULTIPLIER, ENTRY_ZONE_TOLERANCE
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

        logger.info(f"[MT5] [{signal_id}] Opening MARKET {direction} {LOT_SIZE} lot @ {price:.2f}, SL:{sl:.2f}, TP:{tp if tp else 'None'}")

        # Send order
        result = mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"[MT5] [{signal_id}] order_send failed: {result.comment} (code {result.retcode})")
            return -1

        ticket = result.order
        logger.info(f"[MT5] [{signal_id}] ✅ Market trade opened - Ticket: {ticket}")
        return ticket

    except Exception as e:
        logger.error(f"[MT5] [{signal_id}] Exception opening trade: {e}")
        return -1


def open_pending_order(
    direction: str,
    entry_price: float,
    sl: float,
    tp: Optional[float],
    comment: str,
    signal_id: str
) -> int:
    """
    Open a pending order (Buy Limit, Buy Stop, Sell Limit, Sell Stop).

    The order type is determined by comparing the desired entry price
    to the current market price:
      - BUY + market > entry  → Buy Limit  (price needs to come down)
      - BUY + market < entry  → Buy Stop   (price needs to go up)
      - SELL + market < entry → Sell Limit  (price needs to come up)
      - SELL + market > entry → Sell Stop   (price needs to go down)

    Args:
        direction: "BUY" or "SELL"
        entry_price: Desired entry price
        sl: Stop loss price
        tp: Take profit price (or None)
        comment: Trade comment (max 32 chars)
        signal_id: Signal ID for logging

    Returns:
        Order ticket (int) on success, -1 on failure
    """
    try:
        # Get current market price to decide pending type
        market_price = get_current_price(direction)
        if market_price is None:
            logger.error(f"[MT5] [{signal_id}] Cannot place pending order: no price available")
            return -1

        # Determine pending order type
        if direction.upper() == "BUY":
            if market_price > entry_price:
                order_type = mt5.ORDER_TYPE_BUY_LIMIT
                order_type_name = "BUY LIMIT"
            else:
                order_type = mt5.ORDER_TYPE_BUY_STOP
                order_type_name = "BUY STOP"
        else:  # SELL
            if market_price < entry_price:
                order_type = mt5.ORDER_TYPE_SELL_LIMIT
                order_type_name = "SELL LIMIT"
            else:
                order_type = mt5.ORDER_TYPE_SELL_STOP
                order_type_name = "SELL STOP"

        # Prepare pending order request
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": SYMBOL,
            "volume": LOT_SIZE,
            "type": order_type,
            "price": round(float(entry_price), ENTRY_PRICE_PRECISION),
            "sl": float(sl),
            "tp": float(tp) if tp is not None else 0.0,
            "deviation": SLIPPAGE,
            "magic": MAGIC_NUMBER,
            "comment": comment[:32],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        logger.info(
            f"[MT5] [{signal_id}] Placing PENDING {order_type_name} {LOT_SIZE} lot "
            f"@ {entry_price:.2f} (market: {market_price:.2f}), SL:{sl:.2f}, TP:{tp if tp else 'None'}"
        )

        # Send order
        result = mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"[MT5] [{signal_id}] Pending order failed: {result.comment} (code {result.retcode})")
            return -1

        ticket = result.order
        logger.info(f"[MT5] [{signal_id}] ✅ Pending {order_type_name} placed - Ticket: {ticket}")
        return ticket

    except Exception as e:
        logger.error(f"[MT5] [{signal_id}] Exception placing pending order: {e}")
        return -1


def open_multiple_trades(
    direction: str,
    sl: float,
    tps: List[Optional[float]],
    signal_id: str,
    channel_name: str,
    count: int = 2,
    entry_high: Optional[float] = None,
    entry_low: Optional[float] = None
) -> List[int]:
    """
    Open multiple trades (N) with smart order routing.

    If entry_high/entry_low are provided, checks current market price:
    - Market price WITHIN entry zone → Market order (instant fill)
    - Market price OUTSIDE entry zone → Pending order (limit/stop)

    If entry_high/entry_low are not provided, falls back to market order.

    Args:
        direction: "BUY" or "SELL"
        sl: Stop loss price
        tps: List of take profit prices (length may be less than count)
        signal_id: Unique signal identifier
        channel_name: Channel identifier (for comment prefix)
        count: Number of trades to open (2 or 4)
        entry_high: Upper bound of entry zone (optional)
        entry_low: Lower bound of entry zone (optional)

    Returns:
        List of ticket numbers (all successful) or empty list on failure
    """
    if count <= 0:
        logger.error(f"[MT5] [{signal_id}] Invalid trade count: {count}")
        return []

    # Determine order mode: market or pending
    use_pending = False
    pending_entry_price = None

    if entry_high is not None and entry_low is not None:
        market_price = get_current_price(direction)
        if market_price is not None:
            # Calculate distance from entry zone edges
            if market_price < entry_low:
                distance_from_zone = entry_low - market_price
                nearest_edge = entry_low
            elif market_price > entry_high:
                distance_from_zone = market_price - entry_high
                nearest_edge = entry_high
            else:
                distance_from_zone = 0  # Inside the zone
                nearest_edge = None

            if distance_from_zone <= ENTRY_ZONE_TOLERANCE:
                # Market price is within zone OR close enough — use market order
                logger.info(
                    f"[MT5] [{signal_id}] Market price {market_price:.2f} is "
                    f"{'WITHIN' if distance_from_zone == 0 else f'{distance_from_zone:.2f}pts from'} "
                    f"entry zone [{entry_low:.2f} - {entry_high:.2f}] → MARKET ORDER"
                )
                use_pending = False
            else:
                # Market is too far from zone — use pending order at nearest edge
                pending_entry_price = round(nearest_edge, ENTRY_PRICE_PRECISION)
                logger.info(
                    f"[MT5] [{signal_id}] Market price {market_price:.2f} is {distance_from_zone:.2f}pts from "
                    f"entry zone [{entry_low:.2f} - {entry_high:.2f}] (>{ENTRY_ZONE_TOLERANCE}pts) "
                    f"→ PENDING ORDER @ {pending_entry_price:.2f}"
                )
                use_pending = True
        else:
            logger.warning(f"[MT5] [{signal_id}] Cannot get market price, falling back to market order")

    order_mode = "PENDING" if use_pending else "MARKET"
    logger.info(f"[MT5] [{signal_id}] Opening {count} {order_mode} trades for {channel_name}: {direction} SL={sl:.2f}")

    tickets = []
    try:
        for i in range(count):
            # Determine TP for this trade
            if i < len(tps):
                tp = tps[i]
            elif len(tps) > 0:
                tp = tps[-1]  # Use last available TP
            else:
                tp = None

            # Generate comment with trade index
            comment = f"{channel_name[:8]}_T{i+1}_{signal_id}"[:32]

            if use_pending and pending_entry_price is not None:
                ticket = open_pending_order(
                    direction=direction,
                    entry_price=pending_entry_price,
                    sl=sl,
                    tp=tp,
                    comment=comment,
                    signal_id=signal_id
                )
            else:
                ticket = open_trade(
                    direction=direction,
                    sl=sl,
                    tp=tp,
                    comment=comment,
                    signal_id=signal_id
                )

            if ticket == -1:
                logger.error(f"[MT5] [{signal_id}] Failed to open trade {i+1}/{count}, rolling back...")
                # Close any already opened trades (market orders) or cancel pending
                for t in tickets:
                    try:
                        if use_pending:
                            cancel_pending_order(t, signal_id)
                        else:
                            close_trade(t, signal_id)
                    except:
                        pass
                return []

            tickets.append(ticket)

            # Delay between trades except after last one
            if i < count - 1:
                time.sleep(0.2)

        logger.info(f"[MT5] [{signal_id}] ✅ Successfully opened {len(tickets)} {order_mode} trades: {tickets}")
        return tickets

    except Exception as e:
        logger.error(f"[MT5] [{signal_id}] Exception during multiple trade opening: {e}")
        # Cleanup any opened trades
        for t in tickets:
            try:
                if use_pending:
                    cancel_pending_order(t, signal_id)
                else:
                    close_trade(t, signal_id)
            except:
                pass
        return []


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


def cancel_pending_order(ticket: int, signal_id: str = "") -> bool:
    """
    Cancel a pending order by ticket.

    Args:
        ticket: Order ticket to cancel
        signal_id: Optional signal ID for logging

    Returns:
        True on success, False on failure
    """
    try:
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
            "comment": f"Cancel_{signal_id}"[:32],
        }

        logger.info(f"[MT5] [{signal_id}] Cancelling pending order: {ticket}")
        result = mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"[MT5] [{signal_id}] Cancel failed: {result.comment} (code {result.retcode})")
            return False

        logger.info(f"[MT5] [{signal_id}] ✅ Pending order {ticket} cancelled")
        return True

    except Exception as e:
        logger.error(f"[MT5] [{signal_id}] Exception cancelling order: {e}")
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
