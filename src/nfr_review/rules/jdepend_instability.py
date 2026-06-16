# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: JDEP-INSTABILITY — flags packages with high instability and low abstractness."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_INSTABILITY_THRESHOLD = 0.8
_ABSTRACTNESS_THRESHOLD = 0.2


class JDepInstabilityRule:
    """Amber finding for packages with high instability (I > 0.8) and low
    abstractness (A < 0.2), indicating concrete packages that are heavily
    depended upon — fragile to change.
    """

    id = "JDEP-INSTABILITY"
    band: Band = 1
    required_collectors: list[str] = ["jdepend"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        jdep_evidence = filter_evidence(evidence, "jdepend")
        if not jdep_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no jdepend evidence available",
            )

        findings: list[Finding] = []
        checked_any = False

        for ev in jdep_evidence:
            if ev.kind == "jdepend-skip":
                return RuleResult(
                    rule_id=self.id,
                    skipped=True,
                    skip_reason=ev.payload.reason,
                )

            if ev.kind != "jdepend-packages":
                continue

            for pkg in ev.payload.packages:
                checked_any = True
                instability = pkg.get("i", pkg.get("I", 0.0))
                abstractness = pkg.get("a", pkg.get("A", 0.0))
                name = pkg.get("name", "unknown")

                if (
                    instability > _INSTABILITY_THRESHOLD
                    and abstractness < _ABSTRACTNESS_THRESHOLD
                ):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Package '{name}' has high instability"
                                f" (I={instability:.2f}) with low abstractness"
                                f" (A={abstractness:.2f}) — concrete and fragile."
                            ),
                            recommendation=(
                                f"Consider extracting interfaces or abstract classes"
                                f" in '{name}' to increase abstractness, or reduce"
                                f" outgoing dependencies to lower instability."
                            ),
                            evidence_locator=f"jdepend:{name}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="jdep-instability-high",
                        )
                    )

        if not checked_any:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no jdepend-packages evidence found",
            )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "jdep-instability-ok",
                    jdep_evidence[0],
                    summary="All packages have acceptable instability/abstractness balance.",
                    evidence_locator="jdepend-summary",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "JDEP-INSTABILITY" not in rule_registry:
        rule_registry.register("JDEP-INSTABILITY", JDepInstabilityRule())


_register()

__all__ = ["JDepInstabilityRule"]
