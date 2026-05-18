"""HYG-CI-006: CI test coverage gate detection."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band

_COVERAGE_TOOL_PATTERNS = re.compile(
    r"(pytest-cov|pytest\s+--cov|coverage\s+run|coverage\s+report|coverage\s+xml"
    r"|nyc|istanbul|c8\s|jacoco|jacocoTestReport|go\s+test\s+.*-cover"
    r"|codecov|coveralls|codeclimate.*coverage|coveragepy|dotcover"
    r"|llvm-cov|gcov|lcov|simplecov|phpunit.*coverage"
    r"|cobertura|opencover|reportgenerator)",
    re.IGNORECASE,
)

_COVERAGE_THRESHOLD_PATTERNS = re.compile(
    r"(--fail-under|fail[_-]under|minimum[_-]coverage|min[_-]coverage"
    r"|coverage[_-]minimum|--check-coverage|--branches\s+\d"
    r"|--lines\s+\d|--functions\s+\d|--statements\s+\d"
    r"|thresholds|violationRules|minimumCoveragePercentage"
    r"|coverage_fail_under|COVERAGE_THRESHOLD|min_coverage)",
    re.IGNORECASE,
)


class CiCoverageGateRule:
    id = "HYG-CI-006"
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
        found_tool = False
        found_threshold = False

        for cfg in configs:
            for step in cfg.get("steps", []):
                if _COVERAGE_TOOL_PATTERNS.search(step):
                    found_tool = True
                if _COVERAGE_THRESHOLD_PATTERNS.search(step):
                    found_threshold = True
                if found_tool and found_threshold:
                    break
            if found_tool and found_threshold:
                break

        if not found_tool:
            rag: RAG = "amber"
            severity: Severity = "medium"
            summary = "No test coverage tooling detected in CI."
            recommendation = (
                "Add a coverage tool (e.g. pytest-cov, nyc, JaCoCo, go test -cover) "
                "to measure test coverage and enforce minimum thresholds."
            )
        elif not found_threshold:
            rag = "amber"
            severity = "low"
            summary = "Coverage tool detected but no threshold enforcement found."
            recommendation = (
                "Add a coverage threshold gate (e.g. --fail-under=80) "
                "to prevent coverage regressions."
            )
        else:
            rag = "green"
            severity = "info"
            summary = "Test coverage tool with threshold enforcement detected in CI."
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
            pattern_tag="ci-coverage-gate",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-006" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-006", CiCoverageGateRule())


_register()

__all__ = ["CiCoverageGateRule"]
