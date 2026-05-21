# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: proto-field-numbering — flags field numbering gaps
not covered by reserved declarations."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class ProtoFieldNumberingRule:
    """Flag messages where field number gaps exist without matching reserved declarations."""

    id = "proto-field-numbering"
    band: Band = 1
    required_collectors: list[str] = ["proto"]
    required_tech: list[str] = ["grpc"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        proto_evidence = [
            e for e in evidence if e.collector_name == "proto" and e.kind == "proto-analysis"
        ]
        if not proto_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no proto evidence available",
            )

        findings: list[Finding] = []
        for ev in proto_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for msg in ev.payload.get("messages", []):
                msg_name = msg.get("name", "Unknown")
                fields = msg.get("fields", [])
                if not fields:
                    continue

                field_numbers = sorted({f["number"] for f in fields})
                reserved_numbers = set(msg.get("reserved_numbers", []))

                expected = set(range(field_numbers[0], field_numbers[-1] + 1))
                actual = set(field_numbers) | reserved_numbers
                gaps = expected - actual

                if gaps:
                    gap_list = ", ".join(str(n) for n in sorted(gaps))
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Message '{msg_name}' in {file_path} has field"
                                f" numbering gaps [{gap_list}] not covered by"
                                " reserved declarations."
                            ),
                            recommendation=(
                                "Add 'reserved' declarations for removed field"
                                " numbers to preserve backward compatibility."
                            ),
                            evidence_locator=f"{file_path}:{msg.get('line', 0)}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="proto-field-numbering",
                        )
                    )

        if not findings:
            first = proto_evidence[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        "All proto messages have clean field numbering"
                        " with no unexplained gaps."
                    ),
                    recommendation="No action required.",
                    evidence_locator="all-protos",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.9,
                    pattern_tag="proto-field-numbering",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "proto-field-numbering" not in rule_registry:
        rule_registry.register("proto-field-numbering", ProtoFieldNumberingRule())


_register()

__all__ = ["ProtoFieldNumberingRule"]
