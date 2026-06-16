# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-CI-002: CI test-step presence check."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

_TEST_PATTERNS = re.compile(
    r"(?:^|\s|/)(pytest|jest|mocha|cargo\s+test|go\s+test|dotnet\s+test|mvn\s+test"
    r"|npm\s+test|yarn\s+test|phpunit|rspec|unittest|nose2|tox"
    r"|ctest|cmake\s+--build\s+\S+\s+--target\s+test)(?:\s|$|\")",
    re.IGNORECASE,
)

_TEST_SIMPLE = re.compile(r"\btest\b", re.IGNORECASE)


class CiHasTestsRule:
    id = "HYG-CI-002"
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

        if not ev.payload.has_ci:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no CI configuration found",
            )

        configs = ev.payload.configs
        configs_with_tests = 0

        for cfg in configs:
            steps = cfg.get("steps", [])
            for step in steps:
                if _TEST_PATTERNS.search(step) or _TEST_SIMPLE.search(step):
                    configs_with_tests += 1
                    break

        if configs_with_tests == 0:
            finding = Finding(
                rule_id=self.id,
                rag="red",
                severity="high",
                summary="No CI step appears to run tests.",
                recommendation=(
                    "Add a test step to your CI pipeline (e.g. pytest, jest, go test)."
                ),
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.8,
                pattern_tag="ci-has-tests",
            )
        elif configs_with_tests == 1 and len(configs) > 1:
            finding = Finding(
                rule_id=self.id,
                rag="amber",
                severity="medium",
                summary=f"Test step found in only 1 of {len(configs)} CI configurations.",
                recommendation="Consider adding test steps to all CI workflows.",
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.8,
                pattern_tag="ci-has-tests",
            )
        else:
            finding = make_green_finding(
                self.id,
                "ci-has-tests",
                ev,
                summary=f"Test steps found in {configs_with_tests} CI configuration(s).",
                evidence_locator=ev.locator,
                confidence=0.8,
            )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-002" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-002", CiHasTestsRule())


_register()

__all__ = ["CiHasTestsRule"]
