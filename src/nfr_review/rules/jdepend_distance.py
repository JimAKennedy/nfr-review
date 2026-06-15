# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: JDEP-DISTANCE — flags packages far from the ideal main sequence (A + I = 1)."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_DISTANCE_THRESHOLD = 0.5


class JDepDistanceRule:
    """Amber finding for packages with distance from main sequence (D) > 0.5.

    The main sequence is the ideal balance line where A + I = 1.
    Packages far from it are either too abstract with few dependents
    (zone of uselessness) or too concrete with many dependents
    (zone of pain).
    """

    id = "JDEP-DISTANCE"
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
                    skip_reason=ev.payload.get("reason", "jdepend unavailable"),
                )

            if ev.kind != "jdepend-packages":
                continue

            for pkg in ev.payload.get("packages", []):
                checked_any = True
                distance = pkg.get("d", pkg.get("D", 0.0))
                name = pkg.get("name", "unknown")
                abstractness = pkg.get("a", pkg.get("A", 0.0))
                instability = pkg.get("i", pkg.get("I", 0.0))

                if distance > _DISTANCE_THRESHOLD:
                    if abstractness > instability:
                        zone = "zone of uselessness (too abstract, few dependents)"
                    else:
                        zone = "zone of pain (too concrete, many dependents)"

                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Package '{name}' is far from the main sequence"
                                f" (D={distance:.2f}, A={abstractness:.2f},"
                                f" I={instability:.2f}) — in the {zone}."
                            ),
                            recommendation=(
                                f"Review '{name}' for architectural balance."
                                f" Aim for A + I ≈ 1 by adjusting the ratio of"
                                f" abstract types to dependencies."
                            ),
                            evidence_locator=f"jdepend:{name}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.8,
                            pattern_tag="jdep-distance-high",
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
                    "jdep-distance-ok",
                    jdep_evidence[0],
                    summary="All packages are close to the main sequence (D ≤ 0.5).",
                    confidence=0.8,
                    evidence_locator="jdepend-summary",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "JDEP-DISTANCE" not in rule_registry:
        rule_registry.register("JDEP-DISTANCE", JDepDistanceRule())


_register()

__all__ = ["JDepDistanceRule"]
