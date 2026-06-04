"""
logger.py — Centralised logging setup for the Enterprise Knowledge Bot.

WHY LOGGING MATTERS:
  print() statements are fine for quick scripts.
  Production applications need STRUCTURED LOGGING because:
    - You can filter logs by severity (DEBUG, INFO, WARNING, ERROR)
    - Logs can be written to files AND the terminal simultaneously
    - Each log entry has a timestamp, module name, and line number
    - Cloud platforms (AWS CloudWatch, GCP Logging) consume structured logs
    - You can set log levels via environment variables without changing code

HOW COMPANIES USE THIS:
  Netflix, Uber, and every production system ships logs to centralised
  aggregators (Datadog, Splunk, ELK stack). This module is the foundation
  for that capability. For now we log to a file + console.
"""

import logging
import sys
from pathlib import Path


def get_logger(name: str) -> logging.Logger:
    """
    Create and return a configured logger for the given module name.

    Usage in any module:
        from src.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Processing document: %s", filename)
        logger.error("Failed to parse file: %s", exc)

    Args:
        name: Typically pass __name__ so the log shows which module emitted it.

    Returns:
        A configured Logger instance.
    """
    # Import here to avoid circular imports at module load time
    from src.config import LOG_LEVEL, LOG_FILE

    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if get_logger() is called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # -----------------------------------------------------------------------
    # Formatter — what each log line looks like
    # -----------------------------------------------------------------------
    # Example output:
    #   2024-01-15 14:32:01,452 | INFO     | src.ingestion.loader | Loaded 3 pages
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # -----------------------------------------------------------------------
    # Console handler — shows logs in your terminal
    # -----------------------------------------------------------------------
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # -----------------------------------------------------------------------
    # File handler — writes logs to disk for later inspection
    # -----------------------------------------------------------------------
    try:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        # Don't crash if we can't write logs — just warn on console
        logger.warning("Could not open log file %s: %s", LOG_FILE, e)

    return logger
