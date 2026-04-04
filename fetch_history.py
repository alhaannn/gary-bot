"""
Historical Message Fetcher + Analyzer + Prompt Generator for GaryBot

This script:
1. Connects to Telegram using existing session
2. Fetches historical messages from configured channels (2000+ per channel)
3. Analyzes each channel's signal patterns
4. Generates/updates channel-specific prompts based on their style
5. Skips 'traderalhan' channel (it's the universal testing channel)

Usage:
    python fetch_history.py
"""

import asyncio
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import List, Dict

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    ApiIdInvalidError,
    FloodWaitError
)

from config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_PHONE,
    CHANNELS,
    USE_LEGACY_SINGLE_CHANNEL,
    LEGACY_CHANNEL,
    HISTORY_LIMIT
)
from logger import get_logger

logger = get_logger()


class SignalPatternExtractor:
    """Extract and analyze signal patterns from channel messages."""

    def __init__(self, channel_name: str):
        self.channel_name = channel_name
        self.messages = []
        self.signal_examples = []
        self.patterns = {
            'entry_formats': Counter(),
            'sl_formats': Counter(),
            'tp_formats': Counter(),
            'direction_keywords': Counter(),
            'symbols': Counter(),
            'structures': []  # List of full signal structures
        }

    def add_message(self, text: str, is_forwarded: bool = False):
        """Add a message for analysis."""
        if is_forwarded:
            return  # Skip forwarded messages

        text = text.strip()
        if not text or len(text) < 10:
            return

        self.messages.append(text)

        # Quick check: is this likely a trading signal?
        if self._is_signal_candidate(text):
            self.signal_examples.append(text)
            self._analyze_signal(text)

    def _is_signal_candidate(self, text: str) -> bool:
        """Quick heuristic to identify signal messages."""
        text_lower = text.lower()

        # Skip obvious non-signals
        skip_keywords = ['advertise', 'sponsored', 'promotion', 'join now', 'free signal',
                         'dm for', 'contact', 'telegram group', 'welcome', 'hello', 'hi ',
                         'how are you', 'good morning', 'thanks', 'thank you']

        for kw in skip_keywords:
            if kw in text_lower:
                return False

        # Need at least one signal keyword
        signal_keywords = ['buy', 'sell', '@', 'sl:', 'tp:', 'stop loss', 'take profit',
                          'long', 'short', 'entry', 'target', 'stop', 'pips']
        has_signal = any(kw in text_lower for kw in signal_keywords)

        # Or contain price pattern (4000-6000 range for gold)
        price_match = re.search(r'\b(4[0-9]{3,4}|5[0-9]{3,4})\b', text)
        if price_match:
            has_signal = True

        return has_signal

    def _analyze_signal(self, text: str):
        """Extract patterns from a signal message."""
        text_lower = text.lower()

        # Detect direction
        if 'buy' in text_lower or 'long' in text_lower or '🟢' in text or '📈' in text:
            self.patterns['direction_keywords']['BUY'] += 1
        if 'sell' in text_lower or 'short' in text_lower or '🔴' in text or '📉' in text:
            self.patterns['direction_keywords']['SELL'] += 1

        # Detect entry format
        if '@' in text:
            self.patterns['entry_formats']['@ PRICE or RANGE'] += 1
        if re.search(r'\bbuy\s+@?', text_lower) or re.search(r'\bsell\s+@?', text_lower):
            self.patterns['entry_formats']['DIRECTION @ PRICE'] += 1
        if re.search(r'\d{4,5}\s*[-–—]\s*\d{4,5}', text):
            self.patterns['entry_formats']['RANGE'] += 1

        # Detect SL format
        if re.search(r'\bsl\s*[:=]?\s*\d', text_lower):
            self.patterns['sl_formats']['SL: XXX'] += 1
        if re.search(r'\bstop\s*(loss)?\s*[:=]?\s*\d', text_lower):
            self.patterns['sl_formats']['STOP LOSS: XXX'] += 1

        # Detect TP format
        if re.search(r'\btp\s*[:=]?\s*\d', text_lower):
            self.patterns['tp_formats']['TP: XXX'] += 1
        if re.search(r'\d+\s*/?\s*\d*\s*pips?', text_lower):
            self.patterns['tp_formats']['PIPS'] += 1
        if re.search(r'\d{4,5}\s*[/]\s*\d{4,5}', text):
            self.patterns['tp_formats']['RANGE SLASH'] += 1

        # Detect symbol
        symbols = ['xauusd', 'gold', 'nas100', 'nasdaq', 'us30', 'spx', 'eurusd', 'gbpusd']
        for sym in symbols:
            if sym in text_lower:
                self.patterns['symbols'][sym.upper()] += 1

        # Store structure example
        if len(self.patterns['structures']) < 10:
            self.patterns['structures'].append(text[:300])

    def get_summary(self) -> Dict:
        """Get analysis summary."""
        total_signals = len(self.signal_examples)
        total_messages = len(self.messages)

        return {
            'channel': self.channel_name,
            'total_messages_analyzed': total_messages,
            'signal_messages_detected': total_signals,
            'signal_percentage': (total_signals / total_messages * 100) if total_messages > 0 else 0,
            'entry_format': self.patterns['entry_formats'].most_common(2),
            'sl_format': self.patterns['sl_formats'].most_common(2),
            'tp_format': self.patterns['tp_formats'].most_common(2),
            'directions': dict(self.patterns['direction_keywords']),
            'symbols': dict(self.patterns['symbols'].most_common(3)),
            'sample_signals': self.signal_examples[:10],
            'raw_patterns': dict(self.patterns)
        }


class PromptGenerator:
    """Generate channel-specific parsing prompts."""

    @staticmethod
    def generate_prompt(channel_name: str, analysis: Dict) -> str:
        """
        Generate final parsing prompt based on analysis.

        Args:
            channel_name: Channel identifier
            analysis: Output from SignalPatternExtractor.get_summary()

        Returns:
            Complete system prompt ready for production use
        """
        return PromptBuilder.build(channel_name, analysis)


class PromptBuilder:
    """Build prompts using observed patterns."""

    @staticmethod
    def build(channel_name: str, analysis: Dict) -> str:
        samples = analysis.get('sample_signals', [])
        entry_fmt = analysis.get('entry_format', [])
        sl_fmt = analysis.get('sl_format', [])
        tp_fmt = analysis.get('tp_format', [])

        # Extract common patterns from samples
        common_patterns = PromptBuilder._extract_examples(samples)

        prompt = f"""You are a Gold trading signal classifier for channel: {channel_name}.

TASK: Classify Telegram messages into signal types.

SIGNAL TYPES:

1. ENTRY - New trade entry with direction, entry zone, stop loss, and take profit(s)

   Observed formats from this channel:
{common_patterns['entry_examples']}

   Key elements detected:
   - Direction: {', '.join(analysis.get('directions', {}).keys()) or 'BUY/SELL'}
   - Entry: {entry_fmt[0][0] if entry_fmt else 'PRICE or PRICE RANGE'}
   - Stop Loss: {sl_fmt[0][0] if sl_fmt else 'SL: price'}
   - Take Profit: {tp_fmt[0][0] if tp_fmt else 'TP: price(s) or pips'}

2. PARTIAL - Close partial position, secure profits, move remainder to breakeven
   Keywords: "close some", "secure profit", "take half", "partial", "book some"

3. CLOSE - Close all remaining positions
   Keywords: "close all", "exit all", "take profit", "full close"

4. SL_HIT - Stop loss hit
   Keywords: "hit sl", "stop loss", "hit my risk"

5. SL_MODIFY - Change stop loss level
   Must include: new stop loss price

6. IGNORE - Everything else (chatter, ads, updates)

PRICE RANGE: XAUUSD typically 4000-6000

RESPONSE FORMAT - JSON only, no markdown:

For ENTRY:
{{
  "type": "ENTRY",
  "direction": "BUY" or "SELL",
  "entry_high": <larger price as float>,
  "entry_low": <smaller price as float>,
  "sl": <stop loss as float>,
  "tp1": <TP1 price as float or null>,
  "tp2": <TP2 price as float or null>,
  "tp1_pips": <TP1 pips as int or null>,
  "tp2_pips": <TP2 pips as int or null>
}}

For SL_MODIFY:
{{
  "type": "SL_MODIFY",
  "new_sl": <stop loss price as float>
}}

For all others:
{{"type": "PARTIAL" | "CLOSE" | "SL_HIT" | "IGNORE"}}

PARSING RULES:
- Extract numeric values ignoring currency symbols, commas
- If range given (4476-4481), entry_high=4481, entry_low=4476
- If single price given (4481), treat as both entry_high and entry_low
- For pips: 100 pips = 10.0 for XAUUSD (1 pip = 0.1)
- When uncertain → IGNORE
- Reject incomplete signals (missing direction, entry, or SL)

EXAMPLES FROM THIS CHANNEL:

{common_patterns['full_examples']}

Analyze the message and return only the JSON.
"""
        return prompt

    @staticmethod
    def _extract_examples(samples: List[str]) -> Dict[str, str]:
        """Extract formatted examples from sample signals."""
        if not samples:
            return {
                'entry_examples': '   (No examples detected - adjust based on channel)',
                'full_examples': '   (No examples detected)'
            }

        # Take up to 3 clear examples
        example_lines = []
        for i, sample in enumerate(samples[:3], 1):
            clean = sample.replace('\n', ' ').strip()
            if len(clean) > 150:
                clean = clean[:147] + '...'
            example_lines.append(f"   Example {i}: {clean}")

        return {
            'entry_examples': '\n'.join(example_lines) if example_lines else '   (No clear examples)',
            'full_examples': '\n'.join(example_lines) if example_lines else '   (No clear examples)'
        }


async def fetch_channel_messages(client, channel_config, limit: int) -> List[Dict]:
    """
    Fetch messages from a single channel.

    Returns:
        List of dicts with 'text', 'date', 'message_id'
    """
    channel_name = channel_config["name"]
    username = channel_config["username"]

    # Skip traderalhan - it's the universal testing channel, not for analysis
    if channel_name == "traderalhan":
        logger.info(f"[FETCH] ⏭️ Skipping '{channel_name}' (universal testing channel)")
        return []

    try:
        channel_entity = await client.get_entity(username)
        logger.info(f"[FETCH] 📥 Fetching up to {limit} messages from '{channel_name}' ({username})")

        messages = []
        count = 0

        async for message in client.iter_messages(channel_entity, limit=limit):
            if not message.text:
                continue

            msg_data = {
                "message_id": message.id,
                "date": message.date.isoformat() if message.date else None,
                "text": message.text.strip()
            }
            messages.append(msg_data)
            count += 1

        logger.info(f"[FETCH] ✅ Retrieved {count} messages from '{channel_name}'")
        return messages

    except Exception as e:
        logger.error(f"[FETCH] ❌ Failed to fetch from channel '{channel_name}': {e}")
        return []


def save_messages_to_json(channel_name: str, messages: List[Dict], output_dir: str = "history"):
    """Save fetched messages to per-channel JSON file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{channel_name}_messages.json"

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        logger.info(f"[FETCH] 💾 Saved {len(messages)} messages to {output_file}")
    except Exception as e:
        logger.error(f"[FETCH] ❌ Failed to write {output_file}: {e}")


def save_prompt(channel_name: str, prompt: str, output_dir: str = "prompts"):
    """Save generated prompt to file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    prompt_file = output_dir / f"{channel_name}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    logger.info(f"[ANALYZE] ✅ Prompt for {channel_name} saved to {prompt_file}")


async def analyze_and_generate_prompt(channel_name: str, messages: List[Dict]):
    """
    Analyze fetched messages and generate/update channel-specific prompt.

    Args:
        channel_name: Name of the channel
        messages: List of message dicts with 'text' field
    """
    logger.info(f"[ANALYZE] 🔍 Analyzing {len(messages)} messages from '{channel_name}'")

    extractor = SignalPatternExtractor(channel_name)

    for msg in messages:
        extractor.add_message(msg["text"], is_forwarded=False)

    summary = extractor.get_summary()

    logger.info(f"[ANALYZE] 📊 {channel_name}: {summary['signal_messages_detected']} signals detected "
                f"({summary['signal_percentage']:.1f}% of {summary['total_messages_analyzed']} messages)")

    if summary['sample_signals']:
        logger.info(f"[ANALYZE] Sample: {summary['sample_signals'][0][:80]}...")

    # Generate new prompt
    generator = PromptGenerator()
    prompt = generator.generate_prompt(channel_name, summary)

    # Save prompt (overwrites existing)
    save_prompt(channel_name, prompt)

    return summary


async def main():
    """
    Main: Connect to Telegram, fetch history, analyze patterns, generate prompts.

    Process:
    1. Connect to Telegram (reuse existing session)
    2. For each enabled channel (except traderalhan):
       - Fetch up to HISTORY_LIMIT messages
       - Save raw messages to history/{channel}_messages.json
       - Analyze signal patterns
       - Generate/update prompt file in prompts/{channel}.txt
    3. Log summary statistics
    """
    logger.info("=" * 80)
    logger.info("[FETCH] 🚀 Starting Historical Message Fetch + Analysis")
    logger.info("=" * 80)

    # Check config placeholders
    if isinstance(TELEGRAM_API_ID, str) and "YOUR_" in TELEGRAM_API_ID:
        logger.warning("[FETCH] ⚠️ Config placeholders detected! Fill in config.py with your credentials.")
        return 1

    # Determine which channels to process
    if USE_LEGACY_SINGLE_CHANNEL:
        channels_to_process = [{"name": "gary", "username": LEGACY_CHANNEL, "enabled": True}]
        logger.info("[FETCH] Running in LEGACY single-channel mode")
    else:
        channels_to_process = [c for c in CHANNELS if c["enabled"]]
        logger.info(f"[FETCH] Multi-channel mode: {len(channels_to_process)} channels")

    if not channels_to_process:
        logger.error("[FETCH] No channels enabled! Check CHANNELS configuration.")
        return 1

    # Create output directories
    history_dir = Path("history")
    history_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"[FETCH] History output: {history_dir.absolute()}")

    # Create Telegram client
    client = TelegramClient(
        "gary_bot_session",
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH
    )

    try:
        # Connect and authorize
        logger.info("[FETCH] Connecting to Telegram...")
        await client.connect()

        if not await client.is_user_authorized():
            logger.info("[FETCH] First-time authorization required")
            await client.send_code_request(TELEGRAM_PHONE)
            try:
                code = input(f"[FETCH] Enter verification code for {TELEGRAM_PHONE}: ")
                await client.sign_in(TELEGRAM_PHONE, code)
            except SessionPasswordNeededError:
                password = input("[FETCH] Two-factor password required: ")
                await client.sign_in(password=password)
            logger.info("[FETCH] ✅ Authorization successful")
        else:
            logger.info("[FETCH] ✅ Using existing session")

        # Process each channel
        total_messages = 0
        for channel_config in channels_to_process:
            channel_name = channel_config["name"]

            # Skip traderalhan
            if channel_name == "traderalhan":
                logger.info(f"[FETCH] ⏭️ Skipping '{channel_name}' (universal testing channel)")
                continue

            # Fetch messages
            messages = await fetch_channel_messages(client, channel_config, HISTORY_LIMIT)

            if not messages:
                logger.warning(f"[FETCH] ⚠️ No messages fetched for {channel_name}, skipping analysis")
                continue

            # Save raw messages to JSON
            save_messages_to_json(channel_name, messages, output_dir="history")
            total_messages += len(messages)

            # Analyze and generate/update prompt
            await analyze_and_generate_prompt(channel_name, messages)

            logger.info("-" * 80)

        logger.info("=" * 80)
        logger.info(f"[FETCH] ✅ Complete! Total messages: {total_messages}")
        logger.info(f"[FETCH] 📂 Raw messages: {history_dir.absolute()}")
        logger.info(f"[FETCH] 📝 Updated prompts in prompts/ directory")
        logger.info("=" * 80)

        return 0

    except PhoneNumberInvalidError:
        logger.error("[FETCH] ❌ Invalid phone number. Check TELEGRAM_PHONE in config.py")
        return 1
    except ApiIdInvalidError:
        logger.error("[FETCH] ❌ Invalid API ID/HASH. Check TELEGRAM_API_ID and TELEGRAM_API_HASH")
        return 1
    except FloodWaitError as e:
        logger.error(f"[FETCH] ❌ Flood wait: {e.seconds} seconds. Too many requests.")
        return 1
    except KeyboardInterrupt:
        logger.info("[FETCH] Interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"[FETCH] ❌ Fatal error: {e}")
        import traceback
        logger.debug(f"[FETCH] Traceback: {traceback.format_exc()}")
        return 1
    finally:
        await client.disconnect()
        logger.info("[FETCH] Disconnected from Telegram")


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n[FETCH] Interrupted")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"[FETCH] Fatal startup error: {e}")
        sys.exit(1)
