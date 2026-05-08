"""Clean Python — no anti-patterns should trigger here."""

import logging

logger = logging.getLogger(__name__)


def safe_parse(value):
    try:
        return int(value)
    except ValueError as e:
        logger.warning("Bad value: %s", e)
        raise
