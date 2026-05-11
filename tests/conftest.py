import logging

import pytest


@pytest.fixture(autouse=True)
def _reset_nfr_review_logger():
    """Reset the nfr_review logger after each test to prevent cross-test pollution."""
    yield
    logger = logging.getLogger("nfr_review")
    logger.handlers.clear()
    logger.setLevel(logging.WARNING)
    logger.propagate = True
