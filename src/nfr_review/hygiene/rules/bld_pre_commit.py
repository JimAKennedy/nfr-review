# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-BLD-004: Pre-commit / git hooks presence check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding


class PreCommitRule:
    id = "HYG-BLD-004"
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

        pre_commit = ev.payload.get("pre_commit", {})
        has_pre_commit = pre_commit.get("has_pre_commit", False)
        tool = pre_commit.get("pre_commit_tool")

        if has_pre_commit:
            finding = make_green_finding(
                self.id,
                "pre-commit-hooks",
                ev,
                summary=f"Git hooks configured via {tool}.",
                evidence_locator=ev.locator,
                confidence=1.0,
            )
        else:
            finding = Finding(
                rule_id=self.id,
                rag="amber",
                severity="low",
                summary=(
                    "No pre-commit or git hooks configuration found "
                    "(checked .pre-commit-config.yaml, .husky/, "
                    "lefthook.yml/yaml, lint-staged in package.json)."
                ),
                recommendation=(
                    "Add a pre-commit hook tool to enforce code quality checks "
                    "before commits. Recommended: pre-commit "
                    "(https://pre-commit.com) for Python projects, "
                    "husky for Node.js projects."
                ),
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=1.0,
                pattern_tag="pre-commit-hooks",
            )

        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-BLD-004" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-BLD-004", PreCommitRule())


_register()

__all__ = ["PreCommitRule"]
