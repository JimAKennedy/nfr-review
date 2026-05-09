"""HYG-COM-005: CHANGELOG presence check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class ChangelogPresenceRule:
    id = "HYG-COM-005"
    band: Band = 1
    required_collectors: list[str] = ["community"]
    category = "community"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "community-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no community-analysis evidence available",
            )

        info = ev.payload.get("changelog", {})
        exists = info.get("exists", False)

        if exists:
            rag: RAG = "green"
            severity: Severity = "info"
            summary = f"Changelog found at {info.get('path')}."
            recommendation = "No action required."
        else:
            rag = "amber"
            severity = "medium"
            summary = "No CHANGELOG.md, CHANGES.md, or HISTORY.md found."
            recommendation = "Add a changelog to document notable changes between releases."

        finding = Finding(
            rule_id=self.id,
            rag=rag,
            severity=severity,
            summary=summary,
            recommendation=recommendation,
            evidence_locator=info.get("path") or ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=1.0,
            pattern_tag="changelog-presence",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-COM-005" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-COM-005", ChangelogPresenceRule())


_register()

__all__ = ["ChangelogPresenceRule"]
