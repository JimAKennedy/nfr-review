# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-COM-001: README presence and quality check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band

_STUB_THRESHOLD = 200

_REQUIRED_SECTIONS = frozenset(
    {
        "installation",
        "install",
        "setup",
        "usage",
        "quickstart",
        "getting started",
        "license",
    }
)

_RECOMMENDED_SECTIONS = frozenset(
    {
        "contributing",
        "examples",
        "example",
        "api",
        "api reference",
    }
)


class ReadmePresenceRule:
    id = "HYG-COM-001"
    band: Band = 1
    required_collectors: list[str] = ["community"]
    category = "community"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "community-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no community-analysis evidence available",
            )

        info = ev.payload.get("readme", {})
        exists = info.get("exists", False)
        size = info.get("size", 0)
        locator = info.get("path") or ev.locator

        findings: list[Finding] = []

        if not exists:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="red",
                    severity="high",
                    summary="No README file found at the repository root.",
                    recommendation=(
                        "Add a README.md documenting project purpose, setup, and usage."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=1.0,
                    pattern_tag="readme-presence",
                )
            )
            return RuleResult(rule_id=self.id, findings=findings)

        if size < _STUB_THRESHOLD:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=f"README exists but is only {size} bytes — likely a stub.",
                    recommendation=(
                        "Expand the README with setup instructions, "
                        "usage examples, and contribution guidelines."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=1.0,
                    pattern_tag="readme-presence",
                )
            )
            return RuleResult(rule_id=self.id, findings=findings)

        findings.append(
            Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary=f"README found ({size} bytes).",
                recommendation="No action required.",
                evidence_locator=locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=1.0,
                pattern_tag="readme-presence",
            )
        )

        sections = ev.payload.get("readme_sections", {})
        well_known = set(sections.get("well_known_sections", []))

        has_required = bool(well_known & _REQUIRED_SECTIONS)
        if not has_required:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        "README is missing required sections "
                        "(installation/setup, usage, or license)."
                    ),
                    recommendation=(
                        "Add installation, usage, and license sections to the README."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.9,
                    pattern_tag="readme-required-sections",
                )
            )

        has_recommended = bool(well_known & _RECOMMENDED_SECTIONS)
        if not has_recommended:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="low",
                    summary=(
                        "README is missing recommended sections "
                        "(contributing, examples, or API reference)."
                    ),
                    recommendation=(
                        "Consider adding contributing guidelines, "
                        "examples, or API reference sections."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.8,
                    pattern_tag="readme-recommended-sections",
                )
            )

        badges = ev.payload.get("readme_badges", [])
        if not badges:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="README has no CI/coverage/registry badges.",
                    recommendation=(
                        "Consider adding badges for build status, "
                        "test coverage, or package registry."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.7,
                    pattern_tag="readme-badges",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "HYG-COM-001" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-COM-001", ReadmePresenceRule())


_register()

__all__ = ["ReadmePresenceRule"]
