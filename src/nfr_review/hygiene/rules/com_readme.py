"""HYG-COM-001: README presence and quality check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band

_STUB_THRESHOLD = 200


class ReadmePresenceRule:
    id = "HYG-COM-001"
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

        info = ev.payload.get("readme", {})
        exists = info.get("exists", False)
        size = info.get("size", 0)

        if not exists:
            rag: RAG = "red"
            severity: Severity = "high"
            summary = "No README file found at the repository root."
            recommendation = "Add a README.md documenting project purpose, setup, and usage."
        elif size < _STUB_THRESHOLD:
            rag = "amber"
            severity = "medium"
            summary = f"README exists but is only {size} bytes — likely a stub."
            recommendation = (
                "Expand the README with setup instructions, "
                "usage examples, and contribution guidelines."
            )
        else:
            rag = "green"
            severity = "info"
            summary = f"README found ({size} bytes)."
            recommendation = "No action required."

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
            pattern_tag="readme-presence",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-COM-001" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-COM-001", ReadmePresenceRule())


_register()

__all__ = ["ReadmePresenceRule"]
