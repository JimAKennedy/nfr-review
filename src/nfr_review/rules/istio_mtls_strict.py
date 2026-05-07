"""Rule: istio-mtls-strict — flags Istio meshes without STRICT mTLS."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class IstioMtlsStrictRule:
    """Flag Istio meshes where PeerAuthentication does not enforce STRICT mTLS."""

    id = "istio-mtls-strict"
    band: Band = 1
    required_collectors: list[str] = ["istio"]
    required_tech: list[str] = ["istio"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        istio_evidence = [
            e for e in evidence if e.collector_name == "istio" and e.kind == "istio-analysis"
        ]
        if not istio_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no istio-analysis evidence available",
            )

        has_strict = False
        for ev in istio_evidence:
            for resource in ev.payload.get("resources", []):
                if resource.get("kind") != "PeerAuthentication":
                    continue
                spec = resource.get("spec", {})
                mtls = spec.get("mtls", {})
                if mtls.get("mode") == "STRICT":
                    has_strict = True
                    break
            if has_strict:
                break

        first = istio_evidence[0]
        if not has_strict:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.9,
                        pattern_tag="istio-mtls-strict",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="mTLS STRICT mode is enforced via PeerAuthentication.",
                    recommendation="No action required.",
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.9,
                    pattern_tag="istio-mtls-strict",
                )
            ],
        )


def _register() -> None:
    if "istio-mtls-strict" not in rule_registry:
        rule_registry.register("istio-mtls-strict", IstioMtlsStrictRule())


_register()

__all__ = ["IstioMtlsStrictRule"]
