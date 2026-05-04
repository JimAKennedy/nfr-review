"""Tests for nfr_review.llm_client — ClaudeClient and serialize_evidence_bundle."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from nfr_review.llm_client import (
    ClaudeClient,
    LlmUnavailableError,
    serialize_evidence_bundle,
)

# ---------------------------------------------------------------------------
# ClaudeClient availability
# ---------------------------------------------------------------------------


class TestClaudeClientAvailability:
    def test_unavailable_when_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = ClaudeClient()
        assert client.available is False

    def test_unavailable_when_key_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        client = ClaudeClient()
        assert client.available is False

    def test_unavailable_when_key_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
        client = ClaudeClient()
        assert client.available is False

    @patch("nfr_review.llm_client.anthropic", create=True)
    def test_available_when_key_set(
        self, mock_anthropic: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        mock_anthropic.Anthropic.return_value = MagicMock()
        client = ClaudeClient()
        assert client.available is True


# ---------------------------------------------------------------------------
# ClaudeClient.analyze
# ---------------------------------------------------------------------------


class TestClaudeClientAnalyze:
    def test_raises_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = ClaudeClient()
        with pytest.raises(LlmUnavailableError):
            client.analyze("prompt", "evidence")

    @patch("nfr_review.llm_client.anthropic", create=True)
    def test_returns_response_text(
        self, mock_anthropic: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        mock_content_block = MagicMock()
        mock_content_block.text = "LLM says no PII found"
        mock_response = MagicMock()
        mock_response.content = [mock_content_block]

        mock_client_instance = MagicMock()
        mock_client_instance.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client_instance

        client = ClaudeClient()
        result = client.analyze("Check for PII", '{"files":["app.py"]}')

        assert result == "LLM says no PII found"
        mock_client_instance.messages.create.assert_called_once_with(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": 'Check for PII\n\n{"files":["app.py"]}',
                },
            ],
        )


# ---------------------------------------------------------------------------
# serialize_evidence_bundle
# ---------------------------------------------------------------------------


class TestSerializeEvidenceBundle:
    def test_under_limit(self) -> None:
        items = [{"file": "a.py", "kind": "pii"}, {"file": "b.py", "kind": "log"}]
        result = serialize_evidence_bundle(items)
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert len(result.encode()) <= 8192

    def test_truncates_to_fit(self) -> None:
        large_items = [{"data": "x" * 500} for _ in range(50)]
        result = serialize_evidence_bundle(large_items, max_bytes=1024)
        assert len(result.encode()) <= 1024
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) < 50

    def test_empty_list(self) -> None:
        result = serialize_evidence_bundle([])
        assert result == "[]"

    def test_does_not_mutate_input(self) -> None:
        items = [{"data": "x" * 500} for _ in range(50)]
        original_len = len(items)
        serialize_evidence_bundle(items, max_bytes=1024)
        assert len(items) == original_len

    def test_single_oversized_item(self) -> None:
        items = [{"data": "x" * 20000}]
        result = serialize_evidence_bundle(items, max_bytes=100)
        assert result == "[]"
        assert len(result.encode()) <= 100
