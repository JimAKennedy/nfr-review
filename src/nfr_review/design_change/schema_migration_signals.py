# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""MetricExtractor implementation for database schema change detection signals."""

from __future__ import annotations

from nfr_review.design_change.extractors import extractor_registry
from nfr_review.design_change.models import MetricCategory, NumericMetric, SetMetric
from nfr_review.models import Evidence

_DEPS_KINDS = frozenset(
    {
        "java-deps",
        "python-deps",
        "go-deps",
        "nodejs-deps",
        "csharp-deps",
    }
)

_AST_KINDS = frozenset(
    {
        "java-ast-file",
        "python-ast-file",
        "go-ast-file",
        "cpp-ast-file",
    }
)

_MIGRATION_DEP_KEYWORDS: dict[str, str] = {
    "flyway": "flyway",
    "alembic": "alembic",
    "liquibase": "liquibase",
    "dbmate": "dbmate",
    "knex": "knex",
    "prisma-migrate": "prisma",
    "django-migrations": "django",
    "golang-migrate": "golang-migrate",
    "goose": "goose",
}

_MIGRATION_PATH_SEGMENTS: list[str] = [
    "/db/migration/",
    "/alembic/versions/",
    "/migrations/versions/",
    "/database/migrations/",
    "/migrations/",
]


class SchemaMigrationExtractor:
    """Extracts database schema migration signals from dependency and AST evidence.

    Detects migration tools from dependency names (e.g. ``flyway-core``,
    ``alembic``) and migration files from AST evidence file paths matching
    known migration directory patterns.
    """

    @property
    def category(self) -> str:
        return "schema_migration"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        migrations: set[str] = set()

        for ev in evidence:
            if ev.kind in _DEPS_KINDS:
                for dep in ev.payload.dependencies:
                    name_lower = dep.name.lower()
                    for keyword, label in _MIGRATION_DEP_KEYWORDS.items():
                        if keyword in name_lower:
                            migrations.add(f"tool:{label}")
                            break

            elif ev.kind in _AST_KINDS:
                file_path = getattr(ev.payload, "file_path", "")
                if not file_path:
                    continue
                normalised = "/" + file_path.replace("\\", "/").lstrip("/")
                for segment in _MIGRATION_PATH_SEGMENTS:
                    if segment in normalised:
                        migrations.add(f"file:{file_path}")
                        break

        if not migrations:
            return MetricCategory(category=self.category)

        return MetricCategory(
            category=self.category,
            numeric_metrics={
                "schema_migration_count": NumericMetric(
                    name="schema_migration_count",
                    value=float(len(migrations)),
                ),
            },
            set_metrics={
                "schema_migrations": SetMetric(
                    name="schema_migrations",
                    items=sorted(migrations),
                ),
            },
        )


def _register() -> None:
    ext = SchemaMigrationExtractor()
    if ext.category not in extractor_registry:
        extractor_registry.register(ext.category, ext)


_register()

__all__ = ["SchemaMigrationExtractor"]
