# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: go-goroutine-leak — flags goroutine launches that may leak."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class GoGoroutineLeakRule:
    """Flag goroutine launches without explicit lifecycle management."""

    id = "go-goroutine-leak"
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
            file_path = ev.payload.file_path
            for launch in ev.payload.goroutine_launches:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary="Goroutine launch may leak without lifecycle management",
                        recommendation=(
                            "Use context.Context, sync.WaitGroup, or errgroup"
                            " for goroutine lifecycle management."
                        ),
                        evidence_locator=f"{file_path}:{launch['line']}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="go-goroutine-leak",
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "go-goroutine-leak",
                    go_evidence[0],
                    summary="No goroutine launches detected.",
                    confidence=0.8,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "go-goroutine-leak" not in rule_registry:
        rule_registry.register("go-goroutine-leak", GoGoroutineLeakRule())


_register()

__all__ = ["GoGoroutineLeakRule"]
