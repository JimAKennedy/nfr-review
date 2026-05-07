"""Clean Python patterns — no anti-patterns should be detected here."""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def specific_exception_with_logging():
    try:
        Path("/nonexistent").read_text()
    except FileNotFoundError as e:
        logger.warning("File not found: %s", e)


def immutable_defaults(timeout: int = 30, prefix: str = "default"):
    return f"{prefix}:{timeout}"


async def tracked_task():
    task = asyncio.create_task(worker())
    result = await task
    return result


async def worker():
    await asyncio.sleep(0.1)
    return 42


def uses_logging_module(data: dict | None = None):
    logger.info("Processing data")
    if data:
        logger.debug("Data keys: %s", list(data.keys()))
