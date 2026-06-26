# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: JDEP-INSTABILITY — flags packages with high instability and low abstractness."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.jdepend import JDependPackagesPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_INSTABILITY_THRESHOLD = 0.8
_ABSTRACTNESS_THRESHOLD = 0.2


class JDepInstabilityRule(FieldRule[JDependPackagesPayload]):
    """Amber finding for packages with high instability (I > 0.8) and low
    abstractness (A < 0.2), indicating concrete packages that are heavily
    depended upon — fragile to change.
    """

    id = "JDEP-INSTABILITY"
    collector_name = "jdepend"
    evidence_kind = "jdepend-packages"
    payload_type = JDependPackagesPayload
    pattern_tag = "jdep-instability-high"
    default_confidence = 0.85
    all_clear_summary = "All packages have acceptable instability/abstractness balance."
    all_clear_recommendation = "No action required."

    def check(self, payload: JDependPackagesPayload, ev: Evidence) -> Iterable[Hit]:
        for pkg in payload.packages:
            instability = pkg.i
            abstractness = pkg.a
            name = pkg.name

            if instability > _INSTABILITY_THRESHOLD and abstractness < _ABSTRACTNESS_THRESHOLD:
                yield Hit(
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
                    locator=f"jdepend:{name}",
                )


__all__ = ["JDepInstabilityRule"]
