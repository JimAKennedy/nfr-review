"""HYG-COM-003: CODE_OF_CONDUCT.md presence check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class CodeOfConductPresenceRule:
    id = "HYG-COM-003"
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

        info = ev.payload.get("code_of_conduct", {})
        exists = info.get("exists", False)

        if exists:
            rag: RAG = "green"
            severity: Severity = "info"
            summary = "CODE_OF_CONDUCT.md found."
            recommendation = "No action required."
        else:
            rag = "amber"
            severity = "medium"
            summary = "No CODE_OF_CONDUCT.md found."
            recommendation = "Add a CODE_OF_CONDUCT.md to set community behavior expectations."

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
            pattern_tag="code-of-conduct-presence",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-COM-003" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-COM-003", CodeOfConductPresenceRule())


_register()

__all__ = ["CodeOfConductPresenceRule"]
