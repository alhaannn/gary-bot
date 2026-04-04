"""
Telegram Listener - Async multi-channel Telegram monitor using Telethon

Monitors multiple channels simultaneously and forwards messages to the handler
with channel context. Includes strict timestamp validation.
"""

import asyncio
import logging
from datetime import datetime, timezone
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    ApiIdInvalidError,
    FloodWaitError,
    PersistentTimestampOutdatedError
)

from logger import get_logger
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, CHANNELS, USE_LEGACY_SINGLE_CHANNEL, LEGACY_CHANNEL, TIMESTAMP_THRESHOLD

logger = get_logger()


def is_message_timestamp_valid(message, threshold_seconds: int = TIMESTAMP_THRESHOLD) -> bool:
    """
    Validate that message timestamp is within threshold of current UTC time.

    Rejects messages that are too old (backlog) or too far in the future (desync).

    Args:
        message: Telethon Message object with .date attribute
        threshold_seconds: Max allowed age difference in seconds (default from config)

    Returns:
        True if message is fresh enough, False if outdated
    """
    msg_date = message.date

    # Ensure message.date is timezone-aware (Telethon provides UTC)
    if msg_date.tzinfo is None:
        msg_date = msg_date.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    diff = abs((now - msg_date).total_seconds())

    if diff > threshold_seconds:
        logger.debug(f"[TELEGRAM] ⏰ Dropping outdated message: age={diff:.1f}s (> {threshold_seconds}s)")
        logger.debug(f"[TELEGRAM] ⏰ Message date: {msg_date}, Now: {now}")
        return False

    return True


async def start_multi_listener(message_handler_callback):
    """
    Start listening to multiple Telegram channels.

    Features:
    - sequential_updates=True: ensures ordered message delivery per channel
    - incoming=True: only processes incoming messages (not outgoing/edits)
    - func filter: ensures message exists
    - Timestamp validation: rejects stale/future messages before processing

    Args:
        message_handler_callback: Async function that accepts (message_text: str, channel_name: str)

    On first run, will prompt for phone verification code if needed.
    Session is saved to disk for subsequent runs.
    """
    logger.info("[TELEGRAM] Initializing multi-channel Telegram client...")

    # Determine which channels to listen
    if USE_LEGACY_SINGLE_CHANNEL:
        channels_to_listen = [{"name": "gary", "username": LEGACY_CHANNEL, "enabled": True}]
        logger.info("[TELEGRAM] Running in LEGACY single-channel mode")
    else:
        channels_to_listen = [c for c in CHANNELS if c["enabled"]]
        logger.info(f"[TELEGRAM] Multi-channel mode: {len(channels_to_listen)} channels enabled")

    if not channels_to_listen:
        logger.error("[TELEGRAM] No channels enabled! Check CHANNELS configuration.")
        return

    # Create client with sequential_updates
    client = TelegramClient(
        "gary_bot_session",
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
        sequential_updates=True
    )

    try:
        # Connect and authorize
        await client.connect()
        if not await client.is_user_authorized():
            logger.info("[TELEGRAM] First-time authorization required")
            await client.send_code_request(TELEGRAM_PHONE)
            try:
                code = input(f"[TELEGRAM] Enter verification code for {TELEGRAM_PHONE}: ")
                await client.sign_in(TELEGRAM_PHONE, code)
            except SessionPasswordNeededError:
                password = input("[TELEGRAM] Two-factor password required: ")
                await client.sign_in(password=password)
            logger.info("[TELEGRAM] Authorization successful, session saved")
        else:
            logger.info("[TELEGRAM] Using existing session")

        # Resolve all channel entities and register handlers
        channel_handlers = []
        for channel_config in channels_to_listen:
            try:
                channel_entity = await client.get_entity(channel_config["username"])
                channel_name = channel_config["name"]

                # Create a handler with bound channel_name using closure
                # Important: we must create the handler function and then register it
                def make_handler(name):
                    """Factory that returns an async handler with captured name."""
                    async def on_new_message(event):
                        try:
                            # DEBUG: Always log that event fired (use INFO to show on console)
                            logger.info(f"[{name}] 🔄 EVENT FIRED! Message ID: {event.message.id if event.message else 'None'}")

                            # Timestamp validation first
                            message = event.message
                            if not message:
                                logger.debug(f"[{name}] ❌ No message object")
                                return

                            # Check timestamp
                            if not is_message_timestamp_valid(message, TIMESTAMP_THRESHOLD):
                                now = datetime.now(timezone.utc)
                                msg_date = message.date
                                if msg_date.tzinfo is None:
                                    msg_date = msg_date.replace(tzinfo=timezone.utc)
                                diff = abs((now - msg_date).total_seconds())
                                logger.warning(f"[{name}] ⏰ Message timestamp validation FAILED: age={diff:.1f}s, threshold={TIMESTAMP_THRESHOLD}s")
                                logger.warning(f"[{name}] ⏰ Message date: {msg_date}, Now: {now}")
                                return

                            # Extract text
                            message_text = message.message
                            if message_text is None:
                                logger.debug(f"[{name}] Skipping media-only/empty message (no text)")
                                return

                            message_text = message_text.strip()
                            if not message_text:
                                logger.debug(f"[{name}] Skipping empty/whitespace-only message")
                                return

                            logger.info(f"[{name}] 📨 New message: {message_text[:80]}{'...' if len(message_text) > 80 else ''}")

                            # Call main handler with channel context
                            asyncio.create_task(message_handler_callback(message_text, name))
                        except Exception as e:
                            logger.error(f"[{name}] Error in message handler: {e}")
                            import traceback
                            logger.debug(f"[{name}] Traceback: {traceback.format_exc()}")
                    return on_new_message

                handler = make_handler(channel_name)
                client.on(events.NewMessage(
                    chats=channel_entity,
                    incoming=True,
                    func=lambda e: e.message
                ))(handler)
                channel_handlers.append((channel_name, handler))
                logger.info(f"[TELEGRAM] ✅ Registered handler for channel: {channel_name} ({channel_config['username']})")
            except Exception as e:
                logger.error(f"[TELEGRAM] Failed to register channel {channel_config.get('username')}: {e}")

        if not channel_handlers:
            logger.error("[TELEGRAM] No channel handlers registered! Exiting.")
            return

        logger.info("[TELEGRAM] ✅ Listening on all channels... (press Ctrl+C to stop)")
        await client.run_until_disconnected()

    except PhoneNumberInvalidError:
        logger.error("[TELEGRAM] ❌ Invalid phone number. Check TELEGRAM_PHONE in config.py")
    except ApiIdInvalidError:
        logger.error("[TELEGRAM] ❌ Invalid API ID/HASH. Check TELEGRAM_API_ID and TELEGRAM_API_HASH")
    except FloodWaitError as e:
        logger.error(f"[TELEGRAM] ❌ Flood wait: {e.seconds} seconds. Too many requests.")
    except PersistentTimestampOutdatedError as e:
        logger.warning(f"[TELEGRAM] ⚠️  Persistent timestamp outdated: {e}")
        logger.info("[TELEGRAM] This indicates client-server time desync or stale session. Reconnecting...")
        raise
    except KeyboardInterrupt:
        logger.info("[TELEGRAM] Shutting down...")
        await client.disconnect()
    except ConnectionError as e:
        logger.error(f"[TELEGRAM] ❌ Connection error: {e}")
        raise
    except Exception as e:
        logger.error(f"[TELEGRAM] ❌ Fatal error: {e}")
        raise
    finally:
        await client.disconnect()


# Backward compatibility: keep the old function name for single-channel mode
async def start_listener(message_handler_callback):
    """Legacy wrapper for backward compatibility."""
    await start_multi_listener(message_handler_callback)
