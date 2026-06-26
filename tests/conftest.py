import logging

import pytest


@pytest.fixture(scope="session", autouse=True)
def _load_all_registrations():
    """Ensure all rules and collectors are registered before any test runs.

    Without this, pytest-xdist workers that happen to execute test_registry.py
    first save an empty registry snapshot (rules haven't been imported yet) and
    restore empty — leaving subsequent tests on the same worker with no rules.
    """
    import nfr_review.collectors  # noqa: F401
    import nfr_review.rules  # noqa: F401


@pytest.fixture(autouse=True)
def _reset_nfr_review_logger():
    """Reset the nfr_review logger after each test to prevent cross-test pollution."""
    yield
    logger = logging.getLogger("nfr_review")
    logger.handlers.clear()
    logger.setLevel(logging.WARNING)
    logger.propagate = True
