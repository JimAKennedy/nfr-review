# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: proto-service-versioning — flags services without version indicators."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_VERSION_IN_NAME = re.compile(r"V\d+", re.IGNORECASE)
_VERSION_IN_PACKAGE = re.compile(r"\.v\d+")


class ProtoServiceVersioningRule:
    """Flag services that lack version indicators in name or package."""

    id = "proto-service-versioning"
    band: Band = 2
    required_collectors: list[str] = ["proto"]
    required_tech: list[str] = ["grpc"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        proto_evidence = filter_evidence(evidence, "proto", "proto-analysis")
        if not proto_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no proto evidence available",
            )

        findings: list[Finding] = []
        for ev in proto_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            package = ev.payload.get("package") or ""
            package_versioned = bool(_VERSION_IN_PACKAGE.search(package))

            for svc in ev.payload.get("services", []):
                svc_name = svc.get("name", "Unknown")
                name_versioned = bool(_VERSION_IN_NAME.search(svc_name))

                if not name_versioned and not package_versioned:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Service '{svc_name}' in {file_path} has no"
                                " version indicator in service name or package."
                            ),
                            recommendation=(
                                "Add a version suffix to the service name"
                                " (e.g. CartServiceV1) or include a version"
                                " segment in the package (e.g. shop.v1)."
                            ),
                            evidence_locator=f"{file_path}:{svc.get('line', 0)}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.8,
                            pattern_tag="proto-service-versioning",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "proto-service-versioning",
                    proto_evidence[0],
                    summary="All proto services have version indicators.",
                    confidence=0.9,
                    evidence_locator="all-protos",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "proto-service-versioning" not in rule_registry:
        rule_registry.register("proto-service-versioning", ProtoServiceVersioningRule())


_register()

__all__ = ["ProtoServiceVersioningRule"]
