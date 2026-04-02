Build a complete automated Gold trading bot called "GaryBot" that monitors a Telegram channel and executes trades on MetaTrader5 automatically.

=== PROJECT STRUCTURE ===
Create these files:
gary-bot/
├── config.py
├── logger.py
├── signal_parser.py
├── trade_manager.py
├── trade_executor.py
├── telegram_listener.py
├── main.py
└── requirements.txt

=== WHAT THE BOT DOES ===
1. Monitors a public Telegram channel (@Gary_TheTrader) in real time using Telethon
2. Every new message is sent to Groq API (LLM) for classification
3. Based on classification, executes trades on MetaTrader5

=== CREDENTIALS (fill placeholders) ===
- Telegram API ID: YOUR_API_ID
- Telegram API Hash: YOUR_API_HASH
- Telegram Phone: YOUR_PHONE
- Telegram Channel: Gary_TheTrader
- Groq API Key: YOUR_GROQ_API_KEY
- Groq Model: llama-3.3-70b-versatile
- MT5 Login: YOUR_MT5_LOGIN
- MT5 Password: YOUR_MT5_PASSWORD
- MT5 Server: YOUR_MT5_SERVER
- Symbol: XAUUSD
- Lot size per trade: 0.01
- Magic number: 20250101
- Slippage: 10

=== SIGNAL CLASSIFICATION (Groq) ===
Send every Telegram message to Groq with this system prompt context:

Gary is a Gold (XAUUSD) trader who posts signals in these exact formats:

ENTRY signals:
- "Gold Buy Now @ 4481 - 4476  Sl: 4471  TP: 4486/4491"
- "Gold Sell Now @ 4452 - 4457  Sl: 4462  TP: 4442/4432"
- "Im buying gold now @ 4562 - 4555  Sl: 4552  Tp: 4572/4582"
- "Gold Buy Now @ 4420 - 4415  Sl: 4410  Tp: 100/200Pips"
- "Gold Sell Now @ 4450 - 4455  Sl: 4460  TP: 100/200Pips"

PARTIAL signals (close T1, move T2 to breakeven):
- "60Pips can close some now"
- "50Pips now in profit can secure some now"
- "60Pips now in profit can secure some now"
- "Almost 100Pips ! Can take some profit"
- "60Pips ! Scalper can secure some"

CLOSE signals (close T2 fully):
- "Boom ! Can take the profit 100PIPS"
- "200Pips ! Can take as Tp2"
- "100PIPS can close all"

SL_HIT signals (log only, MT5 already closed trades):
- "This setup hit SL. Wait for recovery"
- "This setup hit my risk."

IGNORE (everything else):
- "Ready", "Ready !", "Ready recovery !"
- "Ready, i want to take some risk."
- "I want to take some risk now"
- "Be Ready for next setup"
- "One more time ?"
- "Live is starting now on TikTok!"
- Motivational messages, community updates
- Voice note captions, image captions
- Any message that doesn't clearly fit above types
- When in doubt → always return IGNORE to avoid bad trades

Groq must return JSON only, no markdown, no extra text:

For ENTRY:
{
  "type": "ENTRY",
  "direction": "BUY" or "SELL",
  "entry_high": <larger price as float>,
  "entry_low": <smaller price as float>,
  "sl": <stop loss as float>,
  "tp1": <TP1 price as float or null>,
  "tp2": <TP2 price as float or null>,
  "tp1_pips": <TP1 pips as int or null>,
  "tp2_pips": <TP2 pips as int or null>
}

For everything else:
{
  "type": "PARTIAL" | "CLOSE" | "SL_HIT" | "IGNORE"
}

Important parsing notes:
- XAUUSD prices are in the 4000-5000 range
- entry_high is always the larger number regardless of BUY/SELL
- entry_low is always the smaller number regardless of BUY/SELL
- If TP is "100/200Pips" → tp1=null, tp2=null, tp1_pips=100, tp2_pips=200
- Use temperature=0.0 for deterministic output
- Use response_format json_object
- Timeout = 10 seconds
- On any Groq error/timeout → return {"type": "IGNORE"} silently

=== TRADE EXECUTION LOGIC ===

ON ENTRY signal:
- Calculate entry_price = (entry_high + entry_low) / 2
- If TP is pips-based: for BUY → tp = entry_price + (pips * 0.1), for SELL → tp = entry_price - (pips * 0.1)  [XAUUSD: 1 pip = 0.1]
- Open Trade 1: 0.01 lot, market order, SL=signal SL, TP=tp1, comment="Gary_T1_{signal_id}"
- Wait 200ms
- Open Trade 2: 0.01 lot, market order, SL=signal SL, TP=tp2, comment="Gary_T2_{signal_id}"
- signal_id = timestamp string YYYYMMDDHHMMSS
- If a previous Trade 2 is still open → stack positions, open 2 new trades anyway
- Save trade group to trades.json

ON PARTIAL signal:
- Find all trade groups where T1 is not yet closed
- For each group:
  - Close Trade 1 fully (market close)
  - Move Trade 2 SL to breakeven (entry_price)
  - Mark T1 as closed in trades.json

ON CLOSE signal:
- Find all trade groups where T2 is not yet closed
- For each group:
  - If T1 still open → close T1 first
  - Close Trade 2 fully (market close)
  - Mark both as closed in trades.json

ON SL_HIT signal:
- Find all open trade groups
- Mark all as closed in trades.json (MT5 already closed them via SL)
- Log the event

ON IGNORE:
- Do nothing, just log

=== TRADE MANAGER (trades.json) ===
Persist all open trades to trades.json so state survives bot restarts.

Each trade group:
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
  "t2_closed": false
}

Functions needed:
- load_trades() → list
- save_trades(trades)
- add_trade_group(signal_id, direction, entry_price, sl, tp1, tp2, ticket1, ticket2)
- get_open_groups() → groups where t2_closed=false
- get_partial_eligible_groups() → groups where t1_closed=false AND t2_closed=false
- mark_t1_closed(signal_id)
- mark_t2_closed(signal_id)
- mark_both_closed(signal_id)

=== MT5 EXECUTOR ===
Use MetaTrader5 Python package.

Functions needed:
- connect_mt5() → bool: initialize + login, log account info
- disconnect_mt5(): shutdown
- get_current_price(direction) → float: ask for BUY, bid for SELL
- open_trade(direction, sl, tp, comment) → int: returns ticket or -1 on fail
  - Use ORDER_TYPE_BUY or ORDER_TYPE_SELL
  - Use TRADE_ACTION_DEAL
  - Use ORDER_TIME_GTC
  - Use ORDER_FILLING_IOC
- open_two_trades(direction, sl, tp1, tp2, signal_id) → (ticket1, ticket2)
- close_trade(ticket) → bool:
  - If position not found → return True (already closed by SL/TP)
  - Close with opposite market order
- move_sl_to_breakeven(ticket, entry_price) → bool:
  - Use TRADE_ACTION_SLTP
  - Keep existing TP, only change SL
- calculate_entry_price(entry_high, entry_low) → float: midpoint rounded to 2 decimals
- calculate_tp_from_pips(direction, entry_price, pips) → float

=== TELEGRAM LISTENER ===
Use Telethon library.
- Monitor channel: Gary_TheTrader
- On new message → extract message.message (raw text)
- Skip if message is empty or media-only (no text)
- Call async handle_message(message) from main.py
- Session file: gary_bot_session
- Start with phone number authentication

=== LOGGER ===
- Use Python logging module
- Log to both console (INFO level) and gary_bot.log file (DEBUG level)
- Format: "YYYY-MM-DD HH:MM:SS [LEVEL] message"
- Single logger instance imported everywhere

=== MAIN.PY ===
Async orchestrator:
1. Connect MT5 on startup → abort if fails
2. Create Telethon client
3. Register handle_message as the message handler
4. Start Telegram listener (blocking)
5. On KeyboardInterrupt → disconnect MT5, log shutdown

handle_message(message) flow:
1. Call parse_signal(message) → get parsed dict
2. Route to correct handler based on type
3. Log every action with ✅ or ❌ emoji for easy log reading

=== REQUIREMENTS.TXT ===
telethon
requests
MetaTrader5

(No version pins — use latest compatible versions)

=== ERROR HANDLING ===
- All MT5 operations wrapped in proper error checking
- If Groq times out → return IGNORE, never crash
- If MT5 position not found when closing → treat as success (already closed)
- If trade open fails → log error, do not add to trades.json
- Never crash the main loop on any single message error
- Wrap handle_message in try/except so one bad message never kills the bot

=== LOGGING STYLE ===
Use these prefixes consistently:
- [TELEGRAM] for listener events
- [PARSER] for Groq classification results
- [MT5] for all MT5 operations
- [TRADE MANAGER] for trades.json operations
- [MAIN] for orchestration events
- Use ✅ for success, ❌ for failure, ⚠️ for warnings

=== IMPORTANT NOTES ===
- Bot runs 24/7 on Windows Server EC2
- MT5 must be running separately before bot starts
- First run will prompt for Telegram phone verification (one time only)
- XAUUSD on MT5 may appear as "XAUUSD" or "XAUUSDm" depending on broker — use whatever is in config
- All prices are floats rounded to 2 decimal places
- Do not use any version pins in requirements.txt
- Keep all files clean, well commented, production ready




github :-

echo "# gary-bot" >> README.md
git init
git add README.md
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/alhaannn/gary-bot.git
git push -u origin main