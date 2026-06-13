# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-ROLL-001 — rollback documentation presence.

Checks the repo-structure-summary evidence for rollback-related documentation
at the top level of the repository:

* Files (case-insensitive): ROLLBACK.md, disaster-recovery.md
* Dirs  (case-insensitive): runbooks, rollback, disaster-recovery

* GREEN   if any rollback documentation is detected.
* AMBER   if none of the above are found.
* SKIPPED when no repo-structure-summary evidence is available.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_ROLLBACK_FILES = {"rollback.md", "disaster-recovery.md"}
_ROLLBACK_DIRS = {"runbooks", "rollback", "disaster-recovery"}


def _has_k8s_workloads(evidence: list[Evidence]) -> bool:
    return any(
        (e.collector_name == "k8s-manifest" and e.kind == "k8s-resource")
        or e.kind == "patch-config"
        for e in evidence
    )


class RollbackDocsMissingRule:
    """Check for rollback / disaster-recovery documentation in repo root."""

    id = "PATCH-ROLL-001"
    band: Band = 1
    required_collectors: list[str] = ["repo-structure"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summaries = filter_evidence(evidence, "repo-structure", "repo-structure-summary")
        if not summaries:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no repo-structure-summary evidence available",
            )

        if not _has_k8s_workloads(evidence):
            ev = summaries[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-rollback-docs",
                        ev,
                        summary=(
                            "No K8s workloads or patching config detected"
                            " — rollback docs check not applicable"
                        ),
                        confidence=0.80,
                        evidence_locator="repo-root",
                    )
                ],
            )

        ev = summaries[0]
        top_files: list[str] = ev.payload.get("top_level_files", [])
        top_dirs: list[str] = ev.payload.get("top_level_dirs", [])

        matched: list[str] = []

        for f in top_files:
            if f.lower() in _ROLLBACK_FILES:
                matched.append(f)

        for d in top_dirs:
            if d.lower() in _ROLLBACK_DIRS:
                matched.append(d)

        findings: list[Finding] = []

        if not matched:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary="No rollback documentation detected",
                    recommendation=(
                        "Add a ROLLBACK.md or disaster-recovery.md at the repo root, "
                        "or create a runbooks/ directory with rollback procedures."
                    ),
                    evidence_locator="repo-root",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.85,
                    pattern_tag="patch-rollback-docs",
                )
            )
        else:
            for name in matched:
                findings.append(
                    make_green_finding(
                        self.id,
                        "patch-rollback-docs",
                        ev,
                        summary=f"Rollback documentation found: {name}",
                        recommendation=(
                            "No action required — rollback documentation is present."
                        ),
                        confidence=0.90,
                        evidence_locator=name,
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-ROLL-001" not in rule_registry:
        rule_registry.register("PATCH-ROLL-001", RollbackDocsMissingRule())


_register()

__all__ = ["RollbackDocsMissingRule"]
