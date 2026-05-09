"""HYG-CI-004: CI SAST/security scanning step presence check."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band

_SAST_PATTERNS = re.compile(
    r"(codeql|semgrep|snyk|trivy|bandit|gitleaks|sonar"
    r"|dependabot|safety|grype|checkov|tfsec|osv-scanner)",
    re.IGNORECASE,
)


class CiHasSastRule:
    id = "HYG-CI-004"
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
        found_sast = False

        for cfg in configs:
            for step in cfg.get("steps", []):
                if _SAST_PATTERNS.search(step):
                    found_sast = True
                    break
            if found_sast:
                break

        if not found_sast:
            rag: RAG = "amber"
            severity: Severity = "medium"
            summary = "No SAST or security scanning step detected in CI."
            recommendation = (
                "Add a security scanning step (e.g. CodeQL, Semgrep, Snyk, Trivy) "
                "to detect vulnerabilities before deployment."
            )
        else:
            rag = "green"
            severity = "info"
            summary = "SAST/security scanning step detected in CI."
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
            pattern_tag="ci-has-sast",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-004" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-004", CiHasSastRule())


_register()

__all__ = ["CiHasSastRule"]
