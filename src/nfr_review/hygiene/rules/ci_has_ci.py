# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-CI-001: CI/CD pipeline presence check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding


class CiPresenceRule:
    id = "HYG-CI-001"
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

        has_ci = ev.payload.has_ci

        if not has_ci:
            finding = Finding(
                rule_id=self.id,
                rag="red",
                severity="high",
                summary="No CI/CD configuration found.",
                recommendation=(
                    "Add a CI pipeline (e.g. GitHub Actions, GitLab CI) "
                    "to automate testing, linting, and deployment."
                ),
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=1.0,
                pattern_tag="ci-presence",
            )
        else:
            systems = ev.payload.ci_systems
            finding = make_green_finding(
                self.id,
                "ci-presence",
                ev,
                summary=f"CI/CD detected: {', '.join(systems)}.",
                evidence_locator=ev.locator,
                confidence=1.0,
            )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-001" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-001", CiPresenceRule())


_register()

__all__ = ["CiPresenceRule"]
