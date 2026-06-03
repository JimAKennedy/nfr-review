"""Tests for nfr_review.llm_client — backends, factory, serialize."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import nfr_review.llm_client as _llm_mod
from nfr_review.config import LlmConfig
from nfr_review.llm_client import (
    AnthropicClient,
    ClaudeCliClient,
    ClaudeClient,
    LlmUnavailableError,
    OpenAICompatibleClient,
    create_llm_client,
    serialize_evidence_bundle,
)
from nfr_review.protocols import LlmClient


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
# Optional dependency — anthropic not installed
# ---------------------------------------------------------------------------


class TestAnthropicOptional:
    def test_unavailable_when_sdk_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "anthropic", None)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        client = ClaudeClient()
        assert client.available is False

    def test_analyze_raises_when_sdk_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "anthropic", None)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        client = ClaudeClient()
        with pytest.raises(LlmUnavailableError, match="anthropic SDK not installed"):
            client.analyze("prompt", "evidence")

    def test_cli_backend_works_without_sdk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "anthropic", None)
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
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
            model="claude-sonnet-4-6-20250514",
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


# ---------------------------------------------------------------------------
# LlmClient protocol conformance
# ---------------------------------------------------------------------------


class TestLlmClientProtocol:
    def test_claude_client_satisfies_protocol(self) -> None:
        assert isinstance(ClaudeClient(), LlmClient)

    def test_anthropic_client_satisfies_protocol(self) -> None:
        client = AnthropicClient(model="test", api_key="k")
        assert isinstance(client, LlmClient)

    def test_claude_cli_client_satisfies_protocol(self) -> None:
        with patch("nfr_review.llm_client.shutil.which", return_value=None):
            client = ClaudeCliClient()
        assert isinstance(client, LlmClient)

    def test_openai_client_satisfies_protocol(self) -> None:
        client = OpenAICompatibleClient(model="test", api_key="k")
        assert isinstance(client, LlmClient)


# ---------------------------------------------------------------------------
# LlmConfig
# ---------------------------------------------------------------------------


class TestLlmConfig:
    def test_defaults(self) -> None:
        cfg = LlmConfig()
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-sonnet-4-6-20250514"
        assert cfg.base_url is None
        assert cfg.api_key_env_var == "ANTHROPIC_API_KEY"

    def test_resolve_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NFR_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("NFR_LLM_MODEL", raising=False)
        monkeypatch.delenv("NFR_LLM_BASE_URL", raising=False)
        cfg = LlmConfig()
        resolved = cfg.resolve()
        assert resolved.provider == "anthropic"
        assert resolved.model == "claude-sonnet-4-6-20250514"

    def test_resolve_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_PROVIDER", "openai")
        monkeypatch.setenv("NFR_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("NFR_LLM_BASE_URL", "http://localhost:11434/v1")
        cfg = LlmConfig()
        resolved = cfg.resolve()
        assert resolved.provider == "openai"
        assert resolved.model == "gpt-4o"
        assert resolved.base_url == "http://localhost:11434/v1"

    def test_resolve_returns_self_when_no_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NFR_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("NFR_LLM_MODEL", raising=False)
        monkeypatch.delenv("NFR_LLM_BASE_URL", raising=False)
        cfg = LlmConfig()
        resolved = cfg.resolve()
        assert resolved is cfg

    def test_invalid_provider_rejected(self) -> None:
        with pytest.raises(ValueError, match="Input should be"):
            LlmConfig(provider="bogus")  # type: ignore[arg-type]

    def test_custom_api_key_env_var(self) -> None:
        cfg = LlmConfig(provider="openai", api_key_env_var="OPENAI_API_KEY")
        assert cfg.api_key_env_var == "OPENAI_API_KEY"


# ---------------------------------------------------------------------------
# create_llm_client factory
# ---------------------------------------------------------------------------


class TestCreateLlmClient:
    def test_default_creates_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.delenv("NFR_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = create_llm_client()
        assert isinstance(client, AnthropicClient)

    def test_anthropic_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        cfg = LlmConfig(provider="anthropic", model="claude-haiku-4-5-20251001")
        client = create_llm_client(cfg)
        assert isinstance(client, AnthropicClient)
        assert client._model == "claude-haiku-4-5-20251001"

    def test_openai_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        cfg = LlmConfig(
            provider="openai",
            model="gpt-4o",
            api_key_env_var="OPENAI_API_KEY",
            base_url="http://localhost:11434/v1",
        )
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAICompatibleClient)
        assert client._model == "gpt-4o"

    def test_claude_cli_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        cfg = LlmConfig(provider="claude-cli")
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = create_llm_client(cfg)
        assert isinstance(client, ClaudeCliClient)
        assert client.available is True

    def test_env_override_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.setenv("NFR_LLM_PROVIDER", "claude-cli")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = LlmConfig(provider="anthropic")
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = create_llm_client(cfg)
        assert isinstance(client, ClaudeCliClient)


# ---------------------------------------------------------------------------
# AnthropicClient
# ---------------------------------------------------------------------------


class TestAnthropicClientNew:
    def test_unavailable_when_sdk_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "anthropic", None)
        client = AnthropicClient(model="test", api_key="key")
        assert client.available is False

    def test_raises_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "anthropic", None)
        client = AnthropicClient(model="test", api_key="key")
        with pytest.raises(LlmUnavailableError, match="anthropic SDK not installed"):
            client.analyze("prompt", "evidence")

    @patch("nfr_review.llm_client.anthropic", create=True)
    def test_analyze_returns_text(
        self, mock_anthropic: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_block = MagicMock()
        mock_block.text = "result text"
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_instance = MagicMock()
        mock_instance.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_instance

        client = AnthropicClient(model="claude-test", api_key="key")
        result = client.analyze("prompt", "evidence")
        assert result == "result text"
        mock_instance.messages.create.assert_called_once_with(
            model="claude-test",
            max_tokens=1024,
            messages=[{"role": "user", "content": "prompt\n\nevidence"}],
        )


# ---------------------------------------------------------------------------
# ClaudeCliClient
# ---------------------------------------------------------------------------


class TestClaudeCliClientNew:
    def test_unavailable_when_missing(self) -> None:
        with patch("nfr_review.llm_client.shutil.which", return_value=None):
            client = ClaudeCliClient()
        assert client.available is False

    def test_available_when_found(self) -> None:
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeCliClient()
        assert client.available is True

    def test_raises_when_unavailable(self) -> None:
        with patch("nfr_review.llm_client.shutil.which", return_value=None):
            client = ClaudeCliClient()
        with pytest.raises(LlmUnavailableError, match="claude CLI not found"):
            client.analyze("prompt", "evidence")

    def test_returns_stdout(self) -> None:
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeCliClient()
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="  result\n", stderr=""
        )
        with patch("nfr_review.llm_client.subprocess.run", return_value=mock_result):
            result = client.analyze("prompt", "evidence")
        assert result == "result"


# ---------------------------------------------------------------------------
# OpenAICompatibleClient
# ---------------------------------------------------------------------------


class TestOpenAICompatibleClient:
    def test_unavailable_when_sdk_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "openai_mod", None)
        client = OpenAICompatibleClient(model="gpt-4o", api_key="key")
        assert client.available is False

    def test_raises_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "openai_mod", None)
        client = OpenAICompatibleClient(model="gpt-4o", api_key="key")
        with pytest.raises(LlmUnavailableError, match="openai SDK not installed"):
            client.analyze("prompt", "evidence")
