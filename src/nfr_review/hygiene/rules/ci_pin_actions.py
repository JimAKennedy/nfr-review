"""HYG-CI-005: GitHub Actions pin-by-SHA check."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band

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

        if not ev.payload.get("has_ci", False):
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no CI configuration found",
            )

        ci_systems = ev.payload.get("ci_systems", [])
        if "github-actions" not in ci_systems:
            finding = Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary="Not using GitHub Actions — SHA pinning check not applicable.",
                recommendation="No action required.",
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=1.0,
                pattern_tag="ci-pin-actions",
            )
            return RuleResult(rule_id=self.id, findings=[finding])

        configs = ev.payload.get("configs", [])
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
            rag: RAG = "green"
            severity: Severity = "info"
            summary = "No third-party action uses found."
            recommendation = "No action required."
        elif unpinned:
            rag = "amber"
            severity = "medium"
            summary = (
                f"{len(unpinned)} of {total_uses} action reference(s) "
                "use tag versions instead of SHA pins."
            )
            recommendation = (
                "Pin actions to full commit SHAs for supply-chain safety "
                "(e.g. actions/checkout@<sha> instead of @v4)."
            )
        else:
            rag = "green"
            severity = "info"
            summary = f"All {total_uses} action reference(s) are SHA-pinned."
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
            confidence=0.9,
            pattern_tag="ci-pin-actions",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-CI-005" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-CI-005", CiPinActionsRule())


_register()

__all__ = ["CiPinActionsRule"]
