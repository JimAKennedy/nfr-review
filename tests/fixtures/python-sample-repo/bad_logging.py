"""Stdout logging anti-patterns for testing PythonAstCollector."""

import logging
import sys

logger = logging.getLogger(__name__)


def uses_print():
    print("debug info")


def uses_stdout_write():
    sys.stdout.write("log message\n")


def uses_stderr_write():
    sys.stderr.write("error message\n")


def uses_proper_logging():
    """Uses logging module — should NOT be flagged by logging-to-stdout."""
    logger.info("This is proper logging")
    logger.error("This is a proper error")
