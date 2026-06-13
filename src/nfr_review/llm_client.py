# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""LLM client abstraction for Band 2 LLM-augmented rules.

The Anthropic SDK is an **optional** dependency.  Install it with::

    pip install nfr-review[llm-anthropic]

Three backends are available:

* ``anthropic`` (default) — uses the Anthropic Python SDK.
* ``openai`` — uses any OpenAI-compatible API (Ollama, Azure, OpenRouter).
* ``claude-cli`` — shells out to ``claude -p`` (Claude Code CLI).

Configure via ``nfr-review.yaml`` under the ``llm:`` key, or override with
env vars ``NFR_LLM_PROVIDER``, ``NFR_LLM_MODEL``, ``NFR_LLM_BASE_URL``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess  # nosec B404 — intentional: shells out to claude CLI
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nfr_review.config import LlmConfig

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

try:
    import openai as openai_mod
except ImportError:
    openai_mod = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_BACKEND_ENV = "NFR_LLM_BACKEND"
_BACKEND_API = "api"
_BACKEND_CLI = "claude-cli"

_ENV_LOADED = False


def _load_dotenv_once() -> None:
    """Load the project ``.env`` into ``os.environ`` (no-clobber, once)."""
    global _ENV_LOADED  # noqa: PLW0603
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


# nfr-review:skip(python-dormant-classes) reason: raised by create_llm_client
class LlmUnavailableError(Exception):
    """Raised when an LLM call is attempted but no backend is usable."""


def _resolve_backend() -> str:
    """Return the active backend name, validated."""
    _load_dotenv_once()
    raw = os.environ.get(_BACKEND_ENV, _BACKEND_API).strip().lower()
    if raw in (_BACKEND_API, _BACKEND_CLI):
        return raw
    logger.warning("Unknown %s=%r — falling back to %r", _BACKEND_ENV, raw, _BACKEND_API)
    return _BACKEND_API


# nfr-review:skip(python-dormant-classes) reason: instantiated by create_llm_client factory
class ClaudeClient:
    """Legacy LLM client supporting the Anthropic API or the Claude CLI.

    Prefer :func:`create_llm_client` for new code. This class is kept for
    backward compatibility and will be removed in a future release.
    """

    def __init__(self) -> None:
        self._backend = _resolve_backend()
        self._model = os.environ.get("NFR_LLM_MODEL", "claude-sonnet-4-6")

        if self._backend == _BACKEND_CLI:
            self._cli_path: str | None = shutil.which("claude")
            self._client: Any | None = None
            if self._cli_path is None:
                logger.warning("claude CLI not found on PATH; LLM calls will be unavailable")
        else:
            self._cli_path = None
            key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if key:
                if anthropic is None:
                    logger.debug(
                        "anthropic SDK not installed; "
                        "install nfr-review[llm-anthropic] for API access"
                    )
                    self._client = None
                else:
                    self._client = anthropic.Anthropic(api_key=key)
            else:
                self._client = None

    @property
    def available(self) -> bool:
        if self._backend == _BACKEND_CLI:
            return self._cli_path is not None
        return self._client is not None

    def analyze(
        self,
        prompt: str,
        evidence_bundle: str,
        max_tokens: int = 1024,
    ) -> str:
        if not self.available:
            if self._backend == _BACKEND_CLI:
                raise LlmUnavailableError(
                    "claude CLI not found on PATH; cannot perform LLM analysis"
                )
            if anthropic is None:
                raise LlmUnavailableError(
                    "anthropic SDK not installed; "
                    "install nfr-review[llm-anthropic] for LLM analysis"
                )
            raise LlmUnavailableError(
                "ANTHROPIC_API_KEY is not set; cannot perform LLM analysis"
            )

        combined = prompt + "\n\n" + evidence_bundle

        logger.info(
            "LLM call [%s]: sending %d-char prompt + %d-char bundle",
            self._backend,
            len(prompt),
            len(evidence_bundle),
        )

        if self._backend == _BACKEND_CLI:
            return self._analyze_cli(combined, max_tokens)
        return self._analyze_api(combined, max_tokens)

    def _analyze_api(self, combined: str, max_tokens: int) -> str:
        assert self._client is not None
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": combined},
            ],
        )
        block = response.content[0]
        if not hasattr(block, "text"):
            raise TypeError(f"Expected TextBlock, got {type(block).__name__}")
        return block.text

    def _analyze_cli(self, combined: str, max_tokens: int) -> str:
        assert self._cli_path is not None
        cmd = [
            self._cli_path,
            "-p",
            combined,
            "--output-format",
            "text",
            "--max-turns",
            "1",
            "--allowedTools",
            "",
        ]
        try:
            result = subprocess.run(  # nosec B603 — cmd is hardcoded, no user input
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise LlmUnavailableError("claude CLI timed out after 120s") from exc

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise LlmUnavailableError(f"claude CLI exited {result.returncode}: {stderr[:200]}")
        return result.stdout.strip()


# ---------------------------------------------------------------------------
# Config-driven backend classes
# ---------------------------------------------------------------------------


# nfr-review:skip(python-dormant-classes) reason: instantiated by create_llm_client factory
class AnthropicClient:
    """LLM backend using the Anthropic Python SDK."""

    def __init__(self, *, model: str, api_key: str, base_url: str | None = None) -> None:
        self._model = model
        if anthropic is None:
            self._client: Any | None = None
            logger.warning(
                "anthropic SDK not installed; install nfr-review[llm-anthropic] for API access"
            )
        elif not api_key:
            self._client = None
        else:
            kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = anthropic.Anthropic(**kwargs)

    @property
    def available(self) -> bool:
        return self._client is not None

    def analyze(self, prompt: str, evidence_bundle: str, max_tokens: int = 1024) -> str:
        if not self.available:
            raise LlmUnavailableError(
                "anthropic SDK not installed; install nfr-review[llm-anthropic]"
            )
        assert self._client is not None
        combined = prompt + "\n\n" + evidence_bundle
        logger.info(
            "LLM call [anthropic/%s]: sending %d-char prompt + %d-char bundle",
            self._model,
            len(prompt),
            len(evidence_bundle),
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": combined}],
        )
        block = response.content[0]
        if not hasattr(block, "text"):
            raise TypeError(f"Expected TextBlock, got {type(block).__name__}")
        return block.text


# nfr-review:skip(python-dormant-classes) reason: instantiated by create_llm_client factory
class OpenAICompatibleClient:
    """LLM backend using any OpenAI-compatible API."""

    def __init__(self, *, model: str, api_key: str, base_url: str | None = None) -> None:
        self._model = model
        if openai_mod is None:
            self._client: Any | None = None
            logger.warning(
                "openai SDK not installed; install nfr-review[llm-openai] for access"
            )
        elif not api_key:
            self._client = None
        else:
            kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = openai_mod.OpenAI(**kwargs)

    @property
    def available(self) -> bool:
        return self._client is not None

    def analyze(self, prompt: str, evidence_bundle: str, max_tokens: int = 1024) -> str:
        if not self.available:
            raise LlmUnavailableError(
                "openai SDK not installed; install nfr-review[llm-openai]"
            )
        assert self._client is not None
        combined = prompt + "\n\n" + evidence_bundle
        logger.info(
            "LLM call [openai/%s]: sending %d-char prompt + %d-char bundle",
            self._model,
            len(prompt),
            len(evidence_bundle),
        )
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": combined}],
        )
        choice = response.choices[0]
        if choice.message.content is None:
            raise TypeError("OpenAI response contained no content")
        return choice.message.content


# nfr-review:skip(python-dormant-classes) reason: instantiated by create_llm_client factory
class ClaudeCliClient:
    """LLM backend that shells out to the Claude Code CLI."""

    def __init__(self) -> None:
        self._cli_path: str | None = shutil.which("claude")
        if self._cli_path is None:
            logger.warning("claude CLI not found on PATH; LLM calls will be unavailable")

    @property
    def available(self) -> bool:
        return self._cli_path is not None

    def analyze(self, prompt: str, evidence_bundle: str, max_tokens: int = 1024) -> str:
        if not self.available:
            raise LlmUnavailableError(
                "claude CLI not found on PATH; cannot perform LLM analysis"
            )
        assert self._cli_path is not None
        combined = prompt + "\n\n" + evidence_bundle
        logger.info(
            "LLM call [claude-cli]: sending %d-char prompt + %d-char bundle",
            len(prompt),
            len(evidence_bundle),
        )
        cmd = [
            self._cli_path,
            "-p",
            "--output-format",
            "text",
            "--max-turns",
            "1",
            "--allowedTools",
            "",
        ]
        try:
            result = subprocess.run(  # nosec B603
                cmd,
                input=combined,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise LlmUnavailableError("claude CLI timed out after 120s") from exc

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise LlmUnavailableError(f"claude CLI exited {result.returncode}: {stderr[:200]}")
        return result.stdout.strip()


# ---------------------------------------------------------------------------
# JSON extraction from LLM responses
# ---------------------------------------------------------------------------


def extract_json(text: str, *, expect: str = "object") -> dict | list | None:
    """Extract a JSON object or array from an LLM response.

    Uses a 3-stage strategy: direct parse, markdown fence extraction,
    then bare bracket/brace extraction. Returns ``None`` if no valid JSON
    of the expected type can be found.

    *expect* controls the accepted type: ``"object"`` for ``dict``,
    ``"array"`` for ``list``, or ``"any"`` for either.
    """
    _ok_types: tuple[type, ...] = (
        (dict,) if expect == "object" else (list,) if expect == "array" else (dict, list)
    )

    def _check(val: object) -> dict | list | None:
        return val if isinstance(val, _ok_types) else None  # type: ignore[return-value]

    stripped = text.strip()

    # Stage 1: direct parse
    try:
        if (result := _check(json.loads(stripped))) is not None:
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Stage 2: markdown code fence
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", stripped, re.DOTALL)
    if fence_match:
        try:
            if (result := _check(json.loads(fence_match.group(1)))) is not None:
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # Stage 3: bare delimiters — find outermost { } or [ ]
    open_char = "{" if expect == "object" else "[" if expect == "array" else None
    if open_char:
        close_char = "}" if open_char == "{" else "]"
        try:
            start = stripped.index(open_char)
            end = stripped.rindex(close_char) + 1
            if (result := _check(json.loads(stripped[start:end]))) is not None:
                return result
        except (ValueError, json.JSONDecodeError):
            pass
    else:
        for oc, cc in ("{}", "[]"):
            try:
                start = stripped.index(oc)
                end = stripped.rindex(cc) + 1
                if (result := _check(json.loads(stripped[start:end]))) is not None:
                    return result
            except (ValueError, json.JSONDecodeError):
                pass

    return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

# Union type for all backend classes — satisfies the LlmClient protocol.
LlmClientImpl = AnthropicClient | OpenAICompatibleClient | ClaudeCliClient


def create_llm_client(config: LlmConfig | None = None) -> LlmClientImpl:
    """Create an LLM client from config, with env-var overrides applied.

    When *config* is ``None``, uses default :class:`LlmConfig` values.
    """
    from nfr_review.config import LlmConfig as _LlmConfig

    _load_dotenv_once()

    _apply_legacy = config is None
    if config is None:
        config = _LlmConfig()
    resolved = config.resolve()

    # Legacy setup scripts wrote NFR_LLM_BACKEND (not NFR_LLM_PROVIDER).
    # Only apply when no explicit config was passed and NFR_LLM_PROVIDER is absent.
    if _apply_legacy and not os.environ.get("NFR_LLM_PROVIDER", "").strip():
        _legacy_map = {"api": "anthropic", "claude-cli": "claude-cli"}
        if legacy := os.environ.get("NFR_LLM_BACKEND", "").strip():
            mapped = _legacy_map.get(legacy, legacy)
            if mapped != resolved.provider:
                resolved = resolved.model_copy(update={"provider": mapped})

    if resolved.provider == "claude-cli":
        return ClaudeCliClient()

    api_key = os.environ.get(resolved.api_key_env_var, "").strip()
    if not api_key:
        logger.debug(
            "No LLM API key found (%s not set); LLM-augmented rules will be skipped",
            resolved.api_key_env_var,
        )

    if resolved.provider == "openai":
        return OpenAICompatibleClient(
            model=resolved.model,
            api_key=api_key,
            base_url=resolved.base_url,
        )

    return AnthropicClient(
        model=resolved.model,
        api_key=api_key,
        base_url=resolved.base_url,
    )


def serialize_evidence_bundle(
    evidence_items: list[dict],
    max_bytes: int = 8192,
) -> str:
    """Serialize evidence dicts to JSON, truncating to fit *max_bytes*.

    Items are dropped from the end until the serialized output fits.
    An empty list produces ``'[]'``.
    """
    items = list(evidence_items)
    while True:
        serialized = json.dumps(items, separators=(",", ":"))
        if len(serialized.encode()) <= max_bytes:
            return serialized
        if not items:
            return "[]"
        items.pop()


__all__ = [
    "AnthropicClient",
    "ClaudeCliClient",
    "ClaudeClient",
    "LlmClientImpl",
    "LlmUnavailableError",
    "OpenAICompatibleClient",
    "create_llm_client",
    "extract_json",
    "serialize_evidence_bundle",
]
