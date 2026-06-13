# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: go-error-ignored — detects ignored error return values in Go code."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class GoErrorIgnoredRule:
    """Flag Go error return values that are explicitly ignored via blank identifier."""

    id = "go-error-ignored"
    band: Band = 1
    required_collectors: list[str] = ["go-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        go_evidence = filter_evidence(evidence, "go-ast", "go-ast-file")
        if not go_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no go-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in go_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for entry in ev.payload.get("error_assignments", []):
                if entry["error_ignored"]:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=f"Ignored error from {entry['call']}()",
                            recommendation=(
                                "Handle the error or explicitly document why"
                                " it is safe to ignore."
                            ),
                            evidence_locator=f"{file_path}:{entry['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="go-error-ignored",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "go-error-ignored",
                    go_evidence[0],
                    summary="No ignored error return values detected.",
                    confidence=0.9,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "go-error-ignored" not in rule_registry:
        rule_registry.register("go-error-ignored", GoErrorIgnoredRule())


_register()

__all__ = ["GoErrorIgnoredRule"]
