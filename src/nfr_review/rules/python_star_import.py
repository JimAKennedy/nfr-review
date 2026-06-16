# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: python-star-import — detects wildcard imports (from X import *)."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class PythonStarImportRule:
    """Flag wildcard imports that obscure dependencies."""

    id = "python-star-import"
    band: Band = 1
    required_collectors: list[str] = ["python-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        py_evidence = filter_evidence(evidence, "python-ast", "python-ast-file")
        if not py_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no python-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in py_evidence:
            file_path = ev.payload.file_path
            for imp in ev.payload.imports:
                if imp.get("is_star"):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=f"Star import from {imp['module']}",
                            recommendation=(
                                "Use explicit imports to make dependencies"
                                " visible and avoid namespace pollution."
                            ),
                            evidence_locator=f"{file_path}:{imp['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.95,
                            pattern_tag="star-import",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "star-import",
                    py_evidence[0],
                    summary="No wildcard imports detected.",
                    confidence=0.95,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "python-star-import" not in rule_registry:
        rule_registry.register("python-star-import", PythonStarImportRule())


_register()

__all__ = ["PythonStarImportRule"]
