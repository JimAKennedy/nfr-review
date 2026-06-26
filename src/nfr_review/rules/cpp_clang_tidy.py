# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-TOOL-002 — checks for .clang-tidy config presence."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.repo_structure import RepoStructureSummaryPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import make_green_finding


class CppClangTidyRule(FieldRule[RepoStructureSummaryPayload]):
    id = "cpp-clang-tidy"
    collector_name = "repo-structure"
    evidence_kind = "repo-structure-summary"
    payload_type = RepoStructureSummaryPayload
    pattern_tag = "cpp-clang-tidy-missing"
    required_tech = ["cpp"]
    default_confidence = 0.9
    all_clear_summary = ".clang-tidy config found — static analysis configured."

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [
            e
            for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no repo-structure-summary evidence available",
            )

        all_files: set[str] = set()
        for ev in relevant:
            payload = self._coerce(ev.payload)
            for f in payload.top_level_files:
                all_files.add(f if isinstance(f, str) else "")

        has_tidy = any(f.endswith(".clang-tidy") for f in all_files)

        if has_tidy:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "cpp-clang-tidy-present",
                        relevant[0],
                        summary=".clang-tidy config found — static analysis configured.",
                        confidence=0.95,
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_finding(
                    rule_id=self.id,
                    hit=Hit(
                        rag="amber",
                        severity="low",
                        summary=(
                            "No .clang-tidy config found — static analysis not configured."
                        ),
                        recommendation=(
                            "Add a .clang-tidy file to enable clang-tidy static analysis."
                        ),
                        locator="project-wide",
                    ),
                    ev=relevant[0],
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                )
            ],
        )


__all__ = ["CppClangTidyRule"]
