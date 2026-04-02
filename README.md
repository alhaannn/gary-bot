# GaryBot - Automated Gold Trading Bot

A fully automated trading bot that monitors Telegram channel [@Gary_TheTrader](https://t.me/Gary_TheTrader) for gold trading signals and executes trades automatically on MetaTrader5.

## Features

- **Real-time Telegram monitoring** using Telethon
- **AI-powered signal classification** via Groq API (Llama 3.3 70B)
- **Automatic trade execution** on MetaTrader5
- **Dual-trade strategy** (T1 + T2 with separate take-profits)
- **Persistent state** - survives bot restarts via trades.json
- **Partial close management** - close T1, move T2 to breakeven
- **Full position management** - complete close on signal
- **Stop-loss handling** - automatic tracking of SL hits
- **Position stacking** - opens new trades regardless of existing positions
- **Robust error handling** - never crashes on single message errors
- **Comprehensive logging** - console + file with emoji indicators

## Project Structure

```
gary-bot/
├── config.py              # Your credentials (DO NOT COMMIT)
├── config.example.py      # Template for config.py
├── logger.py              # Logging configuration
├── signal_parser.py       # Groq API signal classification
├── trade_manager.py       # Persistent trade state management
├── trade_executor.py      # MetaTrader5 integration
├── telegram_listener.py   # Telegram async listener
├── main.py                # Main orchestrator
├── requirements.txt       # Python dependencies
├── .gitignore             # Git ignore rules
├── trades.json            # Created at runtime - trade state
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

### 4. Customize for Your Channel/Trader (Optional)

The bot is pre-configured for **@Gary_TheTrader** with specific signal formats. To use with a different Telegram channel:

1. **Change the channel name** in `config.py`:
   ```python
   TELEGRAM_CHANNEL = "YourTraderName"  # Without @
   ```

2. **Adapt the signal parser** in `signal_parser.py`:
   - Update the `SYSTEM_PROMPT` with your trader's exact signal formats
   - Add examples of ENTRY, PARTIAL, CLOSE, SL_MODIFY messages
   - The AI will learn to recognize their specific format

3. **Test the parser** by sending sample messages and checking the logs.

The default configuration works for Gary's signal style as documented in this README.

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

All open trades are persisted to `trades.json`:

```json
[
  {
    "signal_id": "20250325064012",
    "direction": "BUY",
    "entry_price": 4478.5,
    "sl": 4471.0,
    "tp1": 4486.0,
    "tp2": 4491.0,
    "ticket1": 123456,
    "ticket2": 123457,
    "t1_closed": false,
    "t2_closed": false,
    "created_at": "2025-03-25T06:40:12.123456"
  }
]
```

This allows the bot to recover from restarts without losing track of positions.

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

| Variable | Default | Description |
|----------|---------|-------------|
| `SYMBOL` | "XAUUSD" | Gold symbol (check your broker) |
| `LOT_SIZE` | 0.01 | Lots per trade |
| `MAGIC_NUMBER` | 20250101 | Bot identifier for trades |
| `SLIPPAGE` | 10 | Max slippage in points |
| `TRADE_DELAY` | 0.2 | Delay between T1 and T2 (seconds) |
| `GROQ_MODEL` | "llama-3.3-70b-versatile" | LLM model |
| `GROQ_TIMEOUT` | 10 | API timeout in seconds |

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
