# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dep-freshness — graduated staleness and dead library detection for dependencies."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from packaging.version import InvalidVersion, Version

from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import make_green_finding

_CONSTRAINT_RE = re.compile(r"^[><=!~^]+\s*")

_DEPS_KINDS = frozenset(
    {
        "python-deps",
        "nodejs-deps",
        "java-deps",
        "go-deps",
        "csharp-deps",
    }
)

_DEAD_LIBRARY_MONTHS = 12


def _strip_constraint(raw: str) -> str:
    return _CONSTRAINT_RE.sub("", raw).strip()


def _parse_version(raw: str) -> Version | None:
    try:
        return Version(raw)
    except InvalidVersion:
        return None


def _months_since(iso_date: str, now: datetime) -> float | None:
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    delta = now - dt
    return delta.days / 30.44


@register
class DepFreshnessRule:
    """Graduated staleness and dead library detection across all dependency ecosystems."""

    id = "dep-freshness"
    band: Band = 2
    required_collectors: list[str] = [
        "python-deps",
        "nodejs-deps",
        "java-deps",
        "go-deps",
        "csharp-deps",
    ]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        dep_evidence = [
            e
            for e in evidence
            if e.kind in _DEPS_KINDS and e.collector_name in self.required_collectors
        ]
        if not dep_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no dependency evidence available",
            )

        now = datetime.now(UTC)
        findings: list[Finding] = []

        for ev in dep_evidence:
            for dep in ev.payload.dependencies:
                dep_findings = self._assess_dep(dep, ev, now)
                findings.extend(dep_findings)

        if not findings:
            first = dep_evidence[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "dep-freshness-ok",
                    first,
                    summary="All dependencies are up to date.",
                    confidence=0.9,
                    evidence_locator="all-dependencies",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)

    def _assess_dep(
        self,
        dep: dict[str, Any],
        ev: Evidence,
        now: datetime,
    ) -> list[Finding]:
        findings: list[Finding] = []
        name: str = dep.get("name", "unknown")
        status = dep.get("deps_dev_status", "")

        if status != "ok":
            return findings

        release_date = dep.get("latest_release_date")
        if release_date:
            months = _months_since(release_date, now)
            if months is not None and months > _DEAD_LIBRARY_MONTHS:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Library '{name}' has had no release in"
                            f" {int(months)} months — may be abandoned."
                        ),
                        recommendation=(
                            "Evaluate whether this library is still maintained."
                            " Consider migrating to an actively maintained alternative."
                        ),
                        evidence_locator=f"dep:{ev.collector_name}:{name}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="dead-library",
                    )
                )

        declared_raw = dep.get("declared_version")
        latest_raw = dep.get("latest_version")
        if not declared_raw or not latest_raw:
            return findings

        declared_clean = _strip_constraint(declared_raw)
        declared_ver = _parse_version(declared_clean)
        latest_ver = _parse_version(latest_raw)
        if declared_ver is None or latest_ver is None:
            return findings

        staleness = self._classify_drift(declared_ver, latest_ver)
        if staleness is None:
            return findings

        rag, severity, tag, label = staleness
        findings.append(
            Finding(
                rule_id=self.id,
                rag=rag,
                severity=severity,
                summary=(
                    f"Dependency '{name}' is at {declared_clean}"
                    f" but latest is {latest_raw} ({label} drift)."
                ),
                recommendation=(
                    f"Update '{name}' to {latest_raw} to pick up"
                    f" bug fixes and security patches."
                ),
                evidence_locator=f"dep:{ev.collector_name}:{name}",
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.85,
                pattern_tag=tag,
            )
        )
        return findings

    @staticmethod
    def _classify_drift(
        declared: Version, latest: Version
    ) -> tuple[RAG, Severity, str, str] | None:
        if declared >= latest:
            return None
        if declared.major < latest.major:
            return ("red", "high", "stale-dep-major", "major")
        if declared.minor < latest.minor:
            return ("amber", "medium", "stale-dep-minor", "minor")
        if declared.micro < latest.micro:
            return ("green", "info", "stale-dep-patch", "patch")
        return None


__all__ = ["DepFreshnessRule"]
