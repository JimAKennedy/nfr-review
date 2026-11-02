"""Tests for nfr_review.llm_integration — the nfr-review / ai-tooling boundary."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from nfr_review.llm_integration import (
    ProviderUnavailableError,
    create_llm_client,
    extract_json,
    run_analysis,
    serialize_bundle,
)

# ---------------------------------------------------------------------------
# create_llm_client — stub behaviour when ai-tooling absent
# ---------------------------------------------------------------------------


class TestCreateLlmClientStub:
    """When ai-tooling is not installed the stub must be importable and inert."""

    def test_returns_unavailable_client_when_no_ai_tooling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import nfr_review.llm_integration as _mod

        monkeypatch.setattr(_mod, "_AI_TOOLING_AVAILABLE", False)
        # Re-import stub path by calling the module-level stub directly
        client = (
            _mod._UnavailableClient()
            if hasattr(_mod, "_UnavailableClient")
            else create_llm_client()
        )
        assert client.available is False

    def test_stub_call_raises_provider_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import nfr_review.llm_integration as _mod

        if not hasattr(_mod, "_UnavailableClient"):
            pytest.skip("ai-tooling is installed; stub path not active")
        client = _mod._UnavailableClient()
        with pytest.raises(ProviderUnavailableError):
            client.call("hello")


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_direct_object(self) -> None:
        assert extract_json('{"key": "value"}') == {"key": "value"}

    def test_direct_array(self) -> None:
        assert extract_json("[1, 2]", expect="array") == [1, 2]

    def test_code_fenced_object(self) -> None:
        text = '```json\n{"verdict": "pass"}\n```'
        assert extract_json(text) == {"verdict": "pass"}

    def test_code_fence_without_json_tag(self) -> None:
        text = '```\n{"verdict": "pass"}\n```'
        assert extract_json(text) == {"verdict": "pass"}

    def test_prose_wrapped_object(self) -> None:
        text = 'Here is the analysis:\n\n{"verdict": "pass", "score": 42}\n\nHope that helps!'
        assert extract_json(text) == {"verdict": "pass", "score": 42}

    def test_prose_wrapped_array(self) -> None:
        text = 'The results are:\n[{"index": 0, "is_pii": true}]\nEnd.'
        assert extract_json(text, expect="array") == [{"index": 0, "is_pii": True}]

    def test_returns_none_on_no_json(self) -> None:
        assert extract_json("This is not JSON at all") is None

    def test_returns_none_on_wrong_type(self) -> None:
        assert extract_json("[1, 2]", expect="object") is None

    def test_any_accepts_object(self) -> None:
        assert extract_json('{"k": 1}', expect="any") == {"k": 1}

    def test_any_accepts_array(self) -> None:
        assert extract_json("[1]", expect="any") == [1]

    def test_nested_braces(self) -> None:
        assert extract_json('prefix {"outer": {"inner": 1}} suffix') == {"outer": {"inner": 1}}


# ---------------------------------------------------------------------------
# serialize_bundle
# ---------------------------------------------------------------------------


class TestSerializeBundle:
    def test_under_limit(self) -> None:
        items = [{"file": "a.py", "kind": "pii"}, {"file": "b.py", "kind": "log"}]
        result = serialize_bundle(items)
        assert len(json.loads(result)) == 2
        assert len(result.encode()) <= 8192

    def test_truncates_to_fit(self) -> None:
        large_items = [{"data": "x" * 500} for _ in range(50)]
        result = serialize_bundle(large_items, max_bytes=1024)
        assert len(result.encode()) <= 1024
        assert len(json.loads(result)) < 50

    def test_empty_list(self) -> None:
        assert serialize_bundle([]) == "[]"

    def test_does_not_mutate_input(self) -> None:
        items = [{"data": "x" * 500} for _ in range(50)]
        original_len = len(items)
        serialize_bundle(items, max_bytes=1024)
        assert len(items) == original_len

    def test_single_oversized_item(self) -> None:
        result = serialize_bundle([{"data": "x" * 20000}], max_bytes=100)
        assert result == "[]"


# ---------------------------------------------------------------------------
# run_analysis
# ---------------------------------------------------------------------------


class TestRunAnalysis:
    def test_calls_client_with_combined_prompt(self) -> None:
        client = MagicMock()
        client.call.return_value = "analysis result"
        result = run_analysis(client, "my prompt", [{"file": "a.py"}])
        assert result == "analysis result"
        call_args = client.call.call_args
        combined = call_args[0][0]
        assert combined.startswith("my prompt")
        assert "a.py" in combined

    def test_passes_max_tokens(self) -> None:
        client = MagicMock()
        client.call.return_value = "ok"
        run_analysis(client, "prompt", [], max_tokens=512)
        assert client.call.call_args[1]["max_tokens"] == 512
