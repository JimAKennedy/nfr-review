# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: nodejs-floating-promise — detects unhandled promise rejections in Node.js code."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class NodejsFloatingPromiseRule:
    """Flag promise chains without .catch() that risk unhandled rejections."""

    id = "nodejs-floating-promise"
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
                            rag="red",
                            severity="high",
                            summary="Floating promise without .catch()",
                            recommendation=(
                                "Add .catch() or use try/await to handle"
                                " rejection. Unhandled promise rejections crash"
                                " Node.js processes."
                            ),
                            evidence_locator=f"{file_path}:{chain['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="nodejs-floating-promise",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "nodejs-floating-promise",
                    js_evidence[0],
                    summary="No floating promises detected.",
                    confidence=0.9,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "nodejs-floating-promise" not in rule_registry:
        rule_registry.register("nodejs-floating-promise", NodejsFloatingPromiseRule())


_register()

__all__ = ["NodejsFloatingPromiseRule"]
