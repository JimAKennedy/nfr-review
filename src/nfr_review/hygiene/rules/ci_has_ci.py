"""HYG-CI-001: CI/CD pipeline presence check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class CiPresenceRule:
    id = "HYG-CI-001"
    band: Band = 1
    required_collectors: list[str] = ["ci-automation"]
    category = "ci-automation"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "ci-automation-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ci-automation-analysis evidence available",
            )

        has_ci = ev.payload.get("has_ci", False)

        if not has_ci:
            rag: RAG = "red"
            severity: Severity = "high"
            summary = "No CI/CD configuration found."
            recommendation = (
                "Add a CI pipeline (e.g. GitHub Actions, GitLab CI) "
                "to automate testing, linting, and deployment."
            )
        else:
            systems = ev.payload.get("ci_systems", [])
            rag = "green"
            severity = "info"
            summary = f"CI/CD detected: {', '.join(systems)}."
            recommendation = "No action required."

        finding = Finding(
            rule_id=self.id,
            rag=rag,
            severity=severity,
            summary=summary,
            recommendation=recommendation,
            evidence_locator=ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=1.0,
            pattern_tag="ci-presence",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-001" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-001", CiPresenceRule())


_register()

__all__ = ["CiPresenceRule"]
