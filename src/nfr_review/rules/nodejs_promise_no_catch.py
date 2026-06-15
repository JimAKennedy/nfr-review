# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: nodejs-promise-no-catch — detects .then() chains without .catch() error handling."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class NodejsPromiseNoCatchRule:
    """Flag .then() promise chains that lack .catch() error handling."""

    id = "nodejs-promise-no-catch"
    band: Band = 1
    required_collectors: list[str] = ["nodejs-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        js_evidence = filter_evidence(evidence, "nodejs-ast", "nodejs-ast-file")
        if not js_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no nodejs-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in js_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for chain in ev.payload.get("promise_chains", []):
                if not chain["has_catch"]:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=".then() chain without .catch()",
                            recommendation=(
                                "Add .catch() to the promise chain or convert"
                                " to async/await with try/catch for proper"
                                " error handling."
                            ),
                            evidence_locator=f"{file_path}:{chain['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="nodejs-promise-no-catch",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "nodejs-promise-no-catch",
                    js_evidence[0],
                    summary="All .then() chains have proper .catch() handling.",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "nodejs-promise-no-catch" not in rule_registry:
        rule_registry.register("nodejs-promise-no-catch", NodejsPromiseNoCatchRule())


_register()

__all__ = ["NodejsPromiseNoCatchRule"]
