# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: spring-profile-misconfiguration -- flags production profiles with debug settings."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from nfr_review.collectors.payloads.spring import SpringConfigFilePayload
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import filter_evidence

_PROD_PROFILES = frozenset({"prod", "production", "prd"})
_DEBUG_LEVELS = frozenset({"debug", "trace"})
_INMEMORY_DB_MARKERS = frozenset({"h2:", "mem:", "hsqldb:", "derby:"})


class SpringProfileMisconfigurationRule(FieldRule[SpringConfigFilePayload]):
    """Flag production profiles with debug logging, in-memory DBs, or show-sql."""

    id = "spring-profile-misconfiguration"
    collector_name = "spring-config"
    evidence_kind = "spring-config-file"
    payload_type = SpringConfigFilePayload
    pattern_tag = "profile-config"
    required_tech = ["spring_boot"]
    default_confidence = 0.85
    all_clear_summary = "Production profile has appropriate settings."
    all_clear_recommendation = "No action required."

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        """Override evaluate to handle cross-evidence prod/base filtering."""
        spring_evidence = filter_evidence(evidence, "spring-config", "spring-config-file")
        if not spring_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no spring-config-file evidence available",
            )

        prod_evidence = [
            e
            for e in spring_evidence
            if e.payload.profile and e.payload.profile.lower() in _PROD_PROFILES
        ]
        base_evidence = [e for e in spring_evidence if not e.payload.profile]

        if not prod_evidence:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_finding(
                        rule_id=self.id,
                        hit=Hit(
                            rag="green",
                            summary="No production profile config found to check.",
                            recommendation=self.all_clear_recommendation,
                            locator=spring_evidence[0].payload.file_path,
                        ),
                        ev=spring_evidence[0],
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.7,
                    )
                ],
            )

        findings: list[Finding] = []

        for ev in prod_evidence:
            payload = self._coerce(ev.payload)
            file_path = payload.file_path
            issues = _check_prod_issues(payload)

            if not issues and base_evidence:
                base_payload = self._coerce(base_evidence[0].payload)
                issues = _check_inherited_issues(base_payload, payload)

            for issue in issues:
                findings.append(
                    make_finding(
                        rule_id=self.id,
                        hit=Hit(
                            rag=cast(RAG, issue["rag"]),
                            severity=cast(Severity, issue["severity"]),
                            summary=issue["summary"],
                            recommendation=issue["recommendation"],
                            locator=file_path,
                        ),
                        ev=ev,
                        pattern_tag=self.pattern_tag,
                        default_confidence=self.default_confidence,
                    )
                )

        if not findings:
            file_path = prod_evidence[0].payload.file_path
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_finding(
                        rule_id=self.id,
                        hit=Hit(
                            rag="green",
                            summary=self.all_clear_summary,
                            recommendation=self.all_clear_recommendation,
                            locator=file_path,
                        ),
                        ev=prod_evidence[0],
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.8,
                    )
                ],
            )

        return RuleResult(rule_id=self.id, findings=findings)

    def check(self, payload: SpringConfigFilePayload, ev: Evidence) -> Iterable[Hit]:
        # Not used -- evaluate() is overridden for cross-evidence logic.
        return ()


def _check_prod_issues(
    payload: SpringConfigFilePayload,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    logging_section = payload.logging or {}

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


def _check_datasource(payload: SpringConfigFilePayload, issues: list[dict[str, str]]) -> None:
    raw_values = _flatten_values(payload.model_dump()).lower()
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


def _check_show_sql(payload: SpringConfigFilePayload, issues: list[dict[str, str]]) -> None:
    spring = payload.spring
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
    base_payload: SpringConfigFilePayload,
    prod_payload: SpringConfigFilePayload,
) -> list[dict[str, str]]:
    """Check if base config has debug settings not overridden by prod."""
    issues: list[dict[str, str]] = []
    base_logging = base_payload.logging or {}
    prod_logging = prod_payload.logging or {}

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


__all__ = ["SpringProfileMisconfigurationRule"]
