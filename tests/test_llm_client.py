"""Tests for nfr_review.llm_client — ClaudeClient and serialize_evidence_bundle."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import nfr_review.llm_client as _llm_mod
from nfr_review.llm_client import (
    LLM_MODEL,
    ClaudeClient,
    LlmUnavailableError,
    serialize_evidence_bundle,
)


@pytest.fixture(autouse=True)
def _default_api_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests default to the 'api' backend and bypass .env loading."""
    monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
    monkeypatch.setenv("NFR_LLM_BACKEND", "api")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# ClaudeClient availability — API backend
# ---------------------------------------------------------------------------


class TestClaudeClientAvailability:
    def test_unavailable_when_no_key(self) -> None:
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
# .env auto-loading
# ---------------------------------------------------------------------------


class TestDotenvLoading:
    def test_loads_backend_from_dotenv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("NFR_LLM_BACKEND=claude-cli\n")
        monkeypatch.delenv("NFR_LLM_BACKEND", raising=False)
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", False)
        with patch.object(
            _llm_mod.Path,
            "resolve",
            return_value=tmp_path / "src" / "nfr_review" / "llm_client.py",
        ):
            with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
                _llm_mod._load_dotenv_once()
        assert os.environ.get("NFR_LLM_BACKEND") == "claude-cli"

    def test_no_clobber_existing_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("NFR_LLM_BACKEND=api\n")
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", False)
        with patch.object(
            _llm_mod.Path,
            "resolve",
            return_value=tmp_path / "src" / "nfr_review" / "llm_client.py",
        ):
            _llm_mod._load_dotenv_once()
        assert os.environ["NFR_LLM_BACKEND"] == "claude-cli"


# ---------------------------------------------------------------------------
# ClaudeClient availability — CLI backend
# ---------------------------------------------------------------------------


class TestClaudeClientCliAvailability:
    def test_available_when_cli_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeClient()
        assert client.available is True

    def test_unavailable_when_cli_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        with patch("nfr_review.llm_client.shutil.which", return_value=None):
            client = ClaudeClient()
        assert client.available is False

    def test_does_not_need_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeClient()
        assert client.available is True
        assert client._client is None

    def test_unknown_backend_falls_back_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_BACKEND", "bogus")
        client = ClaudeClient()
        assert client._backend == "api"
        assert client.available is False


# ---------------------------------------------------------------------------
# ClaudeClient.analyze — API backend
# ---------------------------------------------------------------------------


class TestClaudeClientAnalyze:
    def test_raises_when_unavailable(self) -> None:
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
            model=LLM_MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": 'Check for PII\n\n{"files":["app.py"]}',
                },
            ],
        )


# ---------------------------------------------------------------------------
# ClaudeClient.analyze — CLI backend
# ---------------------------------------------------------------------------


class TestClaudeClientAnalyzeCli:
    def test_raises_when_cli_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        with patch("nfr_review.llm_client.shutil.which", return_value=None):
            client = ClaudeClient()
        with pytest.raises(LlmUnavailableError, match="claude CLI not found"):
            client.analyze("prompt", "evidence")

    def test_returns_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeClient()

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="  analysis result\n", stderr=""
        )
        with patch(
            "nfr_review.llm_client.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = client.analyze("Check PII", '{"files":[]}')

        assert result == "analysis result"
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "/usr/bin/claude"
        assert "-p" in cmd
        assert "--output-format" in cmd

    def test_raises_on_nonzero_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeClient()

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="something broke"
        )
        with patch("nfr_review.llm_client.subprocess.run", return_value=mock_result):
            with pytest.raises(LlmUnavailableError, match="exited 1"):
                client.analyze("prompt", "evidence")

    def test_raises_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeClient()

        with patch(
            "nfr_review.llm_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120),
        ):
            with pytest.raises(LlmUnavailableError, match="timed out"):
                client.analyze("prompt", "evidence")


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
