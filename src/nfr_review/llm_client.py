# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Thin wrapper around the Anthropic SDK (or Claude CLI) for Band 2 LLM-augmented rules.

Set ``NFR_LLM_BACKEND`` to choose the backend:

* ``api`` (default) — uses ``ANTHROPIC_API_KEY`` and the Anthropic Python SDK.
* ``claude-cli`` — shells out to ``claude -p`` (Claude Code CLI), which uses
  your Claude Max subscription.  No API key required.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess  # nosec B404 — intentional: shells out to claude CLI
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

_BACKEND_ENV = "NFR_LLM_BACKEND"
_BACKEND_API = "api"
_BACKEND_CLI = "claude-cli"

LLM_MODEL = os.environ.get("NFR_LLM_MODEL", "claude-sonnet-4-20250514")

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


class ClaudeClient:
    """Unified LLM client supporting the Anthropic API or the Claude CLI.

    Backend selection is controlled by ``NFR_LLM_BACKEND``:

    * ``api`` — requires ``ANTHROPIC_API_KEY``.
    * ``claude-cli`` — requires the ``claude`` binary on ``$PATH``.

    When neither prerequisite is satisfied, :attr:`available` is ``False``
    and :meth:`analyze` raises :class:`LlmUnavailableError`.
    """

    def __init__(self) -> None:
        self._backend = _resolve_backend()

        if self._backend == _BACKEND_CLI:
            self._cli_path: str | None = shutil.which("claude")
            self._client: anthropic.Anthropic | None = None
            if self._cli_path is None:
                logger.warning("claude CLI not found on PATH; LLM calls will be unavailable")
        else:
            self._cli_path = None
            key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if key:
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
            model=LLM_MODEL,
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
            "--no-input",
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
    "ClaudeClient",
    "LlmUnavailableError",
    "serialize_evidence_bundle",
]
