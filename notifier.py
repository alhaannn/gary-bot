import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_CHAT_ID, SUPABASE_URL, SUPABASE_KEY, DASHBOARD_URL

# Supabase REST API headers (no SDK needed)
# Using "on_conflict=signal_id" for upsert to avoid duplicate rows per signal
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal"
} if SUPABASE_URL and SUPABASE_KEY else {}


def send_telegram_alert(trade_data: dict, action_type: str = "signal"):
    """
    Sends an HTML formatted alert to Telegram.
    trade_data: pair, action, entry_price, sl, tp, pnl (if close), channel
    """
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    if action_type == "signal":
        text = (
            f"<b>🚨 NEW SIGNAL DETECTED 🚨</b>\n\n"
            f"🪙 <b>Pair:</b> {trade_data.get('pair')}\n"
            f"📈 <b>Action:</b> {trade_data.get('action')}\n"
            f"💵 <b>Entry Region:</b> {trade_data.get('entry_price')}\n"
            f"🛑 <b>Stop Loss:</b> {trade_data.get('sl')}\n"
            f"🎯 <b>Take Profit:</b> {trade_data.get('tp')}\n"
        )
    elif action_type == "entry":
        text = (
            f"<b>✅ TRADE ENTERED ✅</b>\n\n"
            f"🪙 <b>Pair:</b> {trade_data.get('pair')}\n"
            f"📈 <b>Action:</b> {trade_data.get('action')}\n"
            f"💵 <b>Filled Price:</b> {trade_data.get('entry_price')}\n"
        )
    elif action_type == "close":
        pnl = trade_data.get('pnl', 0)
        icon = "💹" if pnl > 0 else "🩸"
        text = (
            f"<b>{icon} POSITION CLOSED {icon}</b>\n\n"
            f"🪙 <b>Pair:</b> {trade_data.get('pair')}\n"
            f"📈 <b>Type:</b> {trade_data.get('action')}\n"
            f"💵 <b>Entry:</b> {trade_data.get('entry_price', 'N/A')}\n"
            f"🎯 <b>TP:</b> {trade_data.get('tp', 'N/A')}\n"
            f"💸 <b>PnL:</b> ${pnl}\n"
        )
    else:
        text = f"<b>ℹ️ update:</b> {str(trade_data)}"

    # Add inline keyboard button to open Mini App
    reply_markup = None
    if DASHBOARD_URL and DASHBOARD_URL != "http://localhost:3000":
        reply_markup = {
            "inline_keyboard": [
                [{"text": "📊 Open Dashboard", "web_app": {"url": DASHBOARD_URL}}]
            ]
        }

    payload = {
        "chat_id": TELEGRAM_BOT_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")


def push_trade_to_db(trade_data: dict, status: str):
    """
    Pushes or updates trade history in Supabase via REST API.

    Uses 'signal_id' (TEXT) as the unique conflict key for upsert,
    so updating a trade (OPEN → CLOSED_PARTIAL → CLOSED) only modifies
    the existing row instead of creating duplicates.

    The 'id' column in Supabase is UUID auto-generated — we never send it.
    """
    if not SUPABASE_HEADERS:
        return

    try:
        entry = float(trade_data.get("entry_price")) if trade_data.get("entry_price") else None
        sl = float(trade_data.get("sl")) if trade_data.get("sl") else None
        tp = float(trade_data.get("tp")) if trade_data.get("tp") else None
        pnl = float(trade_data.get("pnl", 0))

        row = {
            "pair": trade_data.get("pair"),
            "action": trade_data.get("action"),
            "entry_price": entry,
            "sl": sl,
            "tp": tp,
            "status": status,
            "pnl": pnl,
            "channel": trade_data.get("channel", "Unknown"),
        }

        # Use signal_id (our timestamp-based ID) as the upsert key
        # This allows OPEN → CLOSED status transitions to UPDATE the same row
        if trade_data.get("id"):
            row["signal_id"] = str(trade_data["id"])

        # POST with on_conflict=signal_id → upsert on the signal_id unique index
        api_url = f"{SUPABASE_URL}/rest/v1/trades?on_conflict=signal_id"
        response = requests.post(api_url, json=row, headers=SUPABASE_HEADERS, timeout=5)
        response.raise_for_status()

    except requests.exceptions.HTTPError as e:
        print(f"Failed to push trade to DB: {e} — response: {e.response.text[:300] if e.response else 'N/A'}")
    except Exception as e:
        print(f"Failed to push trade to DB: {e}")
