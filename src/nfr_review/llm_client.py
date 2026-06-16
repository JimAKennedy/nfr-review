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
import time
from abc import ABC, abstractmethod
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

_ENV_LOADED = False

_DEFAULT_TIMEOUT_SECONDS = 120
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 16.0

_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 529})


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


def _is_transient(exc: Exception) -> bool:
    """Return True if *exc* looks like a transient API error worth retrying."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int) and status in _TRANSIENT_STATUS_CODES:
        return True
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    cls_name = type(exc).__name__.lower()
    return any(k in cls_name for k in ("timeout", "ratelimit", "rate_limit", "connection"))


def _retry_with_backoff(
    fn: Any,
    *,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _RETRY_BASE_DELAY,
    max_delay: float = _RETRY_MAX_DELAY,
    label: str = "LLM",
) -> Any:
    """Call *fn* with bounded exponential backoff on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except LlmUnavailableError:
            raise
        except Exception as exc:
            last_exc = exc
            if not _is_transient(exc) or attempt == max_retries - 1:
                raise
            delay = min(base_delay * (2**attempt), max_delay)
            logger.warning(
                "%s transient error (attempt %d/%d), retrying in %.1fs: %s",
                label,
                attempt + 1,
                max_retries,
                delay,
                exc,
            )
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]  # unreachable but satisfies type checker


# ---------------------------------------------------------------------------
# Abstract base for SDK-backed clients
# ---------------------------------------------------------------------------


class _BaseSdkClient(ABC):
    """Shared scaffold for SDK-backed LLM clients.

    Subclasses implement :meth:`_call_sdk` only.  Availability checking,
    prompt combining, logging, retry, and timeout are handled here.
    """

    _model: str
    _client: Any | None
    _timeout_seconds: int
    _backend_label: str

    @property
    def available(self) -> bool:
        return self._client is not None

    def analyze(self, prompt: str, evidence_bundle: str, max_tokens: int = 1024) -> str:
        if not self.available:
            raise LlmUnavailableError(self._unavailable_message())
        assert self._client is not None  # noqa: S101
        combined = prompt + "\n\n" + evidence_bundle
        logger.info(
            "LLM call [%s/%s]: sending %d-char prompt + %d-char bundle",
            self._backend_label,
            self._model,
            len(prompt),
            len(evidence_bundle),
        )
        return _retry_with_backoff(
            lambda: self._call_sdk(combined, max_tokens),
            label=self._backend_label,
        )

    @abstractmethod
    def _call_sdk(self, combined: str, max_tokens: int) -> str:
        """Execute the actual SDK/subprocess call.  Must not handle retries."""

    @abstractmethod
    def _unavailable_message(self) -> str:
        """Return the error message for :class:`LlmUnavailableError`."""


# ---------------------------------------------------------------------------
# Config-driven backend classes
# ---------------------------------------------------------------------------


# nfr-review:skip(python-dormant-classes) reason: instantiated by create_llm_client factory
class AnthropicClient(_BaseSdkClient):
    """LLM backend using the Anthropic Python SDK."""

    _backend_label = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        if anthropic is None:
            self._client: Any | None = None
            logger.warning(
                "anthropic SDK not installed; install nfr-review[llm-anthropic] for API access"
            )
        elif not api_key:
            self._client = None
        else:
            kwargs: dict[str, Any] = {"api_key": api_key, "timeout": float(timeout_seconds)}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = anthropic.Anthropic(**kwargs)

    def _call_sdk(self, combined: str, max_tokens: int) -> str:
        assert self._client is not None
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": combined}],
        )
        block = response.content[0]
        if not hasattr(block, "text"):
            raise TypeError(f"Expected TextBlock, got {type(block).__name__}")
        return block.text

    def _unavailable_message(self) -> str:
        return "anthropic SDK not installed; install nfr-review[llm-anthropic]"


# nfr-review:skip(python-dormant-classes) reason: instantiated by create_llm_client factory
class OpenAICompatibleClient(_BaseSdkClient):
    """LLM backend using any OpenAI-compatible API."""

    _backend_label = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        if openai_mod is None:
            self._client: Any | None = None
            logger.warning(
                "openai SDK not installed; install nfr-review[llm-openai] for access"
            )
        elif not api_key:
            self._client = None
        else:
            kwargs: dict[str, Any] = {"api_key": api_key, "timeout": float(timeout_seconds)}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = openai_mod.OpenAI(**kwargs)

    def _call_sdk(self, combined: str, max_tokens: int) -> str:
        assert self._client is not None
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": combined}],
        )
        choice = response.choices[0]
        if choice.message.content is None:
            raise TypeError("OpenAI response contained no content")
        return choice.message.content

    def _unavailable_message(self) -> str:
        return "openai SDK not installed; install nfr-review[llm-openai]"


# nfr-review:skip(python-dormant-classes) reason: instantiated by create_llm_client factory
class ClaudeCliClient(_BaseSdkClient):
    """LLM backend that shells out to the Claude Code CLI."""

    _backend_label = "claude-cli"

    def __init__(self, *, timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._model = "claude-cli"
        self._client: Any | None = True  # sentinel — availability means CLI found
        self._cli_path: str | None = shutil.which("claude")
        self._timeout_seconds = timeout_seconds
        if self._cli_path is None:
            self._client = None
            logger.warning("claude CLI not found on PATH; LLM calls will be unavailable")

    @property
    def available(self) -> bool:
        return self._cli_path is not None

    def _call_sdk(self, combined: str, max_tokens: int) -> str:
        assert self._cli_path is not None  # noqa: S101
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
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise LlmUnavailableError(
                f"claude CLI timed out after {self._timeout_seconds}s"
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise LlmUnavailableError(f"claude CLI exited {result.returncode}: {stderr[:200]}")
        return result.stdout.strip()

    def _unavailable_message(self) -> str:
        return "claude CLI not found on PATH; cannot perform LLM analysis"


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

    if config is None:
        config = _LlmConfig()
    resolved = config.resolve()

    timeout = _DEFAULT_TIMEOUT_SECONDS

    if resolved.provider == "claude-cli":
        return ClaudeCliClient(timeout_seconds=timeout)

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
            timeout_seconds=timeout,
        )

    return AnthropicClient(
        model=resolved.model,
        api_key=api_key,
        base_url=resolved.base_url,
        timeout_seconds=timeout,
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
    "LlmClientImpl",
    "LlmUnavailableError",
    "OpenAICompatibleClient",
    "create_llm_client",
    "extract_json",
    "serialize_evidence_bundle",
]
