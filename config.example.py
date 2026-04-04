"""
Configuration template for GaryBot - Gold Trading Bot

Copy this file to config.py and fill in your actual credentials.
DO NOT commit config.py to git - it contains sensitive credentials.

=== GET STARTED ===
1. Fill in all credential fields below
2. For multi-channel setup, update the CHANNELS list
3. Run `python fetch_history.py` to generate channel prompts
4. Start the bot: `python main.py`

=== MULTI-CHANNEL MODE ===
Set USE_LEGACY_SINGLE_CHANNEL = False (default) to use multiple channels.
Define each channel in the CHANNELS list with its unique prompt file.
"""

# ========== Telegram Credentials ==========
# Get these from https://my.telegram.org/apps
TELEGRAM_API_ID = 1234567  # Your numeric API ID (int)
TELEGRAM_API_HASH = "your_api_hash_here"  # Your API Hash (str)
TELEGRAM_PHONE = "+1234567890"  # Your phone with country code

# ========== Multi-Channel Configuration ==========
# Set to True to use old single-channel mode (backward compatibility)
USE_LEGACY_SINGLE_CHANNEL = False

# List of channels to monitor with their settings
CHANNELS = [
    {
        "name": "gary",  # Internal identifier (lowercase, no spaces)
        "username": "Gary_TheTrader",  # Channel username (with or without @)
        "enabled": True,  # Set False to disable temporarily
        "trades_per_signal": 2,  # Number of trades to open per signal (2 or 4)
        "prompt_file": "prompts/gary.txt"  # Path to channel-specific prompt
    },
    {
        "name": "goldtradersunny",
        "username": "goldtradersunny",
        "enabled": True,
        "trades_per_signal": 4,
        "prompt_file": "prompts/goldtradersunny.txt"
    },
    {
        "name": "bengoldtrader",
        "username": "bengoldtrader",
        "enabled": True,
        "trades_per_signal": 2,
        "prompt_file": "prompts/bengoldtrader.txt"
    },
    {
        "name": "gtmofx",
        "username": "gtmofx",
        "enabled": True,
        "trades_per_signal": 2,
        "prompt_file": "prompts/gtmofx.txt"
    },
    {
        "name": "traderalhan",
        "username": "traderalhan",
        "enabled": True,
        "trades_per_signal": 2,
        "prompt_file": "prompts/traderalhan.txt"
    }
]

# Legacy single-channel mode (used only if USE_LEGACY_SINGLE_CHANNEL = True)
LEGACY_CHANNEL = "Gary_TheTrader"

# ========== Groq API ==========
# Get your API key from https://console.groq.com
GROQ_API_KEY = "gsk_your_key_here"
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_TIMEOUT = 10  # seconds

# ========== MetaTrader5 Credentials ==========
# Your MT5 account credentials
MT5_LOGIN = 1234567  # Account number
MT5_PASSWORD = "your_mt5_password"
MT5_SERVER = "your-broker-server.com"

# ========== Trading Parameters ==========
SYMBOL = "XAUUSD"  # Gold symbol (may be "XAUUSD" or "XAUUSDm")
LOT_SIZE = 0.01  # Lot size per trade
MAGIC_NUMBER = 20250101  # Unique identifier for bot trades
SLIPPAGE = 10  # Maximum slippage in points

# ========== Bot Behavior ==========
TRADE_DELAY = 0.2  # Delay between opening T1 and T2 (seconds)
ENTRY_PRICE_PRECISION = 2  # Decimal places for price rounding
PIP_MULTIPLIER = 0.1  # XAUUSD: 1 pip = 0.1

# ========== Timestamp Validation ==========
# Reject messages older/newer than this many seconds
TIMESTAMP_THRESHOLD = 5  # seconds

# ========== Historical Message Fetching ==========
# Used by fetch_history.py to analyze channel patterns
HISTORY_LIMIT = 2000  # Number of messages to fetch per channel
HISTORY_OUTPUT_DIR = "history"  # Where to save raw messages

# ========== Automatic TP Management ==========
# Enable to automatically monitor positions and trigger partial/full closes
# when TP1/TP2 levels are reached (no manual signals needed)
AUTO_TP_MANAGEMENT = False  # Set True to enable
TP_MONITOR_INTERVAL = 5  # Check interval in seconds

# ========== File Paths ==========
TRADES_FILE = "trades.json"  # Legacy single-channel state file (ignored in multi-channel)
LOG_FILE = "gary_bot.log"
SESSION_FILE = "gary_bot_session"
