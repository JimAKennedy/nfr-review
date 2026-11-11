import importlib
import logging

import pytest

import nfr_review.llm_integration as _llm_integration
from nfr_review.llm_integration import ProviderUnavailableError

# Never read the checkout's .env: it may hold a real API key, and the first
# create_llm_client() call (made at import time by the LLM rules) would copy
# it into os.environ for the rest of the session.
_llm_integration._ENV_LOADED = True

# Every module that binds ``create_llm_client`` at import time, plus
# ``nfr_review.llm_integration`` itself for the call-time imports in cli.py and
# arch_orchestrator.py. tests/test_llm_isolation.py fails if one is missing.
CREATE_LLM_CLIENT_SITES = (
    "nfr_review.llm_integration",
    "nfr_review.collectors.adr_derive",
    "nfr_review.output.summarize",
    "nfr_review.rules.adr_drift",
    "nfr_review.rules.pii_logging",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    # Registered here rather than in tests/regression/conftest.py: pytest only
    # honours addoption hooks from conftests loaded at startup, and with
    # testpaths = ["tests"] that is this file, not subdirectory conftests.
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Regenerate regression snapshot baselines instead of comparing.",
    )


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


class OfflineLlmClient:
    """Stand-in for an unconfigured LLM: reports unavailable and refuses calls."""

    available = False

    def call(self, prompt: str, *, max_tokens: int = 1024) -> str:
        raise ProviderUnavailableError("LLM calls are disabled in tests (tests/conftest.py)")


def _offline_create_llm_client(config: object = None) -> OfflineLlmClient:
    return OfflineLlmClient()


@pytest.fixture(autouse=True)
def offline_llm(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test off real LLM backends, whatever the environment holds.

    Patches ``create_llm_client`` where it is looked up, and the clients the
    registered LLM rules created at import. Tests that exercise the real
    factory opt out with ``@pytest.mark.real_llm_factory``; tests that need a
    fake with behaviour patch ``create_llm_client`` (or pass ``llm_client=``)
    themselves, which overrides this.
    """
    if request.node.get_closest_marker("real_llm_factory"):
        return
    from nfr_review.registry import rule_registry

    for module_name in CREATE_LLM_CLIENT_SITES:
        monkeypatch.setattr(
            importlib.import_module(module_name),
            "create_llm_client",
            _offline_create_llm_client,
        )
    for rule in rule_registry.all():
        if hasattr(rule, "_llm"):
            monkeypatch.setattr(rule, "_llm", OfflineLlmClient())
