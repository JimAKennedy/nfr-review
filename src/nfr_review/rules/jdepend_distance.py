# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: JDEP-DISTANCE — flags packages far from the ideal main sequence (A + I = 1)."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.jdepend import JDependPackagesPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_DISTANCE_THRESHOLD = 0.5


class JDepDistanceRule(FieldRule[JDependPackagesPayload]):
    """Amber finding for packages with distance from main sequence (D) > 0.5.

    The main sequence is the ideal balance line where A + I = 1.
    Packages far from it are either too abstract with few dependents
    (zone of uselessness) or too concrete with many dependents
    (zone of pain).
    """

    id = "JDEP-DISTANCE"
    collector_name = "jdepend"
    evidence_kind = "jdepend-packages"
    payload_type = JDependPackagesPayload
    pattern_tag = "jdep-distance-high"
    default_confidence = 0.8
    all_clear_summary = "All packages are close to the main sequence (D <= 0.5)."
    all_clear_recommendation = "No action required."

    def check(self, payload: JDependPackagesPayload, ev: Evidence) -> Iterable[Hit]:
        for pkg in payload.packages:
            distance = pkg.d
            name = pkg.name
            abstractness = pkg.a
            instability = pkg.i

            if distance > _DISTANCE_THRESHOLD:
                if abstractness > instability:
                    zone = "zone of uselessness (too abstract, few dependents)"
                else:
                    zone = "zone of pain (too concrete, many dependents)"

                yield Hit(
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
                    locator=f"jdepend:{name}",
                )


__all__ = ["JDepDistanceRule"]
