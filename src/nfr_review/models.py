# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RAG = Literal["red", "amber", "green", "skipped"]
Severity = Literal["critical", "high", "medium", "low", "info"]
Origin = Literal["first_party", "dependency"]


class BasePayload(BaseModel):
    """Base class for typed collector payloads.

    Subclass this for each collector's evidence kind. The ``extra="forbid"``
    config catches typos and drift between collector output and rule expectations
    at Evidence construction time.

    Rules can access fields via typed attributes or dict-style subscript.
    Both ``get`` / ``__getitem__`` / ``__contains__`` delegate to ``getattr``
    so the two styles always see the same values.
    """

    model_config = ConfigDict(extra="forbid")

    def get(self, key: str, default: Any = None) -> Any:
        """Return the field value for *key*, or *default* if absent."""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return key in type(self).model_fields

    def keys(self) -> list[str]:
        return list(type(self).model_fields.keys())

    def values(self) -> list[Any]:
        return [getattr(self, k) for k in type(self).model_fields]

    def items(self) -> list[tuple[str, Any]]:
        return [(k, getattr(self, k)) for k in type(self).model_fields]


def _fill_defaults(data: dict[str, Any], model_cls: type[BasePayload]) -> dict[str, Any]:
    """Recursively fill missing required fields with zero-value defaults."""
    from pydantic_core import PydanticUndefined

    filled = dict(data)
    for fname, finfo in model_cls.model_fields.items():
        ann = finfo.annotation
        origin = getattr(ann, "__origin__", None)
        args = getattr(ann, "__args__", ())

        if fname in filled:
            val = filled[fname]
            if origin is list and args and isinstance(val, list):
                inner = args[0]
                if isinstance(inner, type) and issubclass(inner, BasePayload):
                    filled[fname] = [
                        _fill_defaults(item, inner) if isinstance(item, dict) else item
                        for item in val
                    ]
            elif (
                isinstance(ann, type)
                and issubclass(ann, BasePayload)
                and isinstance(val, dict)
            ):
                filled[fname] = _fill_defaults(val, ann)
            continue

        if finfo.default is not PydanticUndefined:
            continue
        if finfo.default_factory is not None:
            continue

        if ann is str:
            filled[fname] = ""
        elif ann is int:
            filled[fname] = 0
        elif ann is float:
            filled[fname] = 0.0
        elif ann is bool:
            filled[fname] = False
        elif origin is list:
            filled[fname] = []
        elif origin is dict:
            filled[fname] = {}
    return filled


class _DictPayloadProxy(dict):  # type: ignore[type-arg]
    """Thin dict subclass that adds attribute access.

    Used as a fallback when auto-coercion of a dict payload to a typed
    BasePayload subclass fails. Provides ``proxy.field`` access alongside
    normal dict operations so rules using typed attribute access still work.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


class Evidence(BaseModel):
    """A single piece of evidence produced by a collector."""

    model_config = ConfigDict(extra="forbid")

    collector_name: str
    collector_version: str
    locator: str
    kind: str
    payload: Any = Field(default_factory=dict)

    @classmethod
    def _coerce_dict_payload(
        cls, collector_name: str, kind: str, payload: dict[str, Any]
    ) -> Any:
        """Try to coerce a dict payload to the matching typed payload class."""
        from nfr_review._payload_registry import PAYLOAD_REGISTRY

        payload_cls = PAYLOAD_REGISTRY.get((collector_name, kind))
        if payload_cls is None:
            return _DictPayloadProxy(payload)
        filled = _fill_defaults(payload, payload_cls)
        try:
            return payload_cls.model_validate(filled)
        except (ValueError, TypeError):
            return _DictPayloadProxy(payload)

    def model_post_init(self, __context: Any) -> None:
        if (
            isinstance(self.payload, dict)
            and not isinstance(self.payload, _DictPayloadProxy)
            and self.payload
        ):
            coerced = self._coerce_dict_payload(self.collector_name, self.kind, self.payload)
            if coerced is not self.payload:
                object.__setattr__(self, "payload", coerced)


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
    origin: Origin = "first_party"

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


# nfr-review:skip(python-dormant-classes) reason: emitted in every JSONL run record
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
    "Origin",
    "BasePayload",
    "Evidence",
    "Finding",
    "RuleResult",
    "RunMetadata",
    "compute_content_hash",
]
