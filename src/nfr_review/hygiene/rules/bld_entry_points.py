# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-BLD-003: Entry point configuration check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class EntryPointsRule:
    id = "HYG-BLD-003"
    band: Band = 1
    required_collectors: list[str] = ["build-readiness"]
    category = "build-readiness"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "build-readiness-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no build-readiness-analysis evidence available",
            )

        build_info = ev.payload.get("build_system", {})
        has_build = build_info.get("has_build_system", False)

        if not has_build:
            finding = Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary="No build system detected — entry point check not applicable.",
                recommendation="Configure a build system first (see HYG-BLD-001).",
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=1.0,
                pattern_tag="entry-points-skipped",
            )
            return RuleResult(rule_id=self.id, findings=[finding])

        ep_info = ev.payload.get("entry_points", {})
        has_eps = ep_info.get("has_entry_points", False)

        if not has_eps:
            rag: RAG = "amber"
            severity: Severity = "medium"
            summary = "No console_scripts or gui_scripts entry points defined."
            recommendation = (
                "Add [project.scripts] to pyproject.toml if this package "
                "should be installable as a CLI tool."
            )
        else:
            scripts = ep_info.get("scripts", {})
            count = len(scripts)
            rag = "green"
            severity = "info"
            summary = f"{count} entry point(s) configured."
            recommendation = "No action required."

        finding = Finding(
            rule_id=self.id,
            rag=rag,
            severity=severity,
            summary=summary,
            recommendation=recommendation,
            evidence_locator=build_info.get("path") or ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=1.0,
            pattern_tag="entry-points",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-BLD-003" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-BLD-003", EntryPointsRule())


_register()

__all__ = ["EntryPointsRule"]
