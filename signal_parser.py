"""
Signal Parser - Groq API integration for signal classification

Parses Telegram messages from Alhan into structured trade signals.
Uses Groq API with llama-3.3-70b-versatile model.
"""

import json
import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime

from logger import get_logger
from config import GROQ_API_KEY, GROQ_MODEL, GROQ_TIMEOUT

logger = get_logger()

# System prompt defining Alhan's exact signal formats
SYSTEM_PROMPT = """You are a Gold (XAUUSD) trading signal classifier for Alhan.

CLASSIFY messages into exactly one type:

1. ENTRY - New trade entry with explicit entry zone and SL/TP
   Formats:
   - "Gold Buy Now @ 4481 - 4476  Sl: 4471  TP: 4486/4491"
   - "Gold Sell Now @ 4452 - 4457  Sl: 4462  TP: 4442/4432"
   - "Im buying gold now @ 4562 - 4555  Sl: 4552  Tp: 4572/4582"
   - "Gold Buy Now @ 4420 - 4415  Sl: 4410  Tp: 100/200Pips"
   - "Gold Sell Now @ 4450 - 4455  Sl: 4460  TP: 100/200Pips"

   Key elements: @ PRICE1 - PRICE2, Sl: PRICE, TP: PRICE/PRICE or TP: NUMPIPS/NUMPIPSPips

2. PARTIAL - Close partial position, move remainder to breakeven
   Examples:
   - "60Pips can close some now"
   - "50Pips now in profit can secure some now"
   - "60Pips now in profit can secure some now"
   - "Almost 100Pips ! Can take some profit"
   - "60Pips ! Scalper can secure some"

3. CLOSE - Close remaining position (T2) fully
   Examples:
   - "Boom ! Can take the profit 100PIPS"
   - "200Pips ! Can take as Tp2"
   - "100PIPS can close all"

4. SL_HIT - Stop loss hit (MT5 auto-closed)
   Examples:
   - "This setup hit SL. Wait for recovery"
   - "This setup hit my risk."

5. IGNORE - Everything else:
   - "Ready", "Ready !", "Ready recovery !"
   - "Ready, i want to take some risk."
   - "I want to take some risk now"
   - "Be Ready for next setup"
   - "One more time ?"
   - "Live is starting now on TikTok!"
   - Motivational messages, community updates
   - Voice note captions, image captions
   - Any unclear message

PRICE RANGE: XAUUSD prices are 4000-5000 range
1 pip = 0.1 for XAUUSD

RESPONSE FORMAT - JSON only, no markdown:

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

For all other types:
{
  "type": "PARTIAL" | "CLOSE" | "SL_HIT" | "IGNORE"
}

PARSING RULES:
- Entry high is the larger number regardless of BUY/SELL
- Entry low is the smaller number regardless of BUY/SELL
- If TP is "100/200Pips" → tp1=null, tp2=null, tp1_pips=100, tp2_pips=200
- Extract numeric values from text (ignore commas, spaces)
- When in doubt → return IGNORE
"""


def parse_signal(message_text: str) -> Dict[str, Any]:
    """
    Parse a Telegram message using Groq API.

    Args:
        message_text: Raw message text from Telegram

    Returns:
        Dict with signal classification. For ENTRY includes direction, prices, etc.
        Default {"type": "IGNORE"} on any error.
    """
    if not message_text or not message_text.strip():
        logger.debug("[PARSER] Empty message, returning IGNORE")
        return {"type": "IGNORE"}

    message_text = message_text.strip()
    logger.info(f"[PARSER] Processing message: {message_text[:100]}...")

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
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message_text}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "max_tokens": 500
        }

        logger.debug(f"[PARSER] Calling Groq API with model {GROQ_MODEL}")

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=GROQ_TIMEOUT
        )

        if response.status_code != 200:
            logger.error(f"[PARSER] Groq API error: {response.status_code} - {response.text[:200]}")
            return {"type": "IGNORE"}

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            logger.warning("[PARSER] Groq returned empty content")
            return {"type": "IGNORE"}

        # Parse JSON response
        parsed = json.loads(content)
        logger.info(f"[PARSER] ✅ Classified as: {parsed.get('type')}")

        # Validate and normalize ENTRY response
        if parsed.get("type") == "ENTRY":
            # Ensure required fields
            direction = parsed.get("direction", "").upper()
            if direction not in ["BUY", "SELL"]:
                logger.warning(f"[PARSER] Invalid direction: {direction}")
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
                logger.warning("[PARSER] Invalid price values in ENTRY response")
                return {"type": "IGNORE"}

            # Ensure entry_high > entry_low
            if entry_high <= entry_low:
                logger.warning("[PARSER] entry_high must be > entry_low")
                return {"type": "IGNORE"}

            # Validate TP fields (at least one must be present)
            tp1 = parsed.get("tp1")
            tp2 = parsed.get("tp2")
            tp1_pips = parsed.get("tp1_pips")
            tp2_pips = parsed.get("tp2_pips")

            if tp1 is None and tp2 is None and tp1_pips is None and tp2_pips is None:
                logger.warning("[PARSER] ENTRY missing TP info")
                return {"type": "IGNORE"}

            # Normalize None values
            parsed["tp1"] = float(tp1) if tp1 is not None else None
            parsed["tp2"] = float(tp2) if tp2 is not None else None
            parsed["tp1_pips"] = int(tp1_pips) if tp1_pips is not None else None
            parsed["tp2_pips"] = int(tp2_pips) if tp2_pips is not None else None

            logger.debug(f"[PARSER] ENTRY details: {direction} @ {entry_low}-{entry_high} SL:{sl}")

        return parsed

    except json.JSONDecodeError as e:
        logger.error(f"[PARSER] Failed to parse Groq JSON response: {e}")
        return {"type": "IGNORE"}
    except requests.exceptions.Timeout:
        logger.error("[PARSER] Groq request timeout")
        return {"type": "IGNORE"}
    except requests.exceptions.RequestException as e:
        logger.error(f"[PARSER] Groq request failed: {e}")
        return {"type": "IGNORE"}
    except Exception as e:
        logger.error(f"[PARSER] Unexpected error: {e}")
        return {"type": "IGNORE"}
