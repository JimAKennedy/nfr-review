# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: thread-pool-misconfiguration — unbounded thread pools without rejection policy."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class ThreadPoolMisconfigurationRule:
    """Flag ThreadPoolExecutor instances without bounded queue or rejection policy."""

    id = "thread-pool-misconfiguration"
    band: Band = 1
    required_collectors: list[str] = ["java-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_evidence = filter_evidence(evidence, "java-ast", "java-ast-file")
        if not java_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in java_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for pool in ev.payload.get("thread_pool_constructions", []):
                if not pool["has_bounded_queue"] or not pool["has_rejection_policy"]:
                    issues: list[str] = []
                    if not pool["has_bounded_queue"]:
                        issues.append("unbounded queue")
                    if not pool["has_rejection_policy"]:
                        issues.append("no rejection policy")
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(f"{pool['class_name']} has {', '.join(issues)}"),
                            recommendation=(
                                "Use a bounded queue (e.g."
                                " ArrayBlockingQueue) and set a"
                                " RejectedExecutionHandler."
                            ),
                            evidence_locator=(f"{file_path}:{pool['line']}"),
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.8,
                            pattern_tag="thread-pool-config",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "thread-pool-config",
                    java_evidence[0],
                    summary="No misconfigured thread pools detected.",
                    confidence=0.8,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "thread-pool-misconfiguration" not in rule_registry:
        rule_registry.register(
            "thread-pool-misconfiguration", ThreadPoolMisconfigurationRule()
        )


_register()

__all__ = ["ThreadPoolMisconfigurationRule"]
