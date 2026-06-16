# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-COM-006: CODEOWNERS presence check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding


class CodeownersPresenceRule:
    id = "HYG-COM-006"
    band: Band = 1
    required_collectors: list[str] = ["community"]
    category = "community"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "community-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no community-analysis evidence available",
            )

        info = ev.payload.codeowners
        exists = info.get("exists", False)

        locator = info.get("path") or ev.locator

        if exists:
            finding = make_green_finding(
                self.id,
                "codeowners-presence",
                ev,
                summary="CODEOWNERS file found.",
                evidence_locator=locator,
                confidence=1.0,
            )
        else:
            finding = Finding(
                rule_id=self.id,
                rag="amber",
                severity="medium",
                summary="No CODEOWNERS file found.",
                recommendation=(
                    "Add a CODEOWNERS file to enforce review ownership for critical paths."
                ),
                evidence_locator=locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=1.0,
                pattern_tag="codeowners-presence",
            )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-COM-006" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-COM-006", CodeownersPresenceRule())


_register()

__all__ = ["CodeownersPresenceRule"]
