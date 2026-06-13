# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: proto-method-comments — flags service methods without preceding comments."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class ProtoMethodCommentsRule:
    """Flag RPC methods that lack preceding comment documentation."""

    id = "proto-method-comments"
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
            for svc in ev.payload.get("services", []):
                svc_name = svc.get("name", "Unknown")
                for method in svc.get("methods", []):
                    if not method.get("has_comment", False):
                        method_name = method.get("name", "Unknown")
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="amber",
                                severity="low",
                                summary=(
                                    f"Method '{method_name}' in service"
                                    f" '{svc_name}' ({file_path}) has no"
                                    " preceding comment."
                                ),
                                recommendation=(
                                    "Add a comment above the rpc declaration"
                                    " describing the method's purpose, expected"
                                    " errors, and idempotency guarantees."
                                ),
                                evidence_locator=f"{file_path}:{method.get('line', 0)}",
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.85,
                                pattern_tag="proto-method-comments",
                            )
                        )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "proto-method-comments",
                    proto_evidence[0],
                    summary="All proto service methods have preceding comments.",
                    confidence=0.9,
                    evidence_locator="all-protos",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "proto-method-comments" not in rule_registry:
        rule_registry.register("proto-method-comments", ProtoMethodCommentsRule())


_register()

__all__ = ["ProtoMethodCommentsRule"]
