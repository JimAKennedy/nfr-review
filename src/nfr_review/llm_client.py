"""Thin wrapper around the Anthropic SDK for Band 2 LLM-augmented rules."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

try:
    import anthropic
except ModuleNotFoundError:  # SDK is an optional dependency
    anthropic = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class LlmUnavailableError(Exception):
    """Raised when an LLM call is attempted but no API key is configured."""


class ClaudeClient:
    """Wraps the Anthropic SDK with an availability gate for Band 2 rules.

    When ``ANTHROPIC_API_KEY`` is absent or empty the client reports
    ``available == False`` and any call to :meth:`analyze` raises
    :class:`LlmUnavailableError`.
    """

    def __init__(self) -> None:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if key and anthropic is not None:
            self._client: anthropic.Anthropic | None = anthropic.Anthropic(api_key=key)
        else:
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def analyze(
        self,
        prompt: str,
        evidence_bundle: str,
        max_tokens: int = 1024,
    ) -> str:
        if self._client is None:
            raise LlmUnavailableError(
                "ANTHROPIC_API_KEY is not set; cannot perform LLM analysis"
            )

        logger.info(
            "LLM call: sending %d-char prompt + %d-char bundle",
            len(prompt),
            len(evidence_bundle),
        )

        response = self._client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": prompt + "\n\n" + evidence_bundle},
            ],
        )
        return response.content[0].text


def serialize_evidence_bundle(
    evidence_items: list[dict[str, Any]],
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
