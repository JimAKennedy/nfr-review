"""Exception handling anti-patterns for testing PythonAstCollector."""

import logging

logger = logging.getLogger(__name__)


def bare_except_handler():
    try:
        risky()
    except:  # noqa: E722
        pass


def broad_except_silent():
    """Catches Exception but does not log or rethrow — silent swallow."""
    try:
        risky()
    except Exception:
        pass


def broad_base_exception_silent():
    """Catches BaseException silently."""
    try:
        risky()
    except BaseException:
        pass


def broad_except_with_logging():
    """Catches Exception but logs — should NOT trigger silent-catch."""
    try:
        risky()
    except Exception as e:
        logger.error("Caught: %s", e)


def broad_except_with_rethrow():
    """Catches Exception but rethrows — should NOT trigger silent-catch."""
    try:
        risky()
    except Exception:
        raise


def broad_except_with_print():
    """Catches Exception with print — has_logging should be True."""
    try:
        risky()
    except Exception as e:
        print(f"Error: {e}")


def specific_except():
    """Catches specific exception — not a broad catch."""
    try:
        int("abc")
    except ValueError as e:
        logger.warning("Bad value: %s", e)


def risky():
    raise RuntimeError("boom")
