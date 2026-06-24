# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-TOOL-002 — checks for .clang-tidy config presence."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


@register
class CppClangTidyRule:
    id = "cpp-clang-tidy"
    band: Band = 1
    required_collectors: list[str] = ["repo-structure"]
    required_tech: list[str] = ["cpp"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        repo_ev = filter_evidence(evidence, "repo-structure")
        if not repo_ev:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no repo-structure evidence available",
            )

        all_files: set[str] = set()
        for ev in repo_ev:
            for f in getattr(ev.payload, "files", []):
                all_files.add(f if isinstance(f, str) else f.get("path", ""))
            for f in getattr(ev.payload, "top_level_files", []):
                all_files.add(f if isinstance(f, str) else f.get("path", ""))

        has_tidy = any(f.endswith(".clang-tidy") for f in all_files)

        if has_tidy:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "cpp-clang-tidy-present",
                        repo_ev[0],
                        summary=".clang-tidy config found — static analysis configured.",
                        confidence=0.95,
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="low",
                    summary="No .clang-tidy config found — static analysis not configured.",
                    recommendation=(
                        "Add a .clang-tidy file to enable clang-tidy static analysis."
                    ),
                    evidence_locator="project-wide",
                    collector_name=repo_ev[0].collector_name,
                    collector_version=repo_ev[0].collector_version,
                    confidence=0.9,
                    pattern_tag="cpp-clang-tidy-missing",
                )
            ],
        )


__all__ = ["CppClangTidyRule"]
