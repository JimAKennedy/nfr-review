# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed rule framework: Hit, make_finding, FieldRule[P].

Subclass ``FieldRule[YourPayload]`` for Band-1 rules that read a single
evidence kind. Override ``check()`` to yield ``Hit`` objects; the base
handles evidence selection, skip-if-empty, payload coercion, the green
all-clear finding, and Finding construction.

Rules that join multiple collectors, use LLM orchestration, or do
cross-record aggregation should implement ``evaluate()`` directly —
the ``Rule`` protocol remains the permanent escape hatch.

See docs/rule-framework.md for full design rationale and authoring guide.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from nfr_review.models import (
    RAG,
    BasePayload,
    Evidence,
    Finding,
    RuleResult,
    Severity,
)
from nfr_review.protocols import Band

P = TypeVar("P", bound=BasePayload)

_RAG_SEVERITY: dict[RAG, Severity] = {
    "red": "high",
    "amber": "medium",
    "green": "info",
}


@dataclass(frozen=True, slots=True)
class Hit:
    """What a rule author yields from ``check()``.

    Everything else (rule_id, collector info, default severity, the green
    all-clear) is filled by the base class or ``make_finding``.
    """

    rag: RAG
    summary: str
    recommendation: str
    locator: str
    severity: Severity | None = None
    confidence: float | None = None
    pattern_tag: str | None = None
    content_hash: str = ""


def make_finding(
    *,
    rule_id: str,
    hit: Hit,
    ev: Evidence,
    pattern_tag: str,
    default_confidence: float = 0.9,
) -> Finding:
    """Build a ``Finding`` from a ``Hit`` with single-source severity precedence.

    Severity: ``hit.severity`` (explicit override) -> ``_RAG_SEVERITY[hit.rag]``.
    Confidence: ``hit.confidence`` (explicit) -> ``default_confidence``.
    """
    return Finding(
        rule_id=rule_id,
        rag=hit.rag,
        severity=hit.severity or _RAG_SEVERITY[hit.rag],
        summary=hit.summary,
        recommendation=hit.recommendation,
        evidence_locator=hit.locator,
        collector_name=ev.collector_name,
        collector_version=ev.collector_version,
        confidence=hit.confidence if hit.confidence is not None else default_confidence,
        pattern_tag=hit.pattern_tag or pattern_tag,
        content_hash=hit.content_hash,
    )


class FieldRule(Generic[P]):
    """Declarative single-evidence-kind rule with typed payload access.

    Subclasses set class attributes and implement ``check()``.
    The base handles selection, skip-if-empty, payload coercion,
    the green all-clear finding, and Finding construction.
    """

    id: str
    band: Band = 1
    collector_name: str
    evidence_kind: str
    payload_type: type[P]
    pattern_tag: str
    required_tech: list[str] = []
    default_confidence: float = 0.9
    all_clear_summary: str = "No issues detected."
    all_clear_recommendation: str = "No action required."

    required_collectors: list[str] = []

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        if not cls.__dict__.get("required_collectors") and hasattr(cls, "collector_name"):
            cls.required_collectors = [cls.collector_name]

    def check(self, payload: P, ev: Evidence) -> Iterable[Hit]:
        """Yield ``Hit`` objects for one typed payload. Yield nothing when clean."""
        raise NotImplementedError

    def _coerce(self, raw: object) -> P:
        """Coerce *raw* to the declared ``payload_type``.

        - Typed payload (isinstance match): returned as-is (fast path).
        - Different BasePayload subclass: round-tripped through model_dump/validate.
        - Dict (today's common case): validated via model_validate.

        Raises ``ValidationError`` on schema mismatch — the engine records
        this as an auditable rule-skip.
        """
        if isinstance(raw, self.payload_type):
            return raw
        if isinstance(raw, BasePayload):
            target_fields = self.payload_type.model_fields
            return self.payload_type.model_validate(
                {k: v for k, v in raw.model_dump().items() if k in target_fields}
            )
        return self.payload_type.model_validate(raw)  # type: ignore[arg-type]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [
            e
            for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason=f"no {self.evidence_kind} evidence available",
            )

        findings: list[Finding] = []
        for ev in relevant:
            payload = self._coerce(ev.payload)
            for hit in self.check(payload, ev):
                findings.append(
                    make_finding(
                        rule_id=self.id,
                        hit=hit,
                        ev=ev,
                        pattern_tag=self.pattern_tag,
                        default_confidence=self.default_confidence,
                    )
                )

        if not findings:
            findings.append(
                make_finding(
                    rule_id=self.id,
                    ev=relevant[0],
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                    hit=Hit(
                        rag="green",
                        summary=self.all_clear_summary,
                        recommendation=self.all_clear_recommendation,
                        locator="project-wide",
                    ),
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)
