"""
Configuration template for GaryBot - Gold Trading Bot

Copy this file to config.py and fill in your actual credentials.
DO NOT commit config.py to git - it contains sensitive credentials.

=== CUSTOMIZATION ===
To use your own channel/trader:
1. Set TELEGRAM_CHANNEL to the channel username (e.g., "YourTraderName")
2. Update signal examples in signal_parser.py to match their format
3. Adjust trading parameters if needed (SYMBOL, LOT_SIZE, etc.)
"""

# ========== Telegram Credentials ==========
# Get these from https://my.telegram.org/apps
TELEGRAM_API_ID = "YOUR_API_ID"  # Replace with your API ID (int)
TELEGRAM_API_HASH = "YOUR_API_HASH"  # Replace with your API Hash (str)
TELEGRAM_PHONE = "YOUR_PHONE"  # Replace with your phone number (e.g., "+1234567890")
TELEGRAM_CHANNEL = "Gary_TheTrader"  # Channel username to monitor

# ========== Groq API ==========
# Get your API key from https://console.groq.com
GROQ_API_KEY = "YOUR_GROQ_API_KEY"
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_TIMEOUT = 10  # seconds

# ========== MetaTrader5 Credentials ==========
# Your MT5 account credentials
MT5_LOGIN = "YOUR_MT5_LOGIN"
MT5_PASSWORD = "YOUR_MT5_PASSWORD"
MT5_SERVER = "YOUR_MT5_SERVER"

# ========== Trading Parameters ==========
SYMBOL = "XAUUSD"  # Gold symbol (may be "XAUUSD" or "XAUUSDm" depending on broker)
LOT_SIZE = 0.01  # Lot size per trade
MAGIC_NUMBER = 20250101  # Unique identifier for bot trades
SLIPPAGE = 10  # Maximum slippage in points

# ========== Bot Behavior ==========
TRADE_DELAY = 0.2  # Delay between opening T1 and T2 (seconds)
ENTRY_PRICE_PRECISION = 2  # Decimal places for price rounding
PIP_MULTIPLIER = 0.1  # XAUUSD: 1 pip = 0.1

# ========== File Paths ==========
TRADES_FILE = "trades.json"
LOG_FILE = "gary_bot.log"
SESSION_FILE = "gary_bot_session"
