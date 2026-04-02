"""
Logging configuration for GaryBot

Provides a single configured logger instance with:
- Console output (INFO and above)
- File output (DEBUG and above) with timestamps
"""

import logging
import sys
from datetime import datetime

# Module-level logger instance (configured on first import)
_logger = None


def setup_logger():
    """
    Configure the logger with console and file handlers.
    Format: YYYY-MM-DD HH:MM:SS [LEVEL] message
    """
    global _logger

    if _logger is not None:
        return _logger

    logger = logging.getLogger("gary_bot")
    logger.setLevel(logging.DEBUG)

    # Prevent adding handlers multiple times
    if logger.handlers:
        _logger = logger
        return logger

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler (INFO+)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (DEBUG+)
    from config import LOG_FILE
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _logger = logger
    return logger


def get_logger():
    """Get the configured logger instance."""
    if _logger is None:
        return setup_logger()
    return _logger
