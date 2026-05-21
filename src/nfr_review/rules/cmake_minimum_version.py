# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CMAKE-001 — checks cmake_minimum_required version is present and modern."""

from __future__ import annotations

from typing import Any

from packaging.version import Version

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_MODERN_CMAKE_VERSION = Version("3.14")


class CmakeMinimumVersionRule:
    id = "cmake-minimum-version"
    band: Band = 1
    required_collectors: list[str] = ["cmake"]
    required_tech: list[str] = ["cpp"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        cmake_ev = [e for e in evidence if e.kind == "cmake-config"]
        if not cmake_ev:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no cmake evidence available",
            )

        findings: list[Finding] = []
        for ev in cmake_ev:
            file_path = ev.payload.get("file_path", ev.locator)
            version_str = ev.payload.get("cmake_minimum_required")
            if version_str is None:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=f"cmake_minimum_required is missing in {file_path}",
                        recommendation=(
                            "Add cmake_minimum_required(VERSION 3.21) or later "
                            "to ensure reproducible builds."
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="cmake-no-minimum-version",
                    )
                )
            else:
                try:
                    ver = Version(version_str)
                except Exception:
                    ver = Version("0.0")
                if ver < _MODERN_CMAKE_VERSION:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"cmake_minimum_required is {version_str} in "
                                f"{file_path} — pre-modern CMake"
                            ),
                            recommendation=(
                                "Upgrade to cmake_minimum_required(VERSION 3.14) "
                                "or later for modern CMake target-based workflow."
                            ),
                            evidence_locator=file_path,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="cmake-old-minimum-version",
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="cmake_minimum_required is present and modern.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=cmake_ev[0].collector_name,
                    collector_version=cmake_ev[0].collector_version,
                    confidence=0.95,
                    pattern_tag="cmake-minimum-version-ok",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "cmake-minimum-version" not in rule_registry:
        rule_registry.register("cmake-minimum-version", CmakeMinimumVersionRule())


_register()

__all__ = ["CmakeMinimumVersionRule"]
