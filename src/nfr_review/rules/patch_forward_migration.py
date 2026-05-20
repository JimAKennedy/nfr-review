"""Rule: PATCH-ROLL-003 — forward-only migration detection.

Checks the repo-structure-summary evidence for common migration directories
(db/migrate, migrations, alembic, flyway, liquibase) in top_level_dirs.
When migration dirs are found, scans top-level entries for evidence of
rollback support (down migration files, rollback scripts).

* GREEN   if rollback evidence is present, or no migration dirs exist.
* AMBER   if migration tooling is found but no rollback evidence detected.
* SKIPPED when no repo-structure-summary evidence is available.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_MIGRATION_DIRS = {
    "db",
    "migrate",
    "migrations",
    "alembic",
    "flyway",
    "liquibase",
    "db-migrations",
    "db_migrations",
    "sql",
}

_ROLLBACK_DIRS = {"rollback", "rollbacks", "revert", "down"}

_ROLLBACK_FILES_LOWER = {
    "rollback.sql",
    "rollback.py",
    "down.sql",
    "revert.sql",
    "rollback.sh",
    "undo.sql",
}

_ROLLBACK_KEYWORDS = ("rollback", "revert", "undo", "down_revision")


class ForwardOnlyMigrationRule:
    """Detect migration tooling without rollback evidence."""

    id = "PATCH-ROLL-003"
    band: Band = 2
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
        top_dirs: list[str] = ev.payload.get("top_level_dirs", [])
        top_files: list[str] = ev.payload.get("top_level_files", [])

        migration_dirs = [d for d in top_dirs if d.lower() in _MIGRATION_DIRS]

        if not migration_dirs:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary="No migration directories detected",
                        recommendation=(
                            "No action required — no database migration"
                            " tooling found at the repo root."
                        ),
                        evidence_locator="repo-root",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="patch-forward-migration",
                    )
                ],
            )

        rollback_evidence: list[str] = []

        for d in top_dirs:
            if d.lower() in _ROLLBACK_DIRS:
                rollback_evidence.append(f"dir:{d}")

        for f in top_files:
            if f.lower() in _ROLLBACK_FILES_LOWER:
                rollback_evidence.append(f"file:{f}")
            elif any(kw in f.lower() for kw in _ROLLBACK_KEYWORDS):
                rollback_evidence.append(f"file:{f}")

        findings: list[Finding] = []

        if rollback_evidence:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        "Migration rollback evidence found: " + ", ".join(rollback_evidence)
                    ),
                    recommendation=(
                        "No action required — rollback support detected"
                        " alongside migration tooling."
                    ),
                    evidence_locator=", ".join(migration_dirs),
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.85,
                    pattern_tag="patch-forward-migration",
                )
            )
        else:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        "Migration tooling detected without rollback"
                        " evidence: " + ", ".join(migration_dirs)
                    ),
                    recommendation=(
                        "Add down-migration scripts, rollback procedures,"
                        " or a rollback/ directory to ensure database"
                        " changes can be safely reversed."
                    ),
                    evidence_locator=", ".join(migration_dirs),
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.80,
                    pattern_tag="patch-forward-migration",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-ROLL-003" not in rule_registry:
        rule_registry.register("PATCH-ROLL-003", ForwardOnlyMigrationRule())


_register()

__all__ = ["ForwardOnlyMigrationRule"]
