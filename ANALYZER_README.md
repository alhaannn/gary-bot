# Channel Analyzer & Prompt Generator

## Purpose

Read-only tool that analyzes Telegram channels, detects signal patterns, and generates production-ready parsing prompts for GaryBot's multi-channel support.

## Usage

```bash
# Make sure you have run main.py at least once to create the Telethon session
python main.py

# Then run the analyzer (separate process)
python run_analyzer.py
```

## How It Works

1. **Connects** to Telegram using existing `gary_bot_session` (no new auth)
2. **Fetches** last 200 text messages from each enabled channel
3. **Filters** out:
   - Forwarded messages
   - Non-signal chatter (using keyword heuristics)
   - Short/empty messages
4. **Analyzes** signal structure patterns:
   - Entry format (`@ PRICE-RANGE`, `BUY @ PRICE`, etc.)
   - Stop loss notation (`Sl:`, `Stop Loss:`, etc.)
   - Take profit format (prices, pips, ranges)
   - Direction keywords (BUY/SELL, emojis, etc.)
   - Common symbols (XAUUSD, Gold, etc.)
5. **Generates** a channel-specific prompt that:
   - Includes real examples from the channel
   - Handles that channel's exact format variations
   - Enforces proper JSON response schema
   - Ignores noise/ads automatically

## Output

Generated prompts are saved to:

```
prompts/
├── gary.txt            (updated with Gary's patterns)
├── goldtradersunny.txt (new channel prompt)
├── bengoldtrader.txt   (new channel prompt)
└── gtmofx.txt          (new channel prompt)
```

## Customizing After Generation

The analyzer provides a **starting point**. Review each prompt and:

1. Check if detected patterns match your channel's actual signals
2. Add specific example messages in the "EXAMPLES FROM THIS CHANNEL" section
3. Adjust keyword lists if needed
4. Tune confidence by adding/removing IGNORE triggers

## Configuration

The analyzer uses the same `config.py` as the main bot:

- `CHANNELS` - list of channels to analyze
- `USE_LEGACY_SINGLE_CHANNEL` - set to True to analyze only legacy channel
- Channel `enabled` flag - disabled channels are skipped

## Safety

- **Read-only**: Only reads messages, never sends anything
- **No modifications**: Does not change existing bot files
- **Non-blocking**: Separate process, doesn't affect running bot
- **Session reuse**: Uses same session file, no new auth needed

## Requirements

- Existing `gary_bot_session` file (created by running `python main.py` once)
- Channel join status: You must have joined the channels already
- Telethon installed (`pip install telethon`)
- Network connectivity to Telegram

## Output Prompt Format

Each `prompts/{channel}.txt` file contains a complete system prompt ready for use with the multi-channel bot. The prompt includes:

- Channel-specific signal classification rules
- Observed entry/SL/TP formats from actual messages
- 2-3 real example signals
- Strict JSON response schema
- PARSING RULES tailored to that channel's style

Use these prompts directly in the multi-channel bot without modification (unless you want to fine-tune further).
