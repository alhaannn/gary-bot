"""
Channel Analyzer & Prompt Generator

Read-only script that:
1. Connects to Telegram using existing session
2. Extracts messages from configured channels
3. Analyzes signal patterns
4. Generates final parsing prompts for each channel

Usage:
    python run_analyzer.py

DOES NOT modify any bot files. Read-only operation.
"""

import asyncio
import json
import logging
import re
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from difflib import SequenceMatcher

from telethon import TelegramClient
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, CHANNELS, USE_LEGACY_SINGLE_CHANNEL, LEGACY_CHANNEL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("analyzer")


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
        if len(self.patterns['structures']) < 5:
            self.patterns['structures'].append(text[:200])

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
            'sample_signals': self.signal_examples[:5],
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
        # Build the prompt based on observed patterns
        return PromptBuilder.build(channel_name, analysis)


class PromptBuilder:
    """Build prompts using observed patterns."""

    @staticmethod
    def build(channel_name: str, analysis: Dict) -> str:
        samples = analysis.get('sample_signals', [])
        entry_fmt = analysis.get('entry_format', [])
        sl_fmt = analysis.get('sl_format', [])
        tp_fmt = analysis.get('tp_format', [])

        # Extract common patterns from samples (if we have them)
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


async def analyze_channel(client: TelegramClient, channel_username: str, channel_name: str, limit: int = 200) -> Dict:
    """
    Analyze a single channel and return pattern data.

    Args:
        client: Authenticated Telethon client
        channel_username: Channel username (with or without @)
        channel_name: Internal channel identifier
        limit: Number of messages to fetch

    Returns:
        Analysis summary dictionary
    """
    logger.info(f"[{channel_name}] Analyzing channel: {channel_username}")

    try:
        # Resolve channel entity
        channel = await client.get_entity(channel_username)
        logger.info(f"[{channel_name}] Resolved: {channel.title} (ID: {channel.id})")

        # Fetch recent messages
        messages = []
        async for msg in client.iter_messages(channel, limit=limit):
            if msg.text:  # Only text messages
                messages.append(msg)

        logger.info(f"[{channel_name}] Fetched {len(messages)} text messages")

        # Analyze messages
        extractor = SignalPatternExtractor(channel_name)

        for msg in messages:
            is_forwarded = getattr(msg, 'fwd_from', None) is not None
            extractor.add_message(msg.text, is_forwarded)

        summary = extractor.get_summary()

        logger.info(f"[{channel_name}] Detected {summary['signal_messages_detected']} signal-like messages "
                    f"({summary['signal_percentage']:.1f}%)")

        if summary['sample_signals']:
            logger.info(f"[{channel_name}] Sample signal: {summary['sample_signals'][0][:60]}...")

        return summary

    except Exception as e:
        logger.error(f"[{channel_name}] Error analyzing channel: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return {
            'channel': channel_name,
            'error': str(e),
            'total_messages_analyzed': 0,
            'signal_messages_detected': 0
        }


def save_prompt(channel_name: str, prompt: str, output_dir: str = "prompts"):
    """Save generated prompt to file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    prompt_file = output_dir / f"{channel_name}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    logger.info(f"[{channel_name}] ✅ Prompt saved to {prompt_file}")


async def main():
    """Main analyzer entry point."""
    logger.info("=" * 80)
    logger.info("📊 Channel Analyzer & Prompt Generator")
    logger.info("=" * 80)

    # Determine which channels to analyze
    if USE_LEGACY_SINGLE_CHANNEL:
        channels_to_analyze = [{"name": "gary", "username": LEGACY_CHANNEL}]
        logger.info("Running in LEGACY single-channel mode")
    else:
        channels_to_analyze = [
            {"name": ch["name"], "username": ch["username"]}
            for ch in CHANNELS
            if ch["enabled"]
        ]
        logger.info(f"Multi-channel mode: {len(channels_to_analyze)} channels to analyze")

    if not channels_to_analyze:
        logger.error("No channels configured! Check CHANNELS in config.py")
        return 1

    # Create Telegram client (reuse existing session, read-only)
    client = TelegramClient("gary_bot_session", TELEGRAM_API_ID, TELEGRAM_API_HASH)

    try:
        # Connect using existing session (no new auth flow)
        logger.info("Connecting to Telegram...")
        await client.connect()

        if not await client.is_user_authorized():
            logger.error("Session not authorized! Please run the main bot first to create the session.")
            return 1

        logger.info("✅ Connected (read-only mode)")

        # Analyze each channel
        for ch in channels_to_analyze:
            try:
                analysis = await analyze_channel(client, ch["username"], ch["name"], limit=200)

                if analysis.get('signal_messages_detected', 0) < 5:
                    logger.warning(f"[{ch['name']}] Very few signals detected ({analysis['signal_messages_detected']}). "
                                   f"Prompt may need manual tuning.")

                # Generate prompt
                generator = PromptGenerator()
                prompt = generator.generate_prompt(ch["name"], analysis)

                # Save prompt
                save_prompt(ch["name"], prompt)

                # Print summary
                logger.info(f"[{ch['name']}] Summary:")
                logger.info(f"  - Total messages: {analysis.get('total_messages_analyzed', 0)}")
                logger.info(f"  - Signals detected: {analysis.get('signal_messages_detected', 0)}")
                logger.info(f"  - Entry format: {analysis.get('entry_format', [])}")
                logger.info(f"  - SL format: {analysis.get('sl_format', [])}")
                logger.info(f"  - TP format: {analysis.get('tp_format', [])}")
                logger.info(f"  - Directions: {analysis.get('directions', {})}")

            except Exception as e:
                logger.error(f"[{ch.get('name', 'unknown')}] Failed to analyze: {e}")
                continue

        logger.info("=" * 80)
        logger.info("✅ Analysis complete! Prompts saved in prompts/ directory")
        logger.info("Review the generated prompts and adjust if needed.")
        logger.info("=" * 80)

        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1

    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\nInterrupted")
        exit(0)
