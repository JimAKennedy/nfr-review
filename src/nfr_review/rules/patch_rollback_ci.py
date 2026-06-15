# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-ROLL-002 — CI rollback stage presence check.

Scans CI pipeline evidence for rollback/revert/canary-rollback job or step
names.  Flags amber when no CI pipeline includes a rollback-related stage,
green when at least one pipeline does.

* SKIPPED when no ci-pipeline evidence is available.
* AMBER when no pipeline has a rollback-related job or step name.
* GREEN when any pipeline has a matching job or step name.
"""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_ROLLBACK_RE = re.compile(
    r"(rollback|roll[-_]?back|revert|canary[-_]?rollback)", re.IGNORECASE
)


def _has_k8s_workloads(evidence: list[Evidence]) -> bool:
    return any(
        (e.collector_name == "k8s-manifest" and e.kind == "k8s-resource")
        or e.kind == "patch-config"
        for e in evidence
    )


class CiRollbackStageMissingRule:
    """Check that at least one CI pipeline has a rollback/revert stage."""

    id = "PATCH-ROLL-002"
    band: Band = 1
    required_collectors: list[str] = ["ci-artifact"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ci_pipelines = filter_evidence(evidence, "ci-artifact", "ci-pipeline")
        if not ci_pipelines:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ci-pipeline evidence available",
            )

        if not _has_k8s_workloads(evidence):
            first = ci_pipelines[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-rollback-ci",
                        first,
                        summary=(
                            "No K8s workloads or patching config detected"
                            " — CI rollback stage check not applicable"
                        ),
                        confidence=0.80,
                        evidence_locator="all-pipelines",
                    )
                ],
            )

        findings: list[Finding] = []

        for ev in ci_pipelines:
            job_names: list[str] = ev.payload.get("job_names", [])
            step_names: list[str] = ev.payload.get("step_names", [])

            matched = False
            for name in job_names + step_names:
                if _ROLLBACK_RE.search(name):
                    matched = True
                    break

            if matched:
                file_path = ev.payload.get("file_path", ev.locator)
                findings.append(
                    make_green_finding(
                        self.id,
                        "patch-rollback-ci",
                        ev,
                        summary="CI pipeline has a rollback-related stage.",
                        recommendation="No action required — rollback stage detected.",
                        confidence=0.90,
                        evidence_locator=file_path,
                    )
                )

        if not findings:
            first = ci_pipelines[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary="No CI rollback stage detected",
                    recommendation=(
                        "Add a rollback or revert stage to your CI pipeline"
                        " so that failed deployments can be automatically"
                        " rolled back."
                    ),
                    evidence_locator="all-pipelines",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.85,
                    pattern_tag="patch-rollback-ci",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-ROLL-002" not in rule_registry:
        rule_registry.register("PATCH-ROLL-002", CiRollbackStageMissingRule())


_register()

__all__ = ["CiRollbackStageMissingRule"]
