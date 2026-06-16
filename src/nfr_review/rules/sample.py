# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Sample band-1 rule: README presence check.

Emits a green finding if the repo has any README* file at the root, amber
otherwise. This rule exists primarily to exercise the collector -> rule -> CSV
pipeline end-to-end during S01.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import make_green_finding


class ReadmeExistsRule:
    """Verify a README exists at the repo root.

    Emits a green finding when any README* file is present at the top level of
    the target repository, amber otherwise. Used as the canonical band-1 sample
    rule that exercises the full collector -> rule -> output pipeline.
    """

    id = "sample-readme-exists"
    band: Band = 1
    required_collectors: list[str] = ["repo-structure"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        repo_evidence = next(
            (e for e in evidence if e.collector_name == "repo-structure"),
            None,
        )
        if repo_evidence is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no repo-structure evidence available",
            )

        has_readme = bool(repo_evidence.payload.has_readme)
        readme_name = repo_evidence.payload.readme_name

        if has_readme:
            finding = make_green_finding(
                self.id,
                "readme-presence",
                repo_evidence,
                summary=f"README found at repo root: {readme_name}",
                recommendation="No action required — README is present.",
                evidence_locator=str(readme_name or repo_evidence.locator),
                confidence=1.0,
            )
        else:
            finding = Finding(
                rule_id=self.id,
                rag="amber",
                severity="medium",
                summary="No README* file found at the repository root.",
                recommendation=(
                    "Add a README at the repo root to document setup, usage, "
                    "and contribution guidelines."
                ),
                evidence_locator=repo_evidence.locator,
                collector_name=repo_evidence.collector_name,
                collector_version=repo_evidence.collector_version,
                confidence=1.0,
                pattern_tag="readme-presence",
            )

        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "sample-readme-exists" not in rule_registry:
        rule_registry.register("sample-readme-exists", ReadmeExistsRule())


_register()


__all__ = ["ReadmeExistsRule"]
