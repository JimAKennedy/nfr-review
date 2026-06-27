# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-DOC-001: Package metadata completeness check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

_KEY_FIELDS = ("description", "license", "urls", "homepage")


class PkgMetadataRule:
    id = "HYG-DOC-001"
    band: Band = 1
    required_collectors: list[str] = ["documentation"]
    category = "documentation"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "documentation-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no documentation-analysis evidence available",
            )

        manifests: list[dict[str, Any]] = ev.payload.manifests

        if not manifests:
            finding = Finding(
                rule_id=self.id,
                rag="red",
                severity="high",
                summary=(
                    "No package manifest found"
                    " (pyproject.toml, package.json, CMakeLists.txt, etc.)."
                ),
                recommendation=(
                    "Add a pyproject.toml, package.json, CMakeLists.txt,"
                    " or other manifest with project metadata."
                ),
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=1.0,
                pattern_tag="pkg-metadata-missing",
            )
            return RuleResult(rule_id=self.id, findings=[finding])

        findings: list[Finding] = []

        for manifest in manifests:
            missing = manifest.get("fields_missing", [])
            key_missing = [f for f in missing if f in _KEY_FIELDS]

            if len(key_missing) > 2:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Missing {len(key_missing)} key metadata fields"
                            f" ({', '.join(key_missing)})."
                        ),
                        recommendation=f"Add missing fields to {manifest['path']}.",
                        evidence_locator=manifest.get("path", ev.locator),
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=1.0,
                        pattern_tag="pkg-metadata-completeness",
                    )
                )
            elif key_missing:
                findings.append(
                    make_green_finding(
                        self.id,
                        "pkg-metadata-completeness",
                        ev,
                        summary=(
                            f"{len(key_missing)} non-critical metadata field(s) missing"
                            f" ({', '.join(key_missing)})."
                        ),
                        recommendation="No urgent action required.",
                        evidence_locator=manifest.get("path", ev.locator),
                        confidence=1.0,
                    )
                )
            else:
                findings.append(
                    make_green_finding(
                        self.id,
                        "pkg-metadata-completeness",
                        ev,
                        summary="All key metadata fields present.",
                        evidence_locator=manifest.get("path", ev.locator),
                        confidence=1.0,
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "pkg-metadata-completeness",
                    ev,
                    summary="Package metadata present.",
                    evidence_locator=ev.locator,
                    confidence=1.0,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "HYG-DOC-001" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-DOC-001", PkgMetadataRule())


_register()

__all__ = ["PkgMetadataRule"]
