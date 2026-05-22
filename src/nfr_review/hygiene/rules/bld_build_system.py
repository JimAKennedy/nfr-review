# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-BLD-001: Build system presence check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class BuildSystemRule:
    id = "HYG-BLD-001"
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

        info = ev.payload.get("build_system", {})
        has_build = info.get("has_build_system", False)

        if not has_build:
            rag: RAG = "red"
            severity: Severity = "high"
            summary = (
                "No build system found (checked pyproject.toml, setup.py, "
                "setup.cfg, pom.xml, build.gradle(.kts), go.mod, Cargo.toml, "
                "*.csproj/*.sln)."
            )
            recommendation = (
                "Add a build manifest: pyproject.toml [build-system] (Python), "
                "pom.xml/build.gradle (JVM), go.mod (Go), Cargo.toml (Rust), "
                "or *.csproj (C#)."
            )
        else:
            backend = info.get("backend", "unknown")
            rag = "green"
            severity = "info"
            summary = f"Build system configured (backend: {backend})."
            recommendation = "No action required."

        finding = Finding(
            rule_id=self.id,
            rag=rag,
            severity=severity,
            summary=summary,
            recommendation=recommendation,
            evidence_locator=info.get("path") or ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=1.0,
            pattern_tag="build-system-presence",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-BLD-001" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-BLD-001", BuildSystemRule())


_register()

__all__ = ["BuildSystemRule"]
