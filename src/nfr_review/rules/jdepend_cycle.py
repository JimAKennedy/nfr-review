# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: JDEP-CYCLE — flags package dependency cycles detected by JDepend."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class JDepCycleRule:
    """Red finding for any Java package cycle detected by JDepend."""

    id = "JDEP-CYCLE"
    band: Band = 1
    required_collectors: list[str] = ["jdepend"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        jdep_evidence = [e for e in evidence if e.collector_name == "jdepend"]
        if not jdep_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no jdepend evidence available",
            )

        findings: list[Finding] = []

        for ev in jdep_evidence:
            if ev.kind == "jdepend-skip":
                return RuleResult(
                    rule_id=self.id,
                    skipped=True,
                    skip_reason=ev.payload.get("reason", "jdepend unavailable"),
                )

            if ev.kind != "jdepend-packages":
                continue

            cycle_groups = ev.payload.get("cycle_groups", [])
            if not cycle_groups:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary="No package dependency cycles detected.",
                        recommendation="No action required.",
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="jdep-cycle-ok",
                    )
                )
                continue

            for group in cycle_groups:
                packages = group if isinstance(group, list) else [group]
                pkg_list = " → ".join(packages)
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(f"Package dependency cycle detected: {pkg_list}"),
                        recommendation=(
                            "Break the cycle by introducing an interface package or"
                            " inverting the dependency direction. Cyclic dependencies"
                            " prevent independent deployment and testing."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="jdep-cycle-detected",
                    )
                )

        if not findings:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no jdepend-packages evidence found",
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "JDEP-CYCLE" not in rule_registry:
        rule_registry.register("JDEP-CYCLE", JDepCycleRule())


_register()

__all__ = ["JDepCycleRule"]
