"""HYG-DOC-003: API documentation hint check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class ApiDocsRule:
    id = "HYG-DOC-003"
    band: Band = 1
    required_collectors: list[str] = ["documentation"]
    category = "documentation"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "documentation-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no documentation-analysis evidence available",
            )

        manifests = ev.payload.get("manifests", [])
        has_python = any(m.get("type") == "pyproject.toml" for m in manifests)
        has_api_docs_hint = ev.payload.get("has_api_docs_hint", False)

        if not has_python:
            rag: RAG = "green"
            severity: Severity = "info"
            summary = "No Python package detected — API docstring check not applicable."
            recommendation = "No action required."
        elif has_api_docs_hint:
            rag = "green"
            severity = "info"
            summary = "Top-level __init__.py has a module docstring."
            recommendation = "No action required."
        else:
            rag = "amber"
            severity = "medium"
            summary = (
                "Top-level __init__.py lacks a module docstring — API docs may be missing."
            )
            recommendation = (
                "Add a module docstring to the top-level __init__.py "
                "to document the package's public API."
            )

        finding = Finding(
            rule_id=self.id,
            rag=rag,
            severity=severity,
            summary=summary,
            recommendation=recommendation,
            evidence_locator=ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=0.8,
            pattern_tag="api-docs-hint",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-DOC-003" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-DOC-003", ApiDocsRule())


_register()

__all__ = ["ApiDocsRule"]
