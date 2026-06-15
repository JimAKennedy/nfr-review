# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CMAKE-003 — checks for modern CMake build configuration practices."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import make_green_finding


class CmakeBuildConfigRule:
    id = "cmake-build-config"
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

            if ev.payload.get("has_global_cmake_flags"):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            "Global CMAKE_CXX_FLAGS used — prefer target_compile_options"
                        ),
                        recommendation=(
                            "Replace set(CMAKE_CXX_FLAGS ...) with "
                            "target_compile_options() for per-target control."
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="cmake-global-flags",
                    )
                )

            has_target = ev.payload.get("has_target_compile_features") or ev.payload.get(
                "has_target_compile_options"
            )
            if not has_target and not ev.payload.get("has_global_cmake_flags"):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="low",
                        summary=("No target_compile_features or target_compile_options found"),
                        recommendation=(
                            "Use target_compile_features(mylib PUBLIC cxx_std_17) "
                            "to specify C++ standard requirements per target."
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.75,
                        pattern_tag="cmake-no-target-features",
                    )
                )

            if not ev.payload.get("project_version"):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="low",
                        summary="project() missing VERSION",
                        recommendation=(
                            "Add VERSION to project() call for proper versioning: "
                            "project(MyProject VERSION 1.0.0)"
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="cmake-no-project-version",
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "cmake-build-config-ok",
                    cmake_ev[0],
                    summary="CMake build configuration follows modern practices.",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "cmake-build-config" not in rule_registry:
        rule_registry.register("cmake-build-config", CmakeBuildConfigRule())


_register()

__all__ = ["CmakeBuildConfigRule"]
