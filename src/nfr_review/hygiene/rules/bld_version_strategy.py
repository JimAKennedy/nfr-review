# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-BLD-002: Version declaration and SemVer validation."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

_SEMVER_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*)?$"
)


def is_semver(version: str) -> bool:
    return bool(_SEMVER_RE.match(version))


class VersionStrategyRule:
    id = "HYG-BLD-002"
    band: Band = 1
    required_collectors: list[str] = ["build-readiness"]
    category = "build-readiness"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "build-readiness-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no build-readiness-analysis evidence available",
            )

        info = ev.payload.get("version", {})
        declared = info.get("declared", False)

        findings: list[Finding] = []

        if not declared:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        "No version declared (checked pyproject.toml, setup.py/cfg, "
                        "package __init__.py, pom.xml, build.gradle(.kts), go.mod, "
                        "Cargo.toml, *.csproj)."
                    ),
                    recommendation=(
                        "Declare a version: [project].version in pyproject.toml (Python), "
                        "<version> in pom.xml (JVM), version in Cargo.toml (Rust), "
                        "or <Version> in *.csproj (C#)."
                    ),
                    evidence_locator=info.get("source") or ev.locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=1.0,
                    pattern_tag="version-strategy",
                )
            )
        else:
            source = info.get("source", "unknown")
            value = info.get("value", "?")

            # Strategy markers like "(dynamic)" or "(git-tags)" are not
            # concrete versions — skip SemVer validation for those.
            is_strategy_marker = value.startswith("(") and value.endswith(")")

            if is_strategy_marker or is_semver(value):
                findings.append(
                    make_green_finding(
                        self.id,
                        "version-strategy",
                        ev,
                        summary=f"Version {value} declared in {source}.",
                        evidence_locator=info.get("source") or ev.locator,
                        confidence=1.0,
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="low",
                        summary=(
                            f"Version '{value}' in {source} does not follow "
                            "Semantic Versioning (MAJOR.MINOR.PATCH)."
                        ),
                        recommendation=(
                            "Adopt SemVer (https://semver.org): use MAJOR.MINOR.PATCH "
                            "with optional pre-release suffix (e.g. 1.0.0-alpha.1)."
                        ),
                        evidence_locator=info.get("source") or ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=1.0,
                        pattern_tag="version-strategy",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "HYG-BLD-002" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-BLD-002", VersionStrategyRule())


_register()

__all__ = ["VersionStrategyRule"]
