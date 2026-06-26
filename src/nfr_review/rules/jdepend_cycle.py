# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: JDEP-CYCLE — flags package dependency cycles detected by JDepend."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.jdepend import JDependPackagesPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class JDepCycleRule(FieldRule[JDependPackagesPayload]):
    """Red finding for any Java package cycle detected by JDepend."""

    id = "JDEP-CYCLE"
    collector_name = "jdepend"
    evidence_kind = "jdepend-packages"
    payload_type = JDependPackagesPayload
    pattern_tag = "jdep-cycle-detected"
    skip_evidence_kind = "jdepend-skip"
    default_confidence = 0.95
    all_clear_summary = "No package dependency cycles detected."
    all_clear_recommendation = "No action required."
    all_clear_tag = "jdep-cycle-ok"

    def check(self, payload: JDependPackagesPayload, ev: Evidence) -> Iterable[Hit]:
        cycle_groups = payload.cycle_groups
        if not cycle_groups:
            return

        for group in cycle_groups:
            packages = group if isinstance(group, list) else [group]
            pkg_list = " → ".join(packages)
            yield Hit(
                rag="red",
                severity="high",
                summary=f"Package dependency cycle detected: {pkg_list}",
                recommendation=(
                    "Break the cycle by introducing an interface package or"
                    " inverting the dependency direction. Cyclic dependencies"
                    " prevent independent deployment and testing."
                ),
                locator=ev.locator,
            )


__all__ = ["JDepCycleRule"]
