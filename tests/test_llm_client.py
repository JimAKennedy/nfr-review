"""Tests for nfr_review.llm_client — backends, factory, retry, serialize."""

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
    LlmUnavailableError,
    OpenAICompatibleClient,
    _is_transient,
    _retry_with_backoff,
    create_llm_client,
    extract_json,
    serialize_evidence_bundle,
)
from nfr_review.protocols import LlmClient


@pytest.fixture(autouse=True)
def _default_api_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests default to the 'api' backend and bypass .env loading."""
    monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
    monkeypatch.delenv("NFR_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# .env auto-loading
# ---------------------------------------------------------------------------


class TestDotenvLoading:
    def test_loads_from_dotenv(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("NFR_LLM_PROVIDER=openai\n")
        monkeypatch.delenv("NFR_LLM_PROVIDER", raising=False)
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", False)
        with patch.object(
            _llm_mod.Path,
            "resolve",
            return_value=tmp_path / "src" / "nfr_review" / "llm_client.py",
        ):
            _llm_mod._load_dotenv_once()
        assert os.environ.get("NFR_LLM_PROVIDER") == "openai"

    def test_no_clobber_existing_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("NFR_LLM_PROVIDER=openai\n")
        monkeypatch.setenv("NFR_LLM_PROVIDER", "anthropic")
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", False)
        with patch.object(
            _llm_mod.Path,
            "resolve",
            return_value=tmp_path / "src" / "nfr_review" / "llm_client.py",
        ):
            _llm_mod._load_dotenv_once()
        assert os.environ["NFR_LLM_PROVIDER"] == "anthropic"


# ---------------------------------------------------------------------------
# _is_transient
# ---------------------------------------------------------------------------


class TestIsTransient:
    def test_429_is_transient(self) -> None:
        exc = Exception("rate limit")
        exc.status_code = 429  # type: ignore[attr-defined]
        assert _is_transient(exc) is True

    def test_503_is_transient(self) -> None:
        exc = Exception("service unavailable")
        exc.status_code = 503  # type: ignore[attr-defined]
        assert _is_transient(exc) is True

    def test_529_is_transient(self) -> None:
        exc = Exception("overloaded")
        exc.status_code = 529  # type: ignore[attr-defined]
        assert _is_transient(exc) is True

    def test_400_is_not_transient(self) -> None:
        exc = Exception("bad request")
        exc.status_code = 400  # type: ignore[attr-defined]
        assert _is_transient(exc) is False

    def test_timeout_error_is_transient(self) -> None:
        assert _is_transient(TimeoutError("timed out")) is True

    def test_connection_error_is_transient(self) -> None:
        assert _is_transient(ConnectionError("refused")) is True

    def test_class_name_ratelimit_is_transient(self) -> None:
        class RateLimitError(Exception):
            pass

        assert _is_transient(RateLimitError("too fast")) is True

    def test_generic_exception_is_not_transient(self) -> None:
        assert _is_transient(ValueError("bad value")) is False


# ---------------------------------------------------------------------------
# _retry_with_backoff
# ---------------------------------------------------------------------------


class TestRetryWithBackoff:
    def test_succeeds_on_first_try(self) -> None:
        result = _retry_with_backoff(lambda: "ok", max_retries=3)
        assert result == "ok"

    def test_retries_on_transient_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod.time, "sleep", lambda _: None)
        calls = []

        def flaky() -> str:
            calls.append(1)
            if len(calls) < 3:
                exc = Exception("overloaded")
                exc.status_code = 503  # type: ignore[attr-defined]
                raise exc
            return "recovered"

        result = _retry_with_backoff(flaky, max_retries=3, base_delay=0.01)
        assert result == "recovered"
        assert len(calls) == 3

    def test_raises_after_max_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod.time, "sleep", lambda _: None)

        def always_fail() -> str:
            exc = Exception("overloaded")
            exc.status_code = 503  # type: ignore[attr-defined]
            raise exc

        with pytest.raises(Exception, match="overloaded"):
            _retry_with_backoff(always_fail, max_retries=2, base_delay=0.01)

    def test_does_not_retry_non_transient(self) -> None:
        calls = []

        def permanent_fail() -> str:
            calls.append(1)
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            _retry_with_backoff(permanent_fail, max_retries=3)
        assert len(calls) == 1

    def test_does_not_retry_llm_unavailable(self) -> None:
        calls = []

        def unavailable() -> str:
            calls.append(1)
            raise LlmUnavailableError("no backend")

        with pytest.raises(LlmUnavailableError):
            _retry_with_backoff(unavailable, max_retries=3)
        assert len(calls) == 1

    def test_exponential_delays(self, monkeypatch: pytest.MonkeyPatch) -> None:
        delays: list[float] = []
        monkeypatch.setattr(_llm_mod.time, "sleep", lambda d: delays.append(d))
        call_count = 0

        def fail_twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                exc = Exception("overloaded")
                exc.status_code = 503  # type: ignore[attr-defined]
                raise exc
            return "ok"

        _retry_with_backoff(fail_twice, max_retries=3, base_delay=1.0, max_delay=16.0)
        assert len(delays) == 2
        assert delays[0] == pytest.approx(1.0)
        assert delays[1] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# AnthropicClient
# ---------------------------------------------------------------------------


class TestAnthropicClient:
    def test_unavailable_when_sdk_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "anthropic", None)
        client = AnthropicClient(model="test", api_key="key")
        assert client.available is False

    def test_unavailable_when_no_key(self) -> None:
        client = AnthropicClient(model="test", api_key="")
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
        monkeypatch.setattr(_llm_mod.time, "sleep", lambda _: None)
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

    @patch("nfr_review.llm_client.anthropic", create=True)
    def test_timeout_passed_to_sdk(self, mock_anthropic: MagicMock) -> None:
        mock_anthropic.Anthropic.return_value = MagicMock()
        AnthropicClient(model="test", api_key="key", timeout_seconds=60)
        mock_anthropic.Anthropic.assert_called_once_with(api_key="key", timeout=60.0)

    @patch("nfr_review.llm_client.anthropic", create=True)
    def test_retries_transient_sdk_error(
        self, mock_anthropic: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_llm_mod.time, "sleep", lambda _: None)
        mock_block = MagicMock()
        mock_block.text = "recovered"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        transient_exc = Exception("overloaded")
        transient_exc.status_code = 529  # type: ignore[attr-defined]

        mock_instance = MagicMock()
        mock_instance.messages.create.side_effect = [transient_exc, mock_response]
        mock_anthropic.Anthropic.return_value = mock_instance

        client = AnthropicClient(model="test", api_key="key")
        result = client.analyze("prompt", "evidence")
        assert result == "recovered"
        assert mock_instance.messages.create.call_count == 2


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

    @patch("nfr_review.llm_client.openai_mod", create=True)
    def test_available_when_sdk_present(self, mock_openai: MagicMock) -> None:
        mock_openai.OpenAI.return_value = MagicMock()
        client = OpenAICompatibleClient(model="gpt-4o", api_key="key")
        assert client.available is True

    @patch("nfr_review.llm_client.openai_mod", create=True)
    def test_analyze_returns_text(self, mock_openai: MagicMock) -> None:
        mock_message = MagicMock()
        mock_message.content = "OpenAI says hello"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_instance

        client = OpenAICompatibleClient(model="gpt-4o", api_key="key")
        result = client.analyze("prompt", "evidence")
        assert result == "OpenAI says hello"
        mock_instance.chat.completions.create.assert_called_once_with(
            model="gpt-4o",
            max_tokens=1024,
            messages=[{"role": "user", "content": "prompt\n\nevidence"}],
        )

    @patch("nfr_review.llm_client.openai_mod", create=True)
    def test_analyze_custom_max_tokens(self, mock_openai: MagicMock) -> None:
        mock_message = MagicMock()
        mock_message.content = "short"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_instance

        client = OpenAICompatibleClient(model="gpt-4o", api_key="key")
        client.analyze("prompt", "evidence", max_tokens=512)
        call_kwargs = mock_instance.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 512

    @patch("nfr_review.llm_client.openai_mod", create=True)
    def test_analyze_raises_on_null_content(self, mock_openai: MagicMock) -> None:
        mock_message = MagicMock()
        mock_message.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_instance

        client = OpenAICompatibleClient(model="gpt-4o", api_key="key")
        with pytest.raises(TypeError, match="no content"):
            client.analyze("prompt", "evidence")

    @patch("nfr_review.llm_client.openai_mod", create=True)
    def test_base_url_passed_to_sdk(self, mock_openai: MagicMock) -> None:
        mock_openai.OpenAI.return_value = MagicMock()
        OpenAICompatibleClient(
            model="llama3", api_key="ollama", base_url="http://localhost:11434/v1"
        )
        mock_openai.OpenAI.assert_called_once_with(
            api_key="ollama", base_url="http://localhost:11434/v1", timeout=120.0
        )

    @patch("nfr_review.llm_client.openai_mod", create=True)
    def test_no_base_url_omits_kwarg(self, mock_openai: MagicMock) -> None:
        mock_openai.OpenAI.return_value = MagicMock()
        OpenAICompatibleClient(model="gpt-4o", api_key="key")
        mock_openai.OpenAI.assert_called_once_with(api_key="key", timeout=120.0)

    @patch("nfr_review.llm_client.openai_mod", create=True)
    def test_timeout_passed_to_sdk(self, mock_openai: MagicMock) -> None:
        mock_openai.OpenAI.return_value = MagicMock()
        OpenAICompatibleClient(model="test", api_key="key", timeout_seconds=30)
        mock_openai.OpenAI.assert_called_once_with(api_key="key", timeout=30.0)


# ---------------------------------------------------------------------------
# ClaudeCliClient
# ---------------------------------------------------------------------------


class TestClaudeCliClient:
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

    def test_raises_on_nonzero_exit(self) -> None:
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeCliClient()
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="something broke"
        )
        with patch("nfr_review.llm_client.subprocess.run", return_value=mock_result):
            with pytest.raises(LlmUnavailableError, match="exited 1"):
                client.analyze("prompt", "evidence")

    def test_raises_on_timeout(self) -> None:
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeCliClient()
        with patch(
            "nfr_review.llm_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120),
        ):
            with pytest.raises(LlmUnavailableError, match="timed out"):
                client.analyze("prompt", "evidence")

    def test_custom_timeout(self) -> None:
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = ClaudeCliClient(timeout_seconds=60)
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        with patch("nfr_review.llm_client.subprocess.run", return_value=mock_result) as m:
            client.analyze("prompt", "evidence")
        assert m.call_args[1]["timeout"] == 60


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
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.base_url is None
        assert cfg.api_key_env_var == "ANTHROPIC_API_KEY"

    def test_resolve_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NFR_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("NFR_LLM_MODEL", raising=False)
        monkeypatch.delenv("NFR_LLM_BASE_URL", raising=False)
        cfg = LlmConfig()
        resolved = cfg.resolve()
        assert resolved.provider == "anthropic"
        assert resolved.model == "claude-sonnet-4-6"

    def test_resolve_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_PROVIDER", "openai")
        monkeypatch.setenv("NFR_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("NFR_LLM_BASE_URL", "http://localhost:11434/v1")
        cfg = LlmConfig()
        resolved = cfg.resolve()
        assert resolved.provider == "openai"
        assert resolved.model == "gpt-4o"
        assert resolved.base_url == "http://localhost:11434/v1"
        assert resolved.api_key_env_var == "OPENAI_API_KEY"

    def test_resolve_api_key_env_var_follows_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NFR_LLM_PROVIDER", "openai")
        monkeypatch.delenv("NFR_LLM_MODEL", raising=False)
        monkeypatch.delenv("NFR_LLM_BASE_URL", raising=False)
        cfg = LlmConfig()
        resolved = cfg.resolve()
        assert resolved.api_key_env_var == "OPENAI_API_KEY"

    def test_resolve_api_key_env_var_unchanged_for_anthropic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NFR_LLM_PROVIDER", "anthropic")
        cfg = LlmConfig()
        resolved = cfg.resolve()
        assert resolved.api_key_env_var == "ANTHROPIC_API_KEY"

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
# Factory — OpenAI-specific paths
# ---------------------------------------------------------------------------


class TestCreateLlmClientOpenAI:
    def test_openai_with_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = LlmConfig(
            provider="openai",
            model="llama3",
            api_key_env_var="OPENAI_API_KEY",
            base_url="http://localhost:11434/v1",
        )
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAICompatibleClient)
        assert client._model == "llama3"

    def test_openai_env_override_from_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.setenv("NFR_LLM_PROVIDER", "openai")
        monkeypatch.setenv("NFR_LLM_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        cfg = LlmConfig(provider="anthropic")
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAICompatibleClient)
        assert client._model == "gpt-4o-mini"

    def test_openai_missing_key_still_creates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = LlmConfig(provider="openai", api_key_env_var="OPENAI_API_KEY")
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAICompatibleClient)


# ---------------------------------------------------------------------------
# Cross-backend integration: config YAML → load_config → create_llm_client
# ---------------------------------------------------------------------------


class TestCrossBackendConfigIntegration:
    """Verify the full config → factory → client flow for each provider."""

    def test_cross_backend_anthropic_from_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.delenv("NFR_LLM_PROVIDER", raising=False)
        cfg_file = tmp_path / "nfr-review.yaml"
        cfg_file.write_text(
            "version: 1\nllm:\n  provider: anthropic\n  model: claude-haiku-4-5-20251001\n"
        )
        from nfr_review.config import load_config

        config = load_config(cfg_file)
        client = create_llm_client(config.llm)
        assert isinstance(client, AnthropicClient)
        assert client._model == "claude-haiku-4-5-20251001"

    def test_cross_backend_openai_from_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        monkeypatch.delenv("NFR_LLM_PROVIDER", raising=False)
        cfg_file = tmp_path / "nfr-review.yaml"
        cfg_file.write_text(
            "version: 1\n"
            "llm:\n"
            "  provider: openai\n"
            "  model: llama3\n"
            "  base_url: http://localhost:11434/v1\n"
            "  api_key_env_var: OPENAI_API_KEY\n"
        )
        from nfr_review.config import load_config

        config = load_config(cfg_file)
        client = create_llm_client(config.llm)
        assert isinstance(client, OpenAICompatibleClient)
        assert client._model == "llama3"

    def test_cross_backend_claude_cli_from_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.delenv("NFR_LLM_PROVIDER", raising=False)
        cfg_file = tmp_path / "nfr-review.yaml"
        cfg_file.write_text("version: 1\nllm:\n  provider: claude-cli\n")
        from nfr_review.config import load_config

        config = load_config(cfg_file)
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = create_llm_client(config.llm)
        assert isinstance(client, ClaudeCliClient)
        assert client.available is True

    def test_cross_backend_env_overrides_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
        monkeypatch.setenv("NFR_LLM_PROVIDER", "claude-cli")
        cfg_file = tmp_path / "nfr-review.yaml"
        cfg_file.write_text("version: 1\nllm:\n  provider: anthropic\n")
        from nfr_review.config import load_config

        config = load_config(cfg_file)
        with patch("nfr_review.llm_client.shutil.which", return_value="/usr/bin/claude"):
            client = create_llm_client(config.llm)
        assert isinstance(client, ClaudeCliClient)


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
        result = extract_json(text)
        assert result == {"verdict": "pass", "score": 42}

    def test_prose_wrapped_array(self) -> None:
        text = 'The results are:\n[{"index": 0, "is_pii": true}]\nEnd of response.'
        result = extract_json(text, expect="array")
        assert result == [{"index": 0, "is_pii": True}]

    def test_returns_none_on_no_json(self) -> None:
        assert extract_json("This is not JSON at all") is None

    def test_returns_none_on_wrong_type(self) -> None:
        assert extract_json("[1, 2]", expect="object") is None

    def test_object_not_returned_for_array_expect(self) -> None:
        assert extract_json('{"key": "val"}', expect="array") is None

    def test_any_accepts_object(self) -> None:
        result = extract_json('{"k": 1}', expect="any")
        assert result == {"k": 1}

    def test_any_accepts_array(self) -> None:
        result = extract_json("[1]", expect="any")
        assert result == [1]

    def test_leading_trailing_whitespace(self) -> None:
        assert extract_json('  \n{"a": 1}\n  ') == {"a": 1}

    def test_nested_braces(self) -> None:
        text = 'prefix {"outer": {"inner": 1}} suffix'
        result = extract_json(text)
        assert result == {"outer": {"inner": 1}}

    def test_code_fence_with_surrounding_prose(self) -> None:
        text = (
            "I've analyzed the codebase. Here are the results:\n\n"
            "```json\n"
            '{"verdict": "conditional", "score": 65}\n'
            "```\n\n"
            "Let me know if you need more detail."
        )
        result = extract_json(text)
        assert result == {"verdict": "conditional", "score": 65}
