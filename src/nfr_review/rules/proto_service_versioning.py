# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: proto-service-versioning -- flags services without version indicators."""

from __future__ import annotations

import re
from collections.abc import Iterable

from nfr_review.collectors.payloads.proto import ProtoAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_VERSION_IN_NAME = re.compile(r"V\d+", re.IGNORECASE)
_VERSION_IN_PACKAGE = re.compile(r"\.v\d+")


class ProtoServiceVersioningRule(FieldRule[ProtoAnalysisPayload]):
    """Flag services that lack version indicators in name or package."""

    id = "proto-service-versioning"
    band = 2
    collector_name = "proto"
    evidence_kind = "proto-analysis"
    payload_type = ProtoAnalysisPayload
    pattern_tag = "proto-service-versioning"
    required_tech = ["grpc"]
    default_confidence = 0.8
    all_clear_summary = "All proto services have version indicators."
    all_clear_recommendation = "No action required."

    def check(self, payload: ProtoAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        package = payload.package or ""
        package_versioned = bool(_VERSION_IN_PACKAGE.search(package))

        for svc in payload.services:
            name_versioned = bool(_VERSION_IN_NAME.search(svc.name))

            if not name_versioned and not package_versioned:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"Service '{svc.name}' in {payload.file_path} has no"
                        " version indicator in service name or package."
                    ),
                    recommendation=(
                        "Add a version suffix to the service name"
                        " (e.g. CartServiceV1) or include a version"
                        " segment in the package (e.g. shop.v1)."
                    ),
                    locator=f"{payload.file_path}:{svc.line}",
                )


__all__ = ["ProtoServiceVersioningRule"]
