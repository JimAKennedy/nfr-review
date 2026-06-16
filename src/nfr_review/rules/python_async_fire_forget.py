# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: python-async-fire-and-forget — detects fire-and-forget async patterns."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class PythonAsyncFireForgetRule:
    """Flag asyncio.create_task() calls where the returned Task is not stored."""

    id = "python-async-fire-and-forget"
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
            for call in ev.payload.async_calls:
                if not call["stored"]:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=f"Fire-and-forget {call['call']}()",
                            recommendation=(
                                "Store Task reference and add done_callback"
                                " for error handling; GC can collect unstored tasks."
                            ),
                            evidence_locator=f"{file_path}:{call['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="async-fire-and-forget",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "async-fire-and-forget",
                    py_evidence[0],
                    summary="No fire-and-forget async patterns detected.",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "python-async-fire-and-forget" not in rule_registry:
        rule_registry.register("python-async-fire-and-forget", PythonAsyncFireForgetRule())


_register()

__all__ = ["PythonAsyncFireForgetRule"]
