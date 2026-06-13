# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CMAKE-002 — checks FetchContent dependencies are version-pinned."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import make_green_finding


class CmakeFetchcontentPinningRule:
    id = "cmake-fetchcontent-pinning"
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
        has_any_fetchcontent = False
        for ev in cmake_ev:
            file_path = ev.payload.get("file_path", ev.locator)
            declares = ev.payload.get("fetchcontent_declares", [])
            if not declares:
                continue
            has_any_fetchcontent = True
            for dep in declares:
                if not dep.get("is_pinned"):
                    tag = dep.get("tag", "(none)")
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red" if not dep.get("tag") else "amber",
                            severity="high" if not dep.get("tag") else "medium",
                            summary=(
                                f"FetchContent dependency '{dep['name']}' uses "
                                f"unpinned tag '{tag}' in {file_path}:{dep['line']}"
                            ),
                            recommendation=(
                                f"Pin '{dep['name']}' to a specific version tag "
                                f"or commit hash instead of a branch name."
                            ),
                            evidence_locator=f"{file_path}:{dep['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="cmake-unpinned-fetchcontent",
                        )
                    )

        if not has_any_fetchcontent:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no FetchContent dependencies found",
            )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "cmake-fetchcontent-pinned",
                    cmake_ev[0],
                    summary="All FetchContent dependencies are version-pinned.",
                    confidence=0.9,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "cmake-fetchcontent-pinning" not in rule_registry:
        rule_registry.register("cmake-fetchcontent-pinning", CmakeFetchcontentPinningRule())


_register()

__all__ = ["CmakeFetchcontentPinningRule"]
