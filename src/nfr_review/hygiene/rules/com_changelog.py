# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-COM-005: CHANGELOG presence and format validation."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band

_STUB_THRESHOLD = 50


class ChangelogPresenceRule:
    id = "HYG-COM-005"
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

        info = ev.payload.get("changelog", {})
        exists = info.get("exists", False)
        size = info.get("size", 0)
        locator = info.get("path") or ev.locator

        findings: list[Finding] = []

        if not exists:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary="No CHANGELOG.md, CHANGES.md, or HISTORY.md found.",
                    recommendation=(
                        "Add a changelog to document notable changes between releases."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=1.0,
                    pattern_tag="changelog-presence",
                )
            )
            return RuleResult(rule_id=self.id, findings=findings)

        if size < _STUB_THRESHOLD:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"Changelog exists but is only {size} bytes"
                        " — likely a stub or empty template."
                    ),
                    recommendation=(
                        "Populate the changelog with versioned entries "
                        "documenting notable changes per release."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=1.0,
                    pattern_tag="changelog-stub",
                )
            )
            return RuleResult(rule_id=self.id, findings=findings)

        findings.append(
            Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary=f"Changelog found at {info.get('path')}.",
                recommendation="No action required.",
                evidence_locator=locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=1.0,
                pattern_tag="changelog-presence",
            )
        )

        structure = ev.payload.get("changelog_structure", {})
        has_versions = structure.get("has_versions", False)
        follows_kac = structure.get("follows_keep_a_changelog", False)

        if not has_versions:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="low",
                    summary=(
                        "Changelog has no versioned headers (e.g. ## [1.0.0] - 2024-01-01)."
                    ),
                    recommendation=(
                        "Add version headers following semver to make it easy "
                        "to find changes for a specific release."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.9,
                    pattern_tag="changelog-no-versions",
                )
            )

        if has_versions and not follows_kac:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        "Changelog has version headers but does not use "
                        "Keep a Changelog categories (Added/Changed/Fixed etc.)."
                    ),
                    recommendation=(
                        "Consider adopting Keep a Changelog format with "
                        "standard categories for better readability."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.8,
                    pattern_tag="changelog-no-categories",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "HYG-COM-005" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-COM-005", ChangelogPresenceRule())


_register()

__all__ = ["ChangelogPresenceRule"]
