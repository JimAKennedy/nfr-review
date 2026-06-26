# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-TOOL-001 — checks for .clang-format config presence."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.repo_structure import RepoStructureSummaryPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import make_green_finding


class CppClangFormatRule(FieldRule[RepoStructureSummaryPayload]):
    id = "cpp-clang-format"
    collector_name = "repo-structure"
    evidence_kind = "repo-structure-summary"
    payload_type = RepoStructureSummaryPayload
    pattern_tag = "cpp-clang-format-missing"
    required_tech = ["cpp"]
    default_confidence = 0.9
    all_clear_summary = ".clang-format config found — code formatting standardized."

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

        has_format = any(
            f.endswith(".clang-format") or f.endswith("_clang-format") for f in all_files
        )

        if has_format:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "cpp-clang-format-present",
                        relevant[0],
                        summary=".clang-format config found — code formatting standardized.",
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
                            "No .clang-format config found — code formatting"
                            " may be inconsistent."
                        ),
                        recommendation=(
                            "Add a .clang-format file to standardize code formatting."
                        ),
                        locator="project-wide",
                    ),
                    ev=relevant[0],
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                )
            ],
        )


__all__ = ["CppClangFormatRule"]
