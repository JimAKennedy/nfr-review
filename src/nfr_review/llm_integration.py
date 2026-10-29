# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Single integration point between nfr-review and the ai-tooling library.

When ai-tooling is installed (``pip install nfr-review[llm]``), this module
delegates all LLM work to it.  When it is not installed the public surface is
still importable and ``create_llm_client()`` returns an inert stub whose
``available`` property is ``False``.

Public API
----------
create_llm_client(config=None)  -> LlmClient
LlmClient                        (re-exported from ai_tooling or stub)
ProviderUnavailableError         (re-exported from ai_tooling or stub)
extract_json                     (re-exported from ai_tooling or stub)
serialize_bundle                 (re-exported from ai_tooling or stub)
run_analysis                     (re-exported from ai_tooling or stub)
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nfr_review.config import LlmConfig

logger = logging.getLogger(__name__)

try:
    from ai_tooling.config import ProviderConfig
    from ai_tooling.protocols import LlmClient
    from ai_tooling.providers import ProviderUnavailableError
    from ai_tooling.response import extract_json, serialize_bundle
    from ai_tooling.session import create_session
    from ai_tooling.workflows.analyze import run_analysis

    _AI_TOOLING_AVAILABLE = True

    def create_llm_client(config: LlmConfig | None = None) -> LlmClient:
        """Create an LLM client from an nfr-review LlmConfig.

        Maps nfr-review's ``LlmConfig`` fields onto ``ai_tooling.ProviderConfig``
        and delegates session creation to ``ai_tooling.create_session()``.
        When *config* is ``None``, uses ``ai_tooling`` defaults.
        """
        if config is None:
            return create_session()

        provider_cfg = ProviderConfig(
            provider=config.provider,
            model=config.model,
            base_url=config.base_url,
            api_key_env_var=config.api_key_env_var,
        )
        return create_session(provider_cfg)

except ImportError:
    _AI_TOOLING_AVAILABLE = False

    # ---------------------------------------------------------------------------
    # Stubs — keep callers importable when ai-tooling is absent
    # ---------------------------------------------------------------------------

    class ProviderUnavailableError(Exception):  # type: ignore[no-redef]
        """Raised when an LLM call is attempted but no backend is usable."""

    class _UnavailableClient:
        """Inert LLM client used when ai-tooling is not installed."""

        @property
        def available(self) -> bool:
            return False

        def call(self, prompt: str, *, max_tokens: int = 1024) -> str:
            raise ProviderUnavailableError(
                "ai-tooling is not installed; install nfr-review[llm] for LLM support"
            )

    # Re-use the typing-compatible shape without importing ai_tooling
    LlmClient = _UnavailableClient  # type: ignore[assignment,misc]

    def create_llm_client(config: Any = None) -> _UnavailableClient:  # type: ignore[misc]
        """Return an unavailable stub client when ai-tooling is absent."""
        logger.debug(
            "ai-tooling not installed; LLM-augmented rules will be skipped "
            "(install nfr-review[llm] to enable)"
        )
        return _UnavailableClient()

    def extract_json(text: str, *, expect: str = "object") -> dict | list | None:  # type: ignore[misc]
        """Extract a JSON object or array from *text* (ai-tooling fallback).

        Mirrors the ai_tooling.response.extract_json implementation so that
        callers work correctly even when ai-tooling is not installed.
        """
        _ok_types: tuple[type, ...] = (
            (dict,) if expect == "object" else (list,) if expect == "array" else (dict, list)
        )

        def _check(val: object) -> dict | list | None:
            return val if isinstance(val, _ok_types) else None  # type: ignore[return-value]

        stripped = text.strip()

        try:
            if (result := _check(json.loads(stripped))) is not None:
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", stripped, re.DOTALL)
        if fence_match:
            try:
                if (result := _check(json.loads(fence_match.group(1)))) is not None:
                    return result
            except (json.JSONDecodeError, ValueError):
                pass

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

    def serialize_bundle(items: list[dict], max_bytes: int = 8192) -> str:  # type: ignore[misc]
        """Serialize evidence dicts to JSON, truncating to fit *max_bytes* (fallback).

        Mirrors the ai_tooling.response.serialize_bundle implementation.
        """
        items = list(items)
        while True:
            serialized = json.dumps(items, separators=(",", ":"))
            if len(serialized.encode()) <= max_bytes:
                return serialized
            if not items:
                return "[]"
            items.pop()

    def run_analysis(  # type: ignore[misc]
        client: Any,
        prompt: str,
        evidence: list[dict],
        *,
        max_tokens: int = 1024,
        max_bundle_bytes: int = 8192,
    ) -> str:
        """Call client.call() with prompt + serialized evidence bundle.

        Mirrors ai_tooling.workflows.analyze.run_analysis so that callers work
        correctly even when ai-tooling is not installed.
        """
        bundle = serialize_bundle(evidence, max_bytes=max_bundle_bytes)
        return client.call(prompt + "\n\n" + bundle, max_tokens=max_tokens)


__all__ = [
    "LlmClient",
    "ProviderUnavailableError",
    "create_llm_client",
    "extract_json",
    "run_analysis",
    "serialize_bundle",
]
