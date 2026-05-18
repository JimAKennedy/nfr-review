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

_ROLLBACK_FILES = {"rollback.md", "disaster-recovery.md"}
_ROLLBACK_DIRS = {"runbooks", "rollback", "disaster-recovery"}


class RollbackDocsMissingRule:
    """Check for rollback / disaster-recovery documentation in repo root."""

    id = "PATCH-ROLL-001"
    band: Band = 1
    required_collectors: list[str] = ["repo-structure"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summaries = [
            e
            for e in evidence
            if e.collector_name == "repo-structure" and e.kind == "repo-structure-summary"
        ]
        if not summaries:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no repo-structure-summary evidence available",
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
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=f"Rollback documentation found: {name}",
                        recommendation=(
                            "No action required — rollback documentation is present."
                        ),
                        evidence_locator=name,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.90,
                        pattern_tag="patch-rollback-docs",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-ROLL-001" not in rule_registry:
        rule_registry.register("PATCH-ROLL-001", RollbackDocsMissingRule())


_register()

__all__ = ["RollbackDocsMissingRule"]
