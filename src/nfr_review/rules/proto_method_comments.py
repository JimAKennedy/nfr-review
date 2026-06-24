# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: proto-method-comments -- flags service methods without preceding comments."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.proto import ProtoAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class ProtoMethodCommentsRule(FieldRule[ProtoAnalysisPayload]):
    """Flag RPC methods that lack preceding comment documentation."""

    id = "proto-method-comments"
    band = 2
    collector_name = "proto"
    evidence_kind = "proto-analysis"
    payload_type = ProtoAnalysisPayload
    pattern_tag = "proto-method-comments"
    required_tech = ["grpc"]
    default_confidence = 0.85
    all_clear_summary = "All proto service methods have preceding comments."
    all_clear_recommendation = "No action required."

    def check(self, payload: ProtoAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        for svc in payload.services:
            for method in svc.methods:
                if not method.has_comment:
                    yield Hit(
                        rag="amber",
                        severity="low",
                        summary=(
                            f"Method '{method.name}' in service"
                            f" '{svc.name}' ({payload.file_path}) has no"
                            " preceding comment."
                        ),
                        recommendation=(
                            "Add a comment above the rpc declaration"
                            " describing the method's purpose, expected"
                            " errors, and idempotency guarantees."
                        ),
                        locator=f"{payload.file_path}:{method.line}",
                    )


__all__ = ["ProtoMethodCommentsRule"]
