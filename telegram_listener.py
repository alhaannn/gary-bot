"""
Telegram Listener - Async multi-channel Telegram monitor using Telethon

Monitors multiple channels simultaneously and forwards messages to the handler
with channel context. Includes strict timestamp validation and auto-reconnect
on PersistentTimestampOutdatedError.
"""

import asyncio
import logging
import os
import time
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
from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE,
    CHANNELS, USE_LEGACY_SINGLE_CHANNEL, LEGACY_CHANNEL,
    TIMESTAMP_THRESHOLD,
    MAX_RECONNECT_ATTEMPTS, RECONNECT_BASE_DELAY, RECONNECT_MAX_DELAY,
    RECONNECT_ELEVATED_THRESHOLD, RECONNECT_ELEVATED_DURATION
)

logger = get_logger()

# Global adaptive threshold state
_current_threshold = TIMESTAMP_THRESHOLD
_threshold_elevated_until = 0  # Unix timestamp when elevated threshold expires


def get_effective_threshold() -> int:
    """Get the current effective timestamp threshold, accounting for post-reconnect elevation."""
    global _current_threshold, _threshold_elevated_until
    now = time.time()
    if now < _threshold_elevated_until:
        remaining = int(_threshold_elevated_until - now)
        logger.debug(f"[TELEGRAM] Using elevated threshold: {_current_threshold}s (reverts in {remaining}s)")
        return _current_threshold
    elif _current_threshold != TIMESTAMP_THRESHOLD:
        # Elevation period expired, revert
        logger.info(f"[TELEGRAM] Reverting threshold from {_current_threshold}s to {TIMESTAMP_THRESHOLD}s")
        _current_threshold = TIMESTAMP_THRESHOLD
    return TIMESTAMP_THRESHOLD


def elevate_threshold():
    """Temporarily increase the timestamp threshold after a reconnect."""
    global _current_threshold, _threshold_elevated_until
    _current_threshold = RECONNECT_ELEVATED_THRESHOLD
    _threshold_elevated_until = time.time() + RECONNECT_ELEVATED_DURATION
    logger.info(f"[TELEGRAM] ⬆️ Elevated timestamp threshold to {_current_threshold}s for {RECONNECT_ELEVATED_DURATION}s")


def is_message_timestamp_valid(message, threshold_seconds: int = None) -> bool:
    """
    Validate that message timestamp is within threshold of current UTC time.

    Rejects messages that are too old (backlog) or too far in the future (desync).

    Args:
        message: Telethon Message object with .date attribute
        threshold_seconds: Max allowed age difference in seconds (auto-detected if None)

    Returns:
        True if message is fresh enough, False if outdated
    """
    if threshold_seconds is None:
        threshold_seconds = get_effective_threshold()

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


async def _run_listener(client, channels_to_listen, message_handler_callback):
    """
    Internal: Connect, authorize, register handlers, and run until disconnected.
    Raises PersistentTimestampOutdatedError if Telegram's internal state is stale.
    """
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
            logger.info(f"[TELEGRAM] Resolved channel: {channel_name} -> entity ID: {channel_entity.id}, title: {channel_entity.title}")

            # Create a handler with bound channel_name and entity
            def make_handler(name, entity):
                """Factory that returns an async handler with captured name and entity."""
                async def on_new_message(event):
                    try:
                        # DEBUG: Always log that event fired (use INFO to show on console)
                        logger.info(f"[{name}] 🔄 EVENT FIRED! Message ID: {event.message.id if event.message else 'None'}")
                        logger.debug(f"[{name}] Event details: chat_id={event.chat_id}, message_id={event.message.id if event.message else 'None'}")

                        # Timestamp validation first
                        message = event.message
                        if not message:
                            logger.debug(f"[{name}] ❌ No message object")
                            return

                        # Check timestamp (uses adaptive threshold)
                        effective_threshold = get_effective_threshold()
                        if not is_message_timestamp_valid(message, effective_threshold):
                            now = datetime.now(timezone.utc)
                            msg_date = message.date
                            if msg_date.tzinfo is None:
                                msg_date = msg_date.replace(tzinfo=timezone.utc)
                            diff = abs((now - msg_date).total_seconds())
                            logger.warning(f"[{name}] ⏰ Message timestamp validation FAILED: age={diff:.1f}s, threshold={effective_threshold}s")
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

            handler = make_handler(channel_name, channel_entity)
            # Register handler using chats= filter (Telethon handles entity ID matching correctly)
            client.add_event_handler(handler, events.NewMessage(
                chats=channel_entity,
                incoming=True
            ))
            channel_handlers.append((channel_name, handler))
            logger.info(f"[TELEGRAM] ✅ Registered handler for channel: {channel_name} ({channel_config['username']})")
        except Exception as e:
            logger.error(f"[TELEGRAM] Failed to register channel {channel_config.get('username')}: {e}")

    if not channel_handlers:
        logger.error("[TELEGRAM] No channel handlers registered! Exiting.")
        return

    logger.info("[TELEGRAM] ✅ Listening on all channels... (press Ctrl+C to stop)")

    # Run until disconnected - PersistentTimestampOutdatedError may occur here
    await client.run_until_disconnected()


async def start_multi_listener(message_handler_callback):
    """
    Start listening to multiple Telegram channels with auto-reconnect.

    Features:
    - Auto-reconnect on PersistentTimestampOutdatedError with exponential backoff
    - Session file cleanup on persistent errors to reset internal state
    - Adaptive timestamp threshold after reconnect to process backlogged messages
    - sequential_updates=True: ensures ordered message delivery per channel
    - incoming=True: only processes incoming messages (not outgoing/edits)

    Args:
        message_handler_callback: Async function that accepts (message_text: str, channel_name: str)
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

    session_file = "gary_bot_session"
    delay = RECONNECT_BASE_DELAY

    for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
        client = None
        try:
            logger.info(f"[TELEGRAM] Connection attempt {attempt}/{MAX_RECONNECT_ATTEMPTS}")

            # Create client with sequential_updates
            client = TelegramClient(
                session_file,
                TELEGRAM_API_ID,
                TELEGRAM_API_HASH,
                sequential_updates=True
            )

            await _run_listener(client, channels_to_listen, message_handler_callback)

            # If we get here, run_until_disconnected returned normally
            logger.info("[TELEGRAM] Listener exited normally")
            break

        except PersistentTimestampOutdatedError as e:
            logger.warning(f"[TELEGRAM] ⚠️ PersistentTimestampOutdatedError (attempt {attempt}/{MAX_RECONNECT_ATTEMPTS}): {e}")

            # Disconnect current client cleanly
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass

            if attempt >= MAX_RECONNECT_ATTEMPTS:
                logger.error("[TELEGRAM] ❌ Max reconnection attempts reached. Giving up.")
                raise

            # Delete the session file to force a fresh state
            session_path = f"{session_file}.session"
            if os.path.exists(session_path):
                try:
                    os.remove(session_path)
                    logger.info(f"[TELEGRAM] 🗑️ Deleted stale session file: {session_path}")
                except OSError as del_err:
                    logger.warning(f"[TELEGRAM] Could not delete session file: {del_err}")

            # Elevate timestamp threshold temporarily to accept backlogged messages
            elevate_threshold()

            # Exponential backoff
            logger.info(f"[TELEGRAM] ⏳ Reconnecting in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)

        except PhoneNumberInvalidError:
            logger.error("[TELEGRAM] ❌ Invalid phone number. Check TELEGRAM_PHONE in config.py")
            break
        except ApiIdInvalidError:
            logger.error("[TELEGRAM] ❌ Invalid API ID/HASH. Check TELEGRAM_API_ID and TELEGRAM_API_HASH")
            break
        except FloodWaitError as e:
            logger.error(f"[TELEGRAM] ❌ Flood wait: {e.seconds} seconds. Too many requests.")
            await asyncio.sleep(e.seconds)
        except KeyboardInterrupt:
            logger.info("[TELEGRAM] Shutting down...")
            break
        except ConnectionError as e:
            logger.error(f"[TELEGRAM] ❌ Connection error (attempt {attempt}/{MAX_RECONNECT_ATTEMPTS}): {e}")
            if attempt >= MAX_RECONNECT_ATTEMPTS:
                raise
            logger.info(f"[TELEGRAM] ⏳ Reconnecting in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)
        except Exception as e:
            logger.error(f"[TELEGRAM] ❌ Fatal error: {e}")
            raise
        finally:
            if client and client.is_connected():
                try:
                    await client.disconnect()
                except Exception:
                    pass


# Backward compatibility: keep the old function name for single-channel mode
async def start_listener(message_handler_callback):
    """Legacy wrapper for backward compatibility."""
    await start_multi_listener(message_handler_callback)
