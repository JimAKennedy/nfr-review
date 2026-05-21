# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-DOC-002: Documentation infrastructure presence check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class DocsExistRule:
    id = "HYG-DOC-002"
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

        has_docs_dir = ev.payload.get("has_docs_dir", False)
        doc_tool = ev.payload.get("doc_tool", "none")

        if not has_docs_dir and doc_tool == "none":
            rag: RAG = "amber"
            severity: Severity = "medium"
            summary = "No docs/ directory and no documentation tool config found."
            recommendation = (
                "Add a docs/ directory with project documentation, "
                "or set up mkdocs/sphinx for structured docs."
            )
        else:
            parts = []
            if has_docs_dir:
                parts.append("docs/ directory present")
            if doc_tool != "none":
                parts.append(f"{doc_tool} config detected")
            rag = "green"
            severity = "info"
            summary = f"Documentation infrastructure found: {'; '.join(parts)}."
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
            pattern_tag="docs-infrastructure",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-DOC-002" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-DOC-002", DocsExistRule())


_register()

__all__ = ["DocsExistRule"]
