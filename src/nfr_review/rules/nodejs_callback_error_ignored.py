# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: nodejs-callback-error-ignored — detects callbacks that ignore the error parameter."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class NodejsCallbackErrorIgnoredRule:
    """Flag Node.js callbacks that receive an error parameter but never check it."""

    id = "nodejs-callback-error-ignored"
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
            file_path = ev.payload.file_path
            for cb in ev.payload.callback_patterns:
                if not cb["checks_error"]:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Callback ignores error parameter '{cb['callback_param']}'"
                            ),
                            recommendation=(
                                "Check the error parameter and handle or propagate"
                                " it. Ignored errors cause silent failures."
                            ),
                            evidence_locator=f"{file_path}:{cb['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="nodejs-callback-error-ignored",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "nodejs-callback-error-ignored",
                    js_evidence[0],
                    summary="No ignored callback errors detected.",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "nodejs-callback-error-ignored" not in rule_registry:
        rule_registry.register(
            "nodejs-callback-error-ignored", NodejsCallbackErrorIgnoredRule()
        )


_register()

__all__ = ["NodejsCallbackErrorIgnoredRule"]
