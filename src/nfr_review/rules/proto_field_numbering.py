# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: proto-field-numbering -- flags field numbering gaps
not covered by reserved declarations."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.proto import ProtoAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class ProtoFieldNumberingRule(FieldRule[ProtoAnalysisPayload]):
    """Flag messages where field number gaps exist without matching reserved declarations."""

    id = "proto-field-numbering"
    collector_name = "proto"
    evidence_kind = "proto-analysis"
    payload_type = ProtoAnalysisPayload
    pattern_tag = "proto-field-numbering"
    required_tech = ["grpc"]
    default_confidence = 0.85
    all_clear_summary = (
        "All proto messages have clean field numbering with no unexplained gaps."
    )
    all_clear_recommendation = "No action required."

    def check(self, payload: ProtoAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        for msg in payload.messages:
            if not msg.fields:
                continue

            field_numbers = sorted({f.number for f in msg.fields})
            reserved_numbers = set(msg.reserved_numbers)

            expected = set(range(field_numbers[0], field_numbers[-1] + 1))
            actual = set(field_numbers) | reserved_numbers
            gaps = expected - actual

            if gaps:
                gap_list = ", ".join(str(n) for n in sorted(gaps))
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"Message '{msg.name}' in {payload.file_path} has field"
                        f" numbering gaps [{gap_list}] not covered by"
                        " reserved declarations."
                    ),
                    recommendation=(
                        "Add 'reserved' declarations for removed field"
                        " numbers to preserve backward compatibility."
                    ),
                    locator=f"{payload.file_path}:{msg.line}",
                )


__all__ = ["ProtoFieldNumberingRule"]
