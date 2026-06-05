# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: spring-profile-misconfiguration — flags production profiles with debug settings."""

from __future__ import annotations

from typing import Any, cast

from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_PROD_PROFILES = frozenset({"prod", "production", "prd"})
_DEBUG_LEVELS = frozenset({"debug", "trace"})
_INMEMORY_DB_MARKERS = frozenset({"h2:", "mem:", "hsqldb:", "derby:"})


class SpringProfileMisconfigurationRule:
    """Flag production profiles with debug logging, in-memory DBs, or show-sql."""

    id = "spring-profile-misconfiguration"
    band: Band = 1
    required_collectors: list[str] = ["spring-config"]
    required_tech: list[str] = ["spring_boot"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        spring_evidence = [
            e
            for e in evidence
            if e.collector_name == "spring-config" and e.kind == "spring-config-file"
        ]
        if not spring_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no spring-config evidence available",
            )

        prod_evidence = [
            e
            for e in spring_evidence
            if e.payload.get("profile") and e.payload["profile"].lower() in _PROD_PROFILES
        ]
        base_evidence = [e for e in spring_evidence if not e.payload.get("profile")]

        if not prod_evidence:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary="No production profile config found to check.",
                        recommendation="No action required.",
                        evidence_locator=spring_evidence[0].payload.get(
                            "file_path", spring_evidence[0].locator
                        ),
                        collector_name=spring_evidence[0].collector_name,
                        collector_version=spring_evidence[0].collector_version,
                        confidence=0.7,
                        pattern_tag="profile-config",
                    )
                ],
            )

        findings: list[Finding] = []

        for ev in prod_evidence:
            payload = ev.payload
            file_path = payload.get("file_path", ev.locator)
            issues = _check_prod_issues(payload)

            if not issues and base_evidence:
                issues = _check_inherited_issues(base_evidence[0].payload, payload)

            for issue in issues:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag=cast(RAG, issue["rag"]),
                        severity=cast(Severity, issue["severity"]),
                        summary=issue["summary"],
                        recommendation=issue["recommendation"],
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="profile-config",
                    )
                )

        if not findings:
            file_path = prod_evidence[0].payload.get("file_path", prod_evidence[0].locator)
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary="Production profile has appropriate settings.",
                        recommendation="No action required.",
                        evidence_locator=file_path,
                        collector_name=prod_evidence[0].collector_name,
                        collector_version=prod_evidence[0].collector_version,
                        confidence=0.8,
                        pattern_tag="profile-config",
                    )
                ],
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _check_prod_issues(payload: dict[str, Any] | Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    logging_section = payload.get("logging", {}) or {}

    if _has_debug_logging(logging_section):
        issues.append(
            {
                "rag": "amber",
                "severity": "medium",
                "summary": "Production profile has debug-level logging",
                "recommendation": (
                    "Set logging level to INFO or WARN for production."
                    " Debug logging degrades performance and may leak sensitive data."
                ),
            }
        )

    _check_datasource(payload, issues)
    _check_show_sql(payload, issues)

    return issues


def _has_debug_logging(logging_section: dict[str, Any]) -> bool:
    level = logging_section.get("level", {})
    if isinstance(level, dict):
        for val in level.values():
            if str(val).lower() in _DEBUG_LEVELS:
                return True
    elif isinstance(level, str) and level.lower() in _DEBUG_LEVELS:
        return True
    root_level = logging_section.get("root")
    if isinstance(root_level, str) and root_level.lower() in _DEBUG_LEVELS:
        return True
    return False


def _check_datasource(payload: dict[str, Any], issues: list[dict[str, str]]) -> None:
    raw_values = _flatten_values(payload).lower()
    if any(marker in raw_values for marker in _INMEMORY_DB_MARKERS):
        issues.append(
            {
                "rag": "red",
                "severity": "high",
                "summary": "Production profile uses in-memory database",
                "recommendation": (
                    "Replace H2/HSQLDB/Derby in-memory database"
                    " with a persistent database for production."
                ),
            }
        )


def _check_show_sql(payload: dict[str, Any], issues: list[dict[str, str]]) -> None:
    spring = payload.get("spring", {})
    if not isinstance(spring, dict):
        return
    jpa = spring.get("jpa", {})
    if not isinstance(jpa, dict):
        return
    show_sql = jpa.get("show-sql", jpa.get("show_sql"))
    if show_sql is not None and str(show_sql).lower() == "true":
        issues.append(
            {
                "rag": "amber",
                "severity": "medium",
                "summary": "Production profile has show-sql enabled",
                "recommendation": (
                    "Disable spring.jpa.show-sql in production."
                    " SQL logging degrades performance and may"
                    " leak query details."
                ),
            }
        )


def _check_inherited_issues(
    base_payload: dict[str, Any] | Any,
    prod_payload: dict[str, Any] | Any,
) -> list[dict[str, str]]:
    """Check if base config has debug settings not overridden by prod."""
    issues: list[dict[str, str]] = []
    base_logging = base_payload.get("logging", {}) or {}
    prod_logging = prod_payload.get("logging", {}) or {}

    if _has_debug_logging(base_logging) and not prod_logging:
        issues.append(
            {
                "rag": "amber",
                "severity": "medium",
                "summary": (
                    "Base config has debug logging not overridden by production profile"
                ),
                "recommendation": (
                    "Override logging levels in the production profile"
                    " to avoid inheriting debug-level logging."
                ),
            }
        )

    return issues


def _flatten_values(d: dict[str, Any]) -> str:
    parts: list[str] = []
    for v in d.values():
        if isinstance(v, dict):
            parts.append(_flatten_values(v))
        else:
            parts.append(str(v))
    return " ".join(parts)


def _register() -> None:
    if "spring-profile-misconfiguration" not in rule_registry:
        rule_registry.register(
            "spring-profile-misconfiguration", SpringProfileMisconfigurationRule()
        )


_register()

__all__ = ["SpringProfileMisconfigurationRule"]
