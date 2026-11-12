"""T2: the test suite never reaches a real LLM, whatever the environment holds.

The autouse ``offline_llm`` fixture in ``tests/conftest.py`` patches
``create_llm_client`` everywhere it is looked up and the clients that the
registered LLM rules built at import time. These tests set a dummy
``ANTHROPIC_API_KEY`` themselves, so they fail if that isolation is lost
even on a machine where the key is unset.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

import nfr_review
from nfr_review.registry import rule_registry
from tests.conftest import CREATE_LLM_CLIENT_SITES

_MODULE_LEVEL_IMPORT = re.compile(
    r"^from nfr_review\.llm_integration import (\([^)]*\)|[^\n]*)", re.MULTILINE
)


@pytest.mark.parametrize("module_name", CREATE_LLM_CLIENT_SITES)
def test_create_llm_client_is_offline_at_every_lookup_site(
    module_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    client = importlib.import_module(module_name).create_llm_client()
    assert client.available is False


def test_registered_rules_hold_offline_clients() -> None:
    llm_rules = [rule for rule in rule_registry.all() if hasattr(rule, "_llm")]
    assert {rule.id for rule in llm_rules} >= {
        "architectural-drift-from-adr",
        "pii-in-log-statements",
    }
    for rule in llm_rules:
        assert rule._llm.available is False, rule.id


def test_sites_cover_every_module_level_import() -> None:
    """A module that binds create_llm_client at import keeps the real function
    unless it is patched by name, so each one must be listed."""
    src_root = Path(nfr_review.__file__).parent
    importers: set[str] = set()
    for path in src_root.rglob("*.py"):
        for match in _MODULE_LEVEL_IMPORT.finditer(path.read_text(encoding="utf-8")):
            if re.search(r"\bcreate_llm_client\b", match.group(1)):
                importers.add(
                    ".".join(path.relative_to(src_root.parent).with_suffix("").parts)
                )
    assert "nfr_review.output.summarize" in importers  # the scan works
    assert importers <= set(CREATE_LLM_CLIENT_SITES)
