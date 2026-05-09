"""HYG-CI-003: CI lint/format step presence check."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band

_LINT_PATTERNS = re.compile(
    r"(?:^|\s|/)(lint|ruff|eslint|prettier|black|flake8|rubocop|golangci-lint"
    r"|clippy|stylelint|pylint|mypy|biome)(?:\s|$|\")",
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
            rag: RAG = "amber"
            severity: Severity = "medium"
            summary = "No lint or format step detected in CI."
            recommendation = (
                "Add a linting step (e.g. ruff, eslint, golangci-lint) "
                "to catch style issues and potential bugs early."
            )
        else:
            rag = "green"
            severity = "info"
            summary = "Lint/format step detected in CI."
            recommendation = "No action required."

        finding = Finding(
            rule_id=self.id,
            rag=rag,
            severity=severity,
            summary=summary,
            recommendation=recommendation,
            evidence_locator=ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=0.8,
            pattern_tag="ci-has-lint",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-003" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-003", CiHasLintRule())


_register()

__all__ = ["CiHasLintRule"]
