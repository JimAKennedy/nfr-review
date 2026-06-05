# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

RAG = Literal["red", "amber", "green", "skipped"]
Severity = Literal["critical", "high", "medium", "low", "info"]


class BasePayload(BaseModel):
    """Base class for typed collector payloads.

    Subclass this for each collector's evidence kind. The ``extra="forbid"``
    config catches typos and drift between collector output and rule expectations
    at Evidence construction time.

    Provides dict-compatible ``get()`` and ``__getitem__()`` so existing rules
    using ``ev.payload.get("key")`` work without changes during migration.
    """

    model_config = ConfigDict(extra="forbid")

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-compatible attribute access for gradual migration."""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """Dict-compatible subscript access for gradual migration."""
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None

    def __contains__(self, key: object) -> bool:
        """Dict-compatible membership test for gradual migration."""
        if not isinstance(key, str):
            return False
        return key in type(self).model_fields

    def keys(self) -> list[str]:
        """Dict-compatible keys() for gradual migration."""
        return list(type(self).model_fields.keys())


class Evidence(BaseModel):
    """A single piece of evidence produced by a collector."""

    model_config = ConfigDict(extra="forbid")

    collector_name: str
    collector_version: str
    locator: str
    kind: str
    payload: SerializeAsAny[BasePayload] | dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    """A rule evaluation finding. Field order matches R007 exactly.

    The 10 R007 fields in canonical order:
    rule_id, rag, severity, summary, recommendation, evidence_locator,
    collector_name, collector_version, confidence, pattern_tag.
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    rag: RAG
    severity: Severity
    summary: str
    recommendation: str
    evidence_locator: str
    collector_name: str
    collector_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    pattern_tag: str
    content_hash: str = ""

    @property
    def identity_key(self) -> tuple[str, str, str]:
        """Legacy identity for baseline diffing: (rule_id, evidence_locator, pattern_tag)."""
        return (self.rule_id, self.evidence_locator, self.pattern_tag)

    @property
    def stable_identity_key(self) -> tuple[str, ...]:
        """Line-number-independent identity for baseline diffing.

        When content_hash is available, uses (rule_id, file_path, pattern_tag,
        content_hash) — immune to line shifts.  Falls back to identity_key
        when no content_hash is set.
        """
        if self.content_hash:
            file_path = _strip_line_from_locator(self.evidence_locator)
            return (self.rule_id, file_path, self.pattern_tag, self.content_hash)
        return self.identity_key


class RuleResult(BaseModel):
    """Result of evaluating a single rule against collected evidence."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    findings: list[Finding] = Field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None


class RunMetadata(BaseModel):
    """Run-level provenance recorded for every scan (R021)."""

    model_config = ConfigDict(extra="forbid")

    tool_version: str
    target_repo: str
    git_sha: str | None = None
    git_branch: str | None = None
    git_dirty: bool | None = None
    git_error: str | None = None
    timestamp: str
    collector_versions: dict[str, str] = Field(default_factory=dict)
    rules_run: list[str] = Field(default_factory=list)
    rules_skipped: list[dict[str, Any]] = Field(default_factory=list)


_LINE_SUFFIX_RE = re.compile(r":\d+$")


def _strip_line_from_locator(locator: str) -> str:
    """Remove a trailing :line_number from a locator, leaving just the file path."""
    return _LINE_SUFFIX_RE.sub("", locator)


def compute_content_hash(text: str) -> str:
    """Compute a short stable hash from source text for content-based fingerprinting."""
    normalized = text.strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


__all__ = [
    "RAG",
    "Severity",
    "BasePayload",
    "Evidence",
    "Finding",
    "RuleResult",
    "RunMetadata",
    "compute_content_hash",
]
