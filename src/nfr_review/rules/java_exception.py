# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: exception-handling-antipattern — catches broad Exception/Throwable without rethrow."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult, compute_content_hash
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_BROAD_TYPES = frozenset({"Exception", "Throwable"})


class ExceptionHandlingAntipatternRule:
    """Flag catch blocks that swallow Exception/Throwable without rethrowing."""

    id = "exception-handling-antipattern"
    band: Band = 1
    required_collectors: list[str] = ["java-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_evidence = [
            e for e in evidence if e.collector_name == "java-ast" and e.kind == "java-ast-file"
        ]
        if not java_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in java_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for block in ev.payload.get("catch_blocks", []):
                if block["caught_type"] in _BROAD_TYPES and not block["rethrows"]:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="high",
                            summary=(f"Broad catch({block['caught_type']}) without rethrow"),
                            recommendation=(
                                "Catch specific exception types or"
                                " rethrow to preserve stack trace"
                                " visibility."
                            ),
                            evidence_locator=(f"{file_path}:{block['line']}"),
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="exception-handling",
                            content_hash=compute_content_hash(
                                block.get("body_text", block["caught_type"])
                            ),
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No broad exception swallowing detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=java_evidence[0].collector_name,
                    collector_version=java_evidence[0].collector_version,
                    confidence=0.85,
                    pattern_tag="exception-handling",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "exception-handling-antipattern" not in rule_registry:
        rule_registry.register(
            "exception-handling-antipattern", ExceptionHandlingAntipatternRule()
        )


_register()

__all__ = ["ExceptionHandlingAntipatternRule"]
