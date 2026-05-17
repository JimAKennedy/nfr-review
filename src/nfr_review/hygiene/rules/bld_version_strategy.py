"""HYG-BLD-002: Version declaration check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class VersionStrategyRule:
    id = "HYG-BLD-002"
    band: Band = 1
    required_collectors: list[str] = ["build-readiness"]
    category = "build-readiness"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "build-readiness-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no build-readiness-analysis evidence available",
            )

        info = ev.payload.get("version", {})
        declared = info.get("declared", False)

        if not declared:
            rag: RAG = "amber"
            severity: Severity = "medium"
            summary = (
                "No version declared (checked pyproject.toml, setup.py/cfg, "
                "package __init__.py, pom.xml, build.gradle(.kts), go.mod, "
                "Cargo.toml, *.csproj)."
            )
            recommendation = (
                "Declare a version: [project].version in pyproject.toml (Python), "
                "<version> in pom.xml (JVM), version in Cargo.toml (Rust), "
                "or <Version> in *.csproj (C#)."
            )
        else:
            source = info.get("source", "unknown")
            value = info.get("value", "?")
            rag = "green"
            severity = "info"
            summary = f"Version {value} declared in {source}."
            recommendation = "No action required."

        finding = Finding(
            rule_id=self.id,
            rag=rag,
            severity=severity,
            summary=summary,
            recommendation=recommendation,
            evidence_locator=info.get("source") or ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=1.0,
            pattern_tag="version-strategy",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-BLD-002" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-BLD-002", VersionStrategyRule())


_register()

__all__ = ["VersionStrategyRule"]
