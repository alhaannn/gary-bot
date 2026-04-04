"""
Signal Parser - Groq API integration for channel-specific signal classification

Parses Telegram messages from multiple channels using channel-specific prompts.
Uses Groq API with llama-3.3-70b-versatile model.
"""

import json
import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from logger import get_logger
from config import GROQ_API_KEY, GROQ_MODEL, GROQ_TIMEOUT

logger = get_logger()

# Cache for loaded prompts
_PROMPT_CACHE = {}


def load_channel_prompt(channel_name: str) -> str:
    """
    Load system prompt for a specific channel from prompts directory.

    Args:
        channel_name: Channel identifier (e.g., "gary", "goldtradersunny")

    Returns:
        System prompt string for that channel
    """
    if channel_name in _PROMPT_CACHE:
        return _PROMPT_CACHE[channel_name]

    # Find channel config to get prompt file
    from config import CHANNELS
    channel_config = next(
        (c for c in CHANNELS if c["name"] == channel_name),
        None
    )

    if not channel_config:
        logger.error(f"[PARSER] Channel config not found: {channel_name}")
        # Fall back to Gary's prompt
        prompt_file = Path("prompts/gary.txt")
    else:
        prompt_file = Path(channel_config["prompt_file"])

    try:
        if prompt_file.exists():
            prompt = prompt_file.read_text(encoding="utf-8")
            _PROMPT_CACHE[channel_name] = prompt
            logger.debug(f"[PARSER] Loaded prompt for {channel_name} from {prompt_file}")
            return prompt
        else:
            logger.warning(f"[PARSER] Prompt file not found: {prompt_file}, using Gary's prompt")
            return load_channel_prompt("gary")
    except Exception as e:
        logger.error(f"[PARSER] Failed to load prompt for {channel_name}: {e}")
        return load_channel_prompt("gary")


def parse_signal(message_text: str, channel_name: str = "gary") -> Dict[str, Any]:
    """
    Parse a Telegram message using Groq API with channel-specific prompt.

    Args:
        message_text: Raw message text from Telegram
        channel_name: Channel identifier to select appropriate prompt

    Returns:
        Dict with signal classification. For ENTRY includes direction, prices, etc.
        Default {"type": "IGNORE"} on any error.
    """
    if not message_text or not message_text.strip():
        logger.debug("[PARSER] Empty message, returning IGNORE")
        return {"type": "IGNORE"}

    message_text = message_text.strip()
    logger.info(f"[PARSER] [{channel_name}] Processing message: {message_text[:100]}...")

    # Get channel-specific prompt
    system_prompt = load_channel_prompt(channel_name)

    try:
        # Build Groq API request
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "max_tokens": 500
        }

        logger.debug(f"[PARSER] [{channel_name}] Calling Groq API with model {GROQ_MODEL}")

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=GROQ_TIMEOUT
        )

        if response.status_code != 200:
            logger.error(f"[PARSER] [{channel_name}] Groq API error: {response.status_code} - {response.text[:200]}")
            return {"type": "IGNORE"}

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            logger.warning(f"[PARSER] [{channel_name}] Groq returned empty content")
            return {"type": "IGNORE"}

        # Parse JSON response
        parsed = json.loads(content)
        logger.info(f"[PARSER] [{channel_name}] ✅ Classified as: {parsed.get('type')}")

        # Validate and normalize ENTRY response
        if parsed.get("type") == "ENTRY":
            # Ensure required fields
            direction = parsed.get("direction", "").upper()
            if direction not in ["BUY", "SELL"]:
                logger.warning(f"[PARSER] [{channel_name}] Invalid direction: {direction}")
                return {"type": "IGNORE"}

            # Validate prices
            entry_high = parsed.get("entry_high")
            entry_low = parsed.get("entry_low")
            sl = parsed.get("sl")

            try:
                entry_high = float(entry_high)
                entry_low = float(entry_low)
                sl = float(sl)
            except (TypeError, ValueError):
                logger.warning(f"[PARSER] [{channel_name}] Invalid price values in ENTRY response")
                return {"type": "IGNORE"}

            # Ensure entry_high > entry_low
            if entry_high <= entry_low:
                logger.warning(f"[PARSER] [{channel_name}] entry_high must be > entry_low")
                return {"type": "IGNORE"}

            # Validate TP fields (at least one must be present)
            tp1 = parsed.get("tp1")
            tp2 = parsed.get("tp2")
            tp3 = parsed.get("tp3")
            tp4 = parsed.get("tp4")
            tp1_pips = parsed.get("tp1_pips")
            tp2_pips = parsed.get("tp2_pips")
            tp3_pips = parsed.get("tp3_pips")
            tp4_pips = parsed.get("tp4_pips")

            if all(v is None for v in [tp1, tp2, tp3, tp4, tp1_pips, tp2_pips, tp3_pips, tp4_pips]):
                logger.warning(f"[PARSER] [{channel_name}] ENTRY missing TP info")
                return {"type": "IGNORE"}

            # Normalize TP values (convert price strings to float, pips to int)
            parsed["tp1"] = float(tp1) if tp1 is not None else None
            parsed["tp2"] = float(tp2) if tp2 is not None else None
            parsed["tp3"] = float(tp3) if tp3 is not None else None
            parsed["tp4"] = float(tp4) if tp4 is not None else None
            parsed["tp1_pips"] = int(tp1_pips) if tp1_pips is not None else None
            parsed["tp2_pips"] = int(tp2_pips) if tp2_pips is not None else None
            parsed["tp3_pips"] = int(tp3_pips) if tp3_pips is not None else None
            parsed["tp4_pips"] = int(tp4_pips) if tp4_pips is not None else None

            logger.debug(f"[PARSER] [{channel_name}] ENTRY details: {direction} @ {entry_low}-{entry_high} SL:{sl}")

        # Validate SL_MODIFY response
        elif parsed.get("type") == "SL_MODIFY":
            new_sl = parsed.get("new_sl")

            if new_sl is None:
                logger.warning(f"[PARSER] [{channel_name}] SL_MODIFY missing new_sl field")
                return {"type": "IGNORE"}

            try:
                new_sl = float(new_sl)
                # Validate price is in XAUUSD range (4000-5000)
                if not (4000 <= new_sl <= 5000):
                    logger.warning(f"[PARSER] [{channel_name}] SL_MODIFY new_sl out of range: {new_sl}")
                    return {"type": "IGNORE"}
                parsed["new_sl"] = new_sl
            except (TypeError, ValueError):
                logger.warning(f"[PARSER] [{channel_name}] SL_MODIFY new_sl is not a valid number")
                return {"type": "IGNORE"}

            logger.info(f"[PARSER] [{channel_name}] SL_MODIFY details: new SL = {new_sl:.2f}")

        return parsed

    except json.JSONDecodeError as e:
        logger.error(f"[PARSER] [{channel_name}] Failed to parse Groq JSON response: {e}")
        return {"type": "IGNORE"}
    except requests.exceptions.Timeout:
        logger.error(f"[PARSER] [{channel_name}] Groq request timeout")
        return {"type": "IGNORE"}
    except requests.exceptions.RequestException as e:
        logger.error(f"[PARSER] [{channel_name}] Groq request failed: {e}")
        return {"type": "IGNORE"}
    except Exception as e:
        logger.error(f"[PARSER] [{channel_name}] Unexpected error: {e}")
        return {"type": "IGNORE"}
