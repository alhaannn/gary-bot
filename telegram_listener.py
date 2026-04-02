"""
Telegram Listener - Async Telegram channel monitor using Telethon

Monitors the specified channel for new messages and forwards text
to the message handler callback.
"""

import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    ApiIdInvalidError,
    FloodWaitError,
    PersistentTimestampOutdatedError
)

from logger import get_logger
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, TELEGRAM_CHANNEL, SESSION_FILE

logger = get_logger()


async def start_listener(message_handler_callback):
    """
    Start listening to the Telegram channel.

    Args:
        message_handler_callback: Async function that accepts (message_text: str)

    On first run, will prompt for phone verification code.
    Session is saved to disk for subsequent runs.
    """
    logger.info("[TELEGRAM] Initializing Telegram client...")

    # Create client
    client = TelegramClient(SESSION_FILE, TELEGRAM_API_ID, TELEGRAM_API_HASH)

    try:
        # Connect and start
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

        # Get channel entity
        logger.info(f"[TELEGRAM] Joining channel: {TELEGRAM_CHANNEL}")
        channel = await client.get_entity(TELEGRAM_CHANNEL)

        # Register message handler
        @client.on(events.NewMessage(chats=channel))
        async def on_new_message(event):
            """
            Handle new messages from the channel.
            Only process text messages; skip media-only posts.
            """
            try:
                # Extract message text
                message_text = event.message.message
                if message_text is None:
                    # Media-only or empty message
                    logger.debug("[TELEGRAM] Skipping media-only/empty message")
                    return

                message_text = message_text.strip()
                if not message_text:
                    logger.debug("[TELEGRAM] Skipping empty message")
                    return

                logger.info(f"[TELEGRAM] 📨 New message: {message_text[:80]}{'...' if len(message_text) > 80 else ''}")

                # Forward to handler (non-blocking to avoid lag)
                asyncio.create_task(handle_message_safe(message_text, message_handler_callback))

            except Exception as e:
                logger.error(f"[TELEGRAM] Error processing message: {e}")

        logger.info("[TELEGRAM] ✅ Listening for messages... (press Ctrl+C to stop)")
        await client.run_until_disconnected()

    except PhoneNumberInvalidError:
        logger.error("[TELEGRAM] ❌ Invalid phone number. Check TELEGRAM_PHONE in config.py")
    except ApiIdInvalidError:
        logger.error("[TELEGRAM] ❌ Invalid API ID/HASH. Check TELEGRAM_API_ID and TELEGRAM_API_HASH")
    except FloodWaitError as e:
        logger.error(f"[TELEGRAM] ❌ Flood wait: {e.seconds} seconds. Too many requests.")
    except PersistentTimestampOutdatedError as e:
        logger.warning(f"[TELEGRAM] ⚠️  Persistent timestamp outdated: {e}")
        logger.info("[TELEGRAM] Attempting to recreate session and reconnect...")
        # Delete the outdated session file and reconnect
        import os
        try:
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
                logger.info(f"[TELEGRAM] Removed outdated session file: {SESSION_FILE}")
        except Exception as remove_error:
            logger.error(f"[TELEGRAM] Failed to remove session file: {remove_error}")
        raise  # Re-raise to trigger reconnection
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


async def handle_message_safe(message_text: str, callback):
    """
    Wrapper to call callback with exception handling.
    Prevents a single message error from crashing the listener.
    """
    try:
        await callback(message_text)
    except Exception as e:
        logger.error(f"[TELEGRAM] Exception in message handler: {e}")
        import traceback
        logger.debug(f"[TELEGRAM] Traceback: {traceback.format_exc()}")
