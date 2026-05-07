"""Rule: istio-traffic-policy — flags DestinationRules without trafficPolicy."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class IstioTrafficPolicyRule:
    """Flag DestinationRules that lack trafficPolicy with connectionPool settings."""

    id = "istio-traffic-policy"
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

        dest_rules: list[dict[str, Any]] = []
        for ev in istio_evidence:
            for resource in ev.payload.get("resources", []):
                if resource.get("kind") == "DestinationRule":
                    dest_rules.append(resource)

        if not dest_rules:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no DestinationRule resources found",
            )

        missing_policy: list[str] = []
        for dr in dest_rules:
            spec = dr.get("spec", {})
            traffic_policy = spec.get("trafficPolicy")
            if not traffic_policy or not traffic_policy.get("connectionPool"):
                missing_policy.append(dr.get("name", "unknown"))

        first = istio_evidence[0]
        if missing_policy:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"DestinationRule(s) missing trafficPolicy"
                            f" with connectionPool: {', '.join(missing_policy)}."
                        ),
                        recommendation=(
                            "Configure trafficPolicy with connectionPool limits"
                            " (tcp.maxConnections, http.http1MaxPendingRequests)"
                            " to prevent resource exhaustion."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.85,
                        pattern_tag="istio-traffic-policy",
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
                    summary=(
                        "All DestinationRules have trafficPolicy"
                        " with connectionPool configured."
                    ),
                    recommendation="No action required.",
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.85,
                    pattern_tag="istio-traffic-policy",
                )
            ],
        )


def _register() -> None:
    if "istio-traffic-policy" not in rule_registry:
        rule_registry.register("istio-traffic-policy", IstioTrafficPolicyRule())


_register()

__all__ = ["IstioTrafficPolicyRule"]
