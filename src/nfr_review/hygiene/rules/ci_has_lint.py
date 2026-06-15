# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-CI-003: CI lint/format step presence check."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

_LINT_PATTERNS = re.compile(
    r"(?:^|[\s/:\-])"
    r"("
    # General
    r"lint|format"
    # Python
    r"|ruff|black|flake8|pylint|mypy"
    # JavaScript/CSS
    r"|eslint|prettier|stylelint|biome"
    # Go
    r"|golangci-lint"
    # Rust
    r"|clippy"
    # Ruby
    r"|rubocop"
    # JVM (Java/Kotlin)
    r"|checkstyle|spotbugs|pmd|ktlint|detekt|error-?prone|spotless"
    # .NET
    r"|dotnet-format|roslyn"
    r")",
    re.IGNORECASE,
)


class CiHasLintRule:
    id = "HYG-CI-003"
    band: Band = 1
    required_collectors: list[str] = ["ci-automation"]
    category = "ci-automation"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "ci-automation-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ci-automation-analysis evidence available",
            )

        if not ev.payload.get("has_ci", False):
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no CI configuration found",
            )

        configs = ev.payload.get("configs", [])
        found_lint = False

        for cfg in configs:
            for step in cfg.get("steps", []):
                if _LINT_PATTERNS.search(step):
                    found_lint = True
                    break
            if found_lint:
                break

        if not found_lint:
            finding = Finding(
                rule_id=self.id,
                rag="amber",
                severity="medium",
                summary="No lint or format step detected in CI.",
                recommendation=(
                    "Add a linting step (e.g. ruff, eslint, golangci-lint) "
                    "to catch style issues and potential bugs early."
                ),
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.8,
                pattern_tag="ci-has-lint",
            )
        else:
            finding = make_green_finding(
                self.id,
                "ci-has-lint",
                ev,
                summary="Lint/format step detected in CI.",
                evidence_locator=ev.locator,
                confidence=0.8,
            )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-003" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-003", CiHasLintRule())


_register()

__all__ = ["CiHasLintRule"]
