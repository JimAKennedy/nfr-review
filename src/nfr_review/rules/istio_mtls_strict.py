# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: istio-mtls-strict -- flags Istio meshes without STRICT mTLS."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nfr_review.collectors.payloads.istio import IstioAnalysisPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding


class IstioMtlsStrictRule(FieldRule[IstioAnalysisPayload]):
    """Flag Istio meshes where PeerAuthentication does not enforce STRICT mTLS."""

    id = "istio-mtls-strict"
    collector_name = "istio"
    evidence_kind = "istio-analysis"
    payload_type = IstioAnalysisPayload
    pattern_tag = "istio-mtls-strict"
    required_tech = ["istio"]
    default_confidence = 0.9
    all_clear_summary = "mTLS STRICT mode is enforced via PeerAuthentication."
    all_clear_recommendation = "No action required."

    def check(self, payload: IstioAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        # Cross-evidence aggregation handled in evaluate() override.
        # This is called only when no STRICT mode found across all evidence.
        yield Hit(
            rag="red",
            severity="high",
            summary=(
                "mTLS is not enforced in STRICT mode."
                " Service-to-service communication may be unencrypted."
            ),
            recommendation=(
                "Configure a mesh-wide PeerAuthentication resource"
                " with spec.mtls.mode set to STRICT to enforce"
                " mutual TLS for all services."
            ),
            locator=payload.file_path,
        )

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [
            e
            for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason=f"no {self.evidence_kind} evidence available",
            )

        # Aggregate: check if ANY evidence has STRICT PeerAuthentication.
        has_strict = False
        for ev in relevant:
            payload = self._coerce(ev.payload)
            for resource in payload.resources:
                if resource.kind != "PeerAuthentication":
                    continue
                mtls = resource.spec.get("mtls", {})
                if mtls.get("mode") == "STRICT":
                    has_strict = True
                    break
            if has_strict:
                break

        first = relevant[0]
        if has_strict:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=self.default_confidence,
                        hit=Hit(
                            rag="green",
                            summary=self.all_clear_summary,
                            recommendation=self.all_clear_recommendation,
                            locator=first.locator,
                        ),
                    )
                ],
            )

        # No STRICT found -- fire on the first evidence.
        return RuleResult(
            rule_id=self.id,
            findings=[
                make_finding(
                    rule_id=self.id,
                    ev=first,
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                    hit=Hit(
                        rag="red",
                        severity="high",
                        summary=(
                            "mTLS is not enforced in STRICT mode."
                            " Service-to-service communication"
                            " may be unencrypted."
                        ),
                        recommendation=(
                            "Configure a mesh-wide PeerAuthentication"
                            " resource with spec.mtls.mode set to"
                            " STRICT to enforce mutual TLS for all"
                            " services."
                        ),
                        locator=first.locator,
                    ),
                )
            ],
        )


__all__ = ["IstioMtlsStrictRule"]
