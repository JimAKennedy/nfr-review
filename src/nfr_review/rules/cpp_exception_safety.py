# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-003 — detects exception safety issues: catch-all without rethrow."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class CppExceptionSafetyRule:
    id = "cpp-exception-safety"
    band: Band = 1
    required_collectors: list[str] = ["cpp-ast"]
    required_tech: list[str] = ["cpp"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        cpp_ev = [e for e in evidence if e.kind == "cpp-ast-file"]
        if not cpp_ev:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no cpp-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in cpp_ev:
            for block in ev.payload.get("catch_blocks", []):
                caught = block.get("caught_type", "")
                rethrows = block.get("rethrows", False)
                if "..." in caught and not rethrows:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary="catch(...) without rethrow",
                            recommendation=(
                                "Catch specific exception types or rethrow with 'throw;' "
                                "to avoid silently swallowing errors."
                            ),
                            evidence_locator=f"{block['file']}:{block['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="cpp-catch-all-silent",
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No exception safety issues detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=cpp_ev[0].collector_name,
                    collector_version=cpp_ev[0].collector_version,
                    confidence=0.85,
                    pattern_tag="cpp-exception-safety-ok",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "cpp-exception-safety" not in rule_registry:
        rule_registry.register("cpp-exception-safety", CppExceptionSafetyRule())


_register()

__all__ = ["CppExceptionSafetyRule"]
