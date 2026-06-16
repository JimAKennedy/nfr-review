# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-CI-007: Release and publish automation detection."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

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

        if not ev.payload.has_ci:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no CI configuration found",
            )

        configs = ev.payload.configs
        found_release = False

        for cfg in configs:
            for step in cfg.get("steps", []):
                if _RELEASE_PATTERNS.search(step):
                    found_release = True
                    break
            if found_release:
                break

        if not found_release:
            finding = Finding(
                rule_id=self.id,
                rag="amber",
                severity="low",
                summary="No release or publish automation detected in CI.",
                recommendation=(
                    "Add automated release/publish workflows (e.g. semantic-release, "
                    "goreleaser, pypa/gh-action-pypi-publish) to ensure reproducible, "
                    "auditable releases."
                ),
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.8,
                pattern_tag="ci-release-publish",
            )
        else:
            finding = make_green_finding(
                self.id,
                "ci-release-publish",
                ev,
                summary="Release/publish automation detected in CI.",
                evidence_locator=ev.locator,
                confidence=0.8,
            )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-007" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-007", CiReleasePublishRule())


_register()

__all__ = ["CiReleasePublishRule"]
