"""Tests for nfr-review's LLM configuration layer.

Covers ``LlmConfig`` env-var resolution, ``.env`` loading, and the mapping
from ``LlmConfig`` onto ai-tooling's ``ProviderConfig`` performed by
``create_llm_client``. Provider/transport behaviour (retries, SDK calls) is
ai-tooling's responsibility and is tested there.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import nfr_review.llm_integration as _llm_mod
from nfr_review.config import LlmConfig

_NFR_ENV = (
    "NFR_LLM_PROVIDER",
    "NFR_LLM_BACKEND",
    "NFR_LLM_MODEL",
    "NFR_LLM_BASE_URL",
    "AI_TOOLING_PROVIDER",
    "AI_TOOLING_MODEL",
    "AI_TOOLING_BASE_URL",
)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_llm_mod, "_ENV_LOADED", True)
    for var in _NFR_ENV:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# LlmConfig.resolve
# ---------------------------------------------------------------------------


class TestLlmConfig:
    def test_defaults(self) -> None:
        cfg = LlmConfig()
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.base_url is None
        assert cfg.api_key_env_var == "ANTHROPIC_API_KEY"

    def test_resolve_returns_self_when_no_env(self) -> None:
        cfg = LlmConfig()
        assert cfg.resolve() is cfg

    def test_resolve_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NFR_LLM_PROVIDER", "openai")
        monkeypatch.setenv("NFR_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("NFR_LLM_BASE_URL", "http://localhost:11434/v1")
        resolved = LlmConfig().resolve()
        assert resolved.provider == "openai"
        assert resolved.model == "gpt-4o"
        assert resolved.base_url == "http://localhost:11434/v1"
        assert resolved.api_key_env_var == "OPENAI_API_KEY"

    def test_resolve_api_key_env_var_unchanged_for_anthropic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NFR_LLM_PROVIDER", "anthropic")
        assert LlmConfig().resolve().api_key_env_var == "ANTHROPIC_API_KEY"

    def test_deprecated_backend_env_maps_api_to_anthropic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NFR_LLM_BACKEND", "api")
        monkeypatch.setenv("NFR_LLM_MODEL", "claude-haiku-4-5")
        resolved = LlmConfig(provider="claude-cli").resolve()
        assert resolved.provider == "anthropic"

    def test_provider_env_wins_over_deprecated_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NFR_LLM_PROVIDER", "openai")
        monkeypatch.setenv("NFR_LLM_BACKEND", "claude-cli")
        assert LlmConfig().resolve().provider == "openai"

    def test_invalid_provider_rejected(self) -> None:
        with pytest.raises(ValueError, match="Input should be"):
            LlmConfig(provider="bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------


class TestDotenvLoading:
    def _load_from(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_llm_mod, "_ENV_LOADED", False)
        fake_module = tmp_path / "src" / "nfr_review" / "llm_integration.py"
        with patch.object(_llm_mod.Path, "resolve", return_value=fake_module):
            _llm_mod._load_dotenv_once()

    def test_loads_from_dotenv(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("# comment\n\nNFR_LLM_PROVIDER=openai\n")
        self._load_from(tmp_path, monkeypatch)
        assert os.environ.get("NFR_LLM_PROVIDER") == "openai"

    def test_no_clobber_existing_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / ".env").write_text("NFR_LLM_PROVIDER=openai\n")
        monkeypatch.setenv("NFR_LLM_PROVIDER", "anthropic")
        self._load_from(tmp_path, monkeypatch)
        assert os.environ["NFR_LLM_PROVIDER"] == "anthropic"

    def test_loads_only_once(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("NFR_LLM_MODEL=first\n")
        self._load_from(tmp_path, monkeypatch)
        monkeypatch.delenv("NFR_LLM_MODEL")
        (tmp_path / ".env").write_text("NFR_LLM_MODEL=second\n")
        _llm_mod._load_dotenv_once()  # already loaded: no-op
        assert "NFR_LLM_MODEL" not in os.environ


# ---------------------------------------------------------------------------
# create_llm_client -> ai_tooling.ProviderConfig mapping
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_provider_config(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    pytest.importorskip(
        "ai_tooling", reason="mapping only exists when ai-tooling is installed"
    )
    captured: list[Any] = []

    def _fake_create_session(cfg: Any = None) -> object:
        captured.append(cfg)
        return object()

    monkeypatch.setattr(_llm_mod, "create_session", _fake_create_session)
    return captured


class TestCreateLlmClientMapping:
    def test_default_uses_nfr_defaults_not_ai_tooling_defaults(
        self, captured_provider_config: list[Any]
    ) -> None:
        _llm_mod.create_llm_client()
        (cfg,) = captured_provider_config
        assert cfg is not None, "must not fall back to ai-tooling defaults"
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.api_key_env_var == "ANTHROPIC_API_KEY"

    def test_default_honours_nfr_env_overrides(
        self, captured_provider_config: list[Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NFR_LLM_PROVIDER", "openai")
        monkeypatch.setenv("NFR_LLM_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("NFR_LLM_BASE_URL", "http://localhost:11434/v1")
        _llm_mod.create_llm_client()
        (cfg,) = captured_provider_config
        assert (cfg.provider, cfg.model, cfg.base_url, cfg.api_key_env_var) == (
            "openai",
            "gpt-4o-mini",
            "http://localhost:11434/v1",
            "OPENAI_API_KEY",
        )

    def test_explicit_config_fields_are_mapped(
        self, captured_provider_config: list[Any]
    ) -> None:
        _llm_mod.create_llm_client(
            LlmConfig(
                provider="openai",
                model="llama3",
                base_url="http://ollama:11434/v1",
                api_key_env_var="MY_KEY",
            )
        )
        (cfg,) = captured_provider_config
        assert (cfg.provider, cfg.model, cfg.base_url, cfg.api_key_env_var) == (
            "openai",
            "llama3",
            "http://ollama:11434/v1",
            "MY_KEY",
        )

    def test_env_overrides_explicit_config(
        self, captured_provider_config: list[Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NFR_LLM_PROVIDER", "claude-cli")
        _llm_mod.create_llm_client(LlmConfig(provider="anthropic"))
        (cfg,) = captured_provider_config
        assert cfg.provider == "claude-cli"

    def test_yaml_config_flows_through(
        self, captured_provider_config: list[Any], tmp_path: Path
    ) -> None:
        from nfr_review.config import load_config

        cfg_file = tmp_path / "nfr-review.yaml"
        cfg_file.write_text(
            "version: 1\nllm:\n  provider: anthropic\n  model: claude-haiku-4-5-20251001\n"
        )
        _llm_mod.create_llm_client(load_config(cfg_file).llm)
        (cfg,) = captured_provider_config
        assert cfg.model == "claude-haiku-4-5-20251001"

    def test_real_session_uses_resolved_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("ai_tooling")
        monkeypatch.setenv("NFR_LLM_MODEL", "claude-haiku-4-5")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = _llm_mod.create_llm_client()
        assert getattr(client, "_model", None) == "claude-haiku-4-5"
