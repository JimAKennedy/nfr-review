# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-CI-005: GitHub Actions pin-by-SHA check."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

_SHA_PIN_RE = re.compile(r"@[0-9a-f]{40}\b")
_TAG_PIN_RE = re.compile(r"@v?\d")


class CiPinActionsRule:
    id = "HYG-CI-005"
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

        ci_systems = ev.payload.ci_systems
        if "github-actions" not in ci_systems:
            finding = make_green_finding(
                self.id,
                "ci-pin-actions",
                ev,
                summary="Not using GitHub Actions — SHA pinning check not applicable.",
                evidence_locator=ev.locator,
                confidence=1.0,
            )
            return RuleResult(rule_id=self.id, findings=[finding])

        configs = ev.payload.configs
        unpinned: list[str] = []
        total_uses = 0

        for cfg in configs:
            if cfg.get("provider") != "github-actions":
                continue
            for step in cfg.get("steps", []):
                if "/" not in step:
                    continue
                total_uses += 1
                if _TAG_PIN_RE.search(step) and not _SHA_PIN_RE.search(step):
                    unpinned.append(step)

        if total_uses == 0:
            finding = make_green_finding(
                self.id,
                "ci-pin-actions",
                ev,
                summary="No third-party action uses found.",
                evidence_locator=ev.locator,
                confidence=0.9,
            )
        elif unpinned:
            finding = Finding(
                rule_id=self.id,
                rag="amber",
                severity="medium",
                summary=(
                    f"{len(unpinned)} of {total_uses} action reference(s) "
                    "use tag versions instead of SHA pins."
                ),
                recommendation=(
                    "Pin actions to full commit SHAs for supply-chain safety "
                    "(e.g. actions/checkout@<sha> instead of @v4)."
                ),
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.9,
                pattern_tag="ci-pin-actions",
            )
        else:
            finding = make_green_finding(
                self.id,
                "ci-pin-actions",
                ev,
                summary=f"All {total_uses} action reference(s) are SHA-pinned.",
                evidence_locator=ev.locator,
                confidence=0.9,
            )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-005" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-005", CiPinActionsRule())


_register()

__all__ = ["CiPinActionsRule"]
