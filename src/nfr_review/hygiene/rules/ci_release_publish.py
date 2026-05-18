"""HYG-CI-007: Release and publish automation detection."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band

_RELEASE_PATTERNS = re.compile(
    r"(twine\s+upload|flit\s+publish|poetry\s+publish|python\s+-m\s+build"
    r"|npm\s+publish|npx\s+semantic-release|semantic-release"
    r"|mvn\s+deploy|gradle.*publish|./gradlew.*publish"
    r"|goreleaser|go-releaser"
    r"|softprops/action-gh-release|actions/create-release"
    r"|ncipollo/release-action|release-drafter/release-drafter"
    r"|pypa/gh-action-pypi-publish|changesets/action"
    r"|cargo\s+publish|gem\s+push|dotnet\s+nuget\s+push"
    r"|helm\s+push|docker\s+push|skopeo\s+copy"
    r"|gh\s+release\s+create)",
    re.IGNORECASE,
)


class CiReleasePublishRule:
    id = "HYG-CI-007"
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
        found_release = False

        for cfg in configs:
            for step in cfg.get("steps", []):
                if _RELEASE_PATTERNS.search(step):
                    found_release = True
                    break
            if found_release:
                break

        if not found_release:
            rag: RAG = "amber"
            severity: Severity = "low"
            summary = "No release or publish automation detected in CI."
            recommendation = (
                "Add automated release/publish workflows (e.g. semantic-release, "
                "goreleaser, pypa/gh-action-pypi-publish) to ensure reproducible, "
                "auditable releases."
            )
        else:
            rag = "green"
            severity = "info"
            summary = "Release/publish automation detected in CI."
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
            pattern_tag="ci-release-publish",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-007" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-007", CiReleasePublishRule())


_register()

__all__ = ["CiReleasePublishRule"]
