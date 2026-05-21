# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-DOC-003: API documentation hint, py.typed, and classifier checks."""

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

        findings: list[Finding] = []
        findings.append(self._check_docstring(ev, has_python))

        if has_python:
            findings.append(self._check_py_typed(ev))
            findings.append(self._check_classifiers(ev))

        return RuleResult(rule_id=self.id, findings=findings)

    def _check_docstring(self, ev: Evidence, has_python: bool) -> Finding:
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

        return Finding(
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

    def _check_py_typed(self, ev: Evidence) -> Finding:
        has_py_typed = ev.payload.get("has_py_typed", False)

        if has_py_typed:
            return Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary="py.typed marker present — PEP 561 inline types supported.",
                recommendation="No action required.",
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.8,
                pattern_tag="py-typed",
            )

        return Finding(
            rule_id=self.id,
            rag="amber",
            severity="low",
            summary="Missing py.typed marker — PEP 561 inline type stubs not declared.",
            recommendation=(
                "Add an empty py.typed file to the package directory "
                "to declare PEP 561 inline type support."
            ),
            evidence_locator=ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=0.8,
            pattern_tag="py-typed",
        )

    def _check_classifiers(self, ev: Evidence) -> Finding:
        has_classifiers = ev.payload.get("has_classifiers", False)
        classifier_count = ev.payload.get("classifier_count", 0)

        if has_classifiers:
            return Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary=f"Trove classifiers present ({classifier_count} defined).",
                recommendation="No action required.",
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.8,
                pattern_tag="classifiers",
            )

        return Finding(
            rule_id=self.id,
            rag="green",
            severity="info",
            summary="No trove classifiers defined in pyproject.toml.",
            recommendation=(
                "Add classifiers for Development Status, License, "
                "and Programming Language to improve discoverability on PyPI."
            ),
            evidence_locator=ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=0.7,
            pattern_tag="classifiers",
        )


def _register() -> None:
    if "HYG-DOC-003" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-DOC-003", ApiDocsRule())


_register()

__all__ = ["ApiDocsRule"]
