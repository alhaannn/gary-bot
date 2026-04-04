# GaryBot - Multi-Channel Automated Gold Trading Bot

A fully automated trading bot that monitors multiple Telegram channels for gold trading signals and executes trades automatically on MetaTrader5.

**Features:**
- 📺 **Multi-channel support** - Monitor multiple signal providers simultaneously
- 🤖 **AI-powered classification** - Groq Llama 3.3 70B understands each channel's unique style
- 🔄 **Auto-adaptive prompts** - Fetch and analyze channel history to generate perfect prompts
- 🧪 **Universal testing channel** - Test new configurations with `@traderalhan`
- 💾 **Per-channel state** - Isolated trade tracking per channel
- ⚙️ **Flexible trade counts** - Supports 2 or 4 trades per signal based on channel config

## Features

### Core Functionality
- **Real-time Telegram monitoring** using Telethon across multiple channels
- **AI-powered signal classification** via Groq API (Llama 3.3 70B)
- **Channel-specific prompts** - Each trader's unique signal style is learned and adapted to
- **Automatic trade execution** on MetaTrader5
- **Flexible trade strategy** - Supports 2 or 4 trades per signal (configurable per channel)
- **Persistent state** - Survives bot restarts via per-channel `trades_{channel}.json` files
- **Partial close management** - Close T1, move T2 to breakeven
- **Full position management** - Complete close on signal
- **Stop-loss handling** - Automatic tracking of SL hits and SL modifications
- **Position stacking** - Opens new trades regardless of existing positions
- **Robust error handling** - Never crashes on message parsing errors
- **Comprehensive logging** - Console + file with emoji indicators and per-channel context

### Advanced Features
- **Auto-reconnect** - Handles Telegram timestamp desync issues automatically
- **Message validation** - Rejects stale/future messages to prevent duplicate execution
- **Multi-channel orchestration** - Isolated processing per channel with unified trade logic
- **Dynamic prompt generation** - Analyze channel history to create optimal prompts (via `fetch_history.py`)
- **Universal testing channel** - `@traderalhan` combines patterns from all channels for testing

## Project Structure

```
gary-bot/
├── config.py              # Your credentials (DO NOT COMMIT)
├── config.example.py      # Template for config.py
├── logger.py              # Logging configuration
├── signal_parser.py       # Groq API signal classification (multi-channel)
├── trade_manager.py       # Persistent trade state management (per-channel)
├── trade_executor.py      # MetaTrader5 integration
├── telegram_listener.py   # Telegram async multi-channel listener
├── main.py                # Main orchestrator
├── fetch_history.py       # Analyzer: fetch messages + generate prompts
├── run_analyzer.py        # Standalone analyzer (legacy/alternative)
├── requirements.txt       # Python dependencies
├── .gitignore             # Git ignore rules
├── prompts/               # Channel-specific AI prompts (auto-generated)
│   ├── gary.txt
│   ├── goldtradersunny.txt
│   ├── bengoldtrader.txt
│   ├── gtmofx.txt
│   └── traderalhan.txt    # Universal testing channel prompt
├── history/               # Fetched historical messages (analysis output)
│   ├── gary_messages.json
│   ├── goldtradersunny_messages.json
│   └── ... (per channel)
├── trades_{channel}.json  # Created at runtime - trade state per channel
├── gary_bot_session.session # Telegram session (auto-created)
└── gary_bot.log           # Created at runtime - debug logs
```

## Prerequisites

1. **Python 3.8+** installed
2. **MetaTrader5 terminal** installed and running with a funded account
3. **Telegram account** with API credentials
4. **Groq API key** from https://console.groq.com

## Installation

### 1. Clone Repository

```bash
git clone <your-repo-url>
cd gary-bot
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**Note:** The `MetaTrader5` package requires MT5 terminal to be installed on the same machine.

### 3. Configure Credentials

1. Copy the example config:
   ```bash
   cp config.example.py config.py
   ```

2. Edit `config.py` with your actual credentials:

   ```python
   # Get these from https://my.telegram.org/apps
   TELEGRAM_API_ID = 1234567  # Your numeric API ID
   TELEGRAM_API_HASH = "your_api_hash_here"
   TELEGRAM_PHONE = "+1234567890"  # Your phone with country code

   # Get from https://console.groq.com
   GROQ_API_KEY = "gsk_your_key_here"

   # Your MT5 account credentials
   MT5_LOGIN = "your_account_number"
   MT5_PASSWORD = "your_mt5_password"
   MT5_SERVER = "your-broker-server.com"
   ```

   **Important:** Never commit `config.py` to git. It's already in `.gitignore`.

### 4. Configure Channels (Multi-Channel Setup)

GaryBot supports monitoring **multiple signal channels** simultaneously, each with isolated trade state and custom AI prompts.

#### Channel Configuration

Edit `config.py` to add/remove channels in the `CHANNELS` list:

```python
CHANNELS = [
    {
        "name": "gary",              # Internal identifier (lowercase, no spaces)
        "username": "Gary_TheTrader", # Telegram channel username (with or without @)
        "enabled": True,              # Set False to disable temporarily
        "trades_per_signal": 2,       # Number of trades per signal (2 or 4)
        "prompt_file": "prompts/gary.txt"  # Path to channel-specific prompt
    },
    {
        "name": "goldtradersunny",
        "username": "goldtradersunny",
        "enabled": True,
        "trades_per_signal": 4,       # This channel opens 4 trades
        "prompt_file": "prompts/goldtradersunny.txt"
    },
    # Add more channels as needed...
]
```

**Important:**

- Each channel must have unique `name` and corresponding prompt file
- The bot will create separate state files: `trades_{channel_name}.json`
- Channel-specific prompts live in `prompts/{name}.txt`

#### Universal Testing Channel

A special testing channel `traderalhan` is pre-configured. Its prompt (`prompts/traderalhan.txt`) combines signal patterns from **all** channels, making it ideal for testing new signal types or validating parser behavior. You can send test signals in any format and the bot should recognize them correctly.

**To use:** Join `@traderalhan` on Telegram and send test messages; the bot will process them using the universal classifier.

#### Legacy Single-Channel Mode

For backward compatibility, set `USE_LEGACY_SINGLE_CHANNEL = True` and define `LEGACY_CHANNEL`. This mode uses:
- Single state file `trades.json`
- Single prompt `prompts/gary.txt`
- No per-channel isolation

### 5. Generate/Update Channel Prompts Automatically

Each channel has a unique signal style (different formatting, keywords, emoji usage, etc.). Use **`fetch_history.py`** to automatically:

1. Fetch recent messages (default 2000) from each enabled channel
2. Analyze signal patterns, keywords, and structures
3. Generate/update the channel-specific prompt files in `prompts/`

```bash
python fetch_history.py
```

This will overwrite existing prompt files with updated versions based on the latest message history. Run this whenever you notice a channel's signal style has changed, or when adding a new channel.

**Configuration:**

- `HISTORY_LIMIT` (in `config.py`): Number of messages to fetch per channel (default 2000)
- `HISTORY_OUTPUT_DIR`: Where raw fetched messages are saved for reference (default `history/`)

**Note:** The script **skips** the `traderalhan` testing channel (since it's a composite, not a real trader).

#### Alternative: Standalone Analyzer

`run_analyzer.py` is the original analyzer with a different approach. It fetches 200 messages and generates prompts. Use `fetch_history.py` for the enhanced version with customizable limits.

### 6. Verify MT5 Installation

### 4. Verify MT5 Installation

Make sure MetaTrader5 Python package can connect:

```python
python -c "import MetaTrader5; print('MT5 package OK')"
```

And ensure MT5 terminal is running and you're logged in to your account.

## Usage

### Starting the Bot

```bash
python main.py
```

**First Run:**
- The bot will attempt to connect to MT5
- If connection fails, check that MT5 terminal is running and credentials are correct
- Telegram authentication will prompt for verification code (one-time)
- Session is saved to `gary_bot_session` for future runs

### What Happens

1. Bot connects to MT5 and logs account info
2. Connects to Telegram and monitors @Gary_TheTrader
3. Each new message is sent to Groq for classification
4. Based on signal type:
   - **ENTRY**: Opens 2 trades with calculated SL/TP
   - **PARTIAL**: Closes T1, moves T2 SL to breakeven
   - **CLOSE**: Closes all remaining positions
   - **SL_HIT**: Marks trades as closed (MT5 auto-closed)
   - **IGNORE**: No action taken

### Stopping the Bot

Press `Ctrl+C` for graceful shutdown:
- MT5 connection is closed properly
- Telegram session disconnected
- Trade state remains in `trades.json`

## Trade Logic

### Entry Signal

When an ENTRY signal is detected:
- **Entry Price**: Midpoint of entry zone `(high + low) / 2`
- **Trade 1 (T1)**: 0.01 lot with TP1
- **Trade 2 (T2)**: 0.01 lot with TP2 (200ms delay)
- Both trades share the same SL
- Trade comments identify T1/T2 with signal ID

Example signal:
```
Gold Buy Now @ 4481 - 4476  Sl: 4471  TP: 4486/4491
```
- Entry zone: 4476-4481 → entry: 4478.5
- SL: 4471
- T1 TP: 4486
- T2 TP: 4491

### Partial Close

On PARTIAL signal (e.g., "60Pips can close some now"):
- Closes **T1** fully
- Moves **T2** stop loss to breakeven (entry price)
- T2 continues running with no risk

### Full Close

On CLOSE signal (e.g., "Boom! Can take the profit 100PIPS"):
- Closes **T1** if still open
- Closes **T2** fully
- Marks both as closed in state

### SL Hit

On SL_HIT signal (e.g., "This setup hit SL. Wait for recovery"):
- MT5 already closed positions via stop-loss
- Bot marks them as closed in state for consistency

## State Management

### Multi-Channel State

In multi-channel mode (default), each channel has its own state file:

- `trades_gary.json`
- `trades_goldtradersunny.json`
- `trades_bengoldtrader.json`
- etc.

This keeps each channel's trades completely isolated, preventing cross-channel interference. The bot loads state for all channels on startup and maintains each independently.

**State file format** (per channel):

```json
[
  {
    "signal_id": "20250325064012",
    "direction": "BUY",
    "entry_price": 4478.5,
    "sl": 4471.0,
    "tp1": 4486.0,
    "tp2": 4491.0,
    "tickets": [123456, 123457],  // List of all trade tickets
    "closed_tickets": [123456],   // Which tickets are closed
    "partial_applied": false,     // Whether partial close was done
    "created_at": "2025-03-25T06:40:12.123456"
  }
]
```

### Legacy Single-Channel Mode

If `USE_LEGACY_SINGLE_CHANNEL = True`, the original single file `trades.json` is used (backward compatible).

### State Recovery

On startup, the bot automatically:
1. Loads trade state for all channels from their respective JSON files
2. Logs the number of open groups per channel
3. Continues managing those positions normally (partials, closes, etc.)

This ensures bot restarts or crashes never lose track of open trades.

## Logging

## Logging

Logs are written to both console and `gary_bot.log`:

- **Format**: `YYYY-MM-DD HH:MM:SS [LEVEL] message`
- **Console**: INFO level and above
- **File**: DEBUG level and above
- **Prefixes**:
  - `[TELEGRAM]` - Telegram events
  - `[PARSER]` - Groq classification
  - `[MT5]` - Trading operations
  - `[TRADE MANAGER]` - State persistence
  - `[MAIN]` - Orchestration
- **Emojis**: ✅ success, ❌ failure, ⚠️ warning

## Configuration Options

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SYMBOL` | "XAUUSD" | Gold symbol (check your broker: could be XAUUSD or XAUUSDm) |
| `LOT_SIZE` | 0.01 | Lots per trade |
| `MAGIC_NUMBER` | 20250101 | Bot identifier for trades (unique across bots) |
| `SLIPPAGE` | 10 | Max slippage in points |
| `TRADE_DELAY` | 0.2 | Delay between T1 and T2 opening (seconds) |
| `GROQ_MODEL` | "llama-3.3-70b-versatile" | LLM model for signal classification |
| `GROQ_TIMEOUT` | 10 | API timeout in seconds |
| `TIMESTAMP_THRESHOLD` | 5 | Reject messages older/newer than this many seconds |

### Multi-Channel Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_LEGACY_SINGLE_CHANNEL` | False | Set True to use old single-channel mode |
| `LEGACY_CHANNEL` | "Gary_TheTrader" | Channel username when legacy mode is True |
| `CHANNELS` | `[...]` | List of channel configurations (see above) |
| `HISTORY_LIMIT` | 2000 | Messages to fetch per channel when running `fetch_history.py` |
| `HISTORY_OUTPUT_DIR` | "history" | Directory for raw fetched messages |

### Automatic TP Management

The bot can automatically monitor open positions and trigger partial/full closes when price reaches predefined TP levels, without needing manual Telegram signals.

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTO_TP_MANAGEMENT` | False | Set True to enable automatic TP monitoring |
| `TP_MONITOR_INTERVAL` | 5 | Check interval in seconds (how often to scan positions) |

**How it works:**
- When a trade group is opened, the TP1 and TP2 levels are stored in the state.
- If `AUTO_TP_MANAGEMENT=True`, a background task periodically checks the current market price against TP1/TP2.
- **At TP1**: Closes half of the open trades in the group and moves the remaining half to breakeven.
- **At TP2**: Closes all remaining trades in the group.
- This works for any number of trades per signal (2, 4, etc.).
- The logic is identical to the manual `PARTIAL` and `CLOSE` signals, just triggered automatically.
- You can still send manual signals; they will work alongside auto monitoring (auto respects already-applied partials).

**Important:** You must have TP1 and TP2 defined in the signal (either as absolute prices or pips). The bot captures these when the ENTRY signal is processed.

## Analysis & Prompt Generation Tools

GaryBot includes powerful tools to automatically understand each channel's signal style and generate optimal prompts.

### `fetch_history.py` (Recommended)

The flagship tool that combines message fetching, pattern analysis, and prompt generation.

**What it does:**
1. Fetches up to `HISTORY_LIMIT` (default 2000) messages from each enabled channel (skips `traderalhan`)
2. Analyzes message patterns to identify:
   - Direction keywords (BUY/SELL indicators)
   - Entry formats (@ price ranges, etc.)
   - SL/TP formats (price vs pips, labeling styles)
   - Symbol mentions
   - Representative signal examples
3. Saves raw messages to `history/{channel}_messages.json` (for reference)
4. Generates/updates channel-specific prompts in `prompts/{channel}.txt` with:
   - Customized signal descriptions based on actual observed formats
   - Real examples from that channel (top 3 extracted)
   - Tailored parsing rules and keywords

**Usage:**
```bash
python fetch_history.py
```

**When to run:**
- After adding a new channel to `CHANNELS`
- When a channel changes its signal format/style
- Periodically to keep prompts up-to-date
- Before starting the bot for the first time with a new channel

**Customization:**
Edit `config.py` to adjust:
- `HISTORY_LIMIT`: Number of messages to analyze (more = better understanding but slower)
- `HISTORY_OUTPUT_DIR`: Where to save raw JSON messages

### `run_analyzer.py` (Legacy)

The original standalone analyzer. Similar functionality but with fixed 200-message limit and different output format. Kept for compatibility.

```bash
python run_analyzer.py
```

## Troubleshooting

### MT5 Connection Fails
- Ensure MT5 terminal is running
- Verify credentials in config.py
- Check MT5 server is accessible
- Ensure MetaTrader5 Python package installed

### Telegram Authentication Issues
- Delete `gary_bot_session.session` and re-authenticate
- Verify API_ID and API_HASH from https://my.telegram.org/apps
- Check phone number format includes country code (e.g., "+1234567890")

### Groq API Errors
- Verify API key is correct
- Check rate limits at https://console.groq.com
- Network/firewall blocking access

### Trades Not Opening
- Check MT5 terminal allows automated trading
- Verify symbol exists (XAUUSD vs XAUUSDm)
- Check account margin and balance
- Review logs for specific error messages

### Bot Crashes
All errors are caught and logged. Check:
- `gary_bot.log` for full traceback
- MT5 connection stability
- Memory usage (24/7 operation)

## Security Notes

1. **Never commit** `config.py` - it contains real credentials
2. Use environment variables in production if desired
3. The `.gitignore` config.py protects your secrets
4. `trades.json` contains MT5 ticket numbers - keep private
5. Telegram session file (`gary_bot_session.session`) grants access to your Telegram account - keep secure

## Production Deployment

Recommended for Windows Server EC2:

1. **Install Python 3.8+**
2. **Install MT5 terminal** and auto-login
3. **Clone repository** to persistent storage
4. **Configure** as above
5. **Run as service** (use NSSM or Windows Task Scheduler)
6. **Monitor logs** with a log rotation strategy
7. **Set up alerts** for critical errors (optional)

### Running as Windows Service (NSSM)

```bash
nssm install GaryBot "C:\Python39\python.exe" "C:\gary-bot\main.py"
nssm start GaryBot
```

## Disclaimer

This bot is for **educational purposes** only. Trading involves significant risk of loss. Past performance does not guarantee future results.

- Use at your own risk
- Start with small lot sizes for testing
- Understand the strategy before live trading
- Monitor the bot regularly
- Keep MT5 terminal running 24/7
- Ensure stable internet connection

## License

MIT License - feel free to modify and use as needed.

## Support

For issues, feature requests, or questions:
- Open an issue on GitHub
- Check logs in `gary_bot.log`
- Verify all prerequisites are met

---

**Happy Trading!** 🚀💰
