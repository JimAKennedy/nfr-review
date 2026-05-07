"""Rule: istio-circuit-breaker — flags DestinationRules without outlierDetection."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class IstioCircuitBreakerRule:
    """Flag DestinationRules that lack outlierDetection for circuit breaking."""

    id = "istio-circuit-breaker"
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

        has_outlier_detection = False
        for dr in dest_rules:
            spec = dr.get("spec", {})
            traffic_policy = spec.get("trafficPolicy", {})
            if traffic_policy and traffic_policy.get("outlierDetection"):
                has_outlier_detection = True
                break

        first = istio_evidence[0]
        if not has_outlier_detection:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            "No circuit breaker (outlierDetection) configured"
                            " in any DestinationRule."
                        ),
                        recommendation=(
                            "Configure outlierDetection in trafficPolicy"
                            " (consecutive5xxErrors, interval, baseEjectionTime)"
                            " to enable circuit breaking and prevent cascade failures."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.85,
                        pattern_tag="istio-circuit-breaker",
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
                    summary="Circuit breaker (outlierDetection) is configured.",
                    recommendation="No action required.",
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.85,
                    pattern_tag="istio-circuit-breaker",
                )
            ],
        )


def _register() -> None:
    if "istio-circuit-breaker" not in rule_registry:
        rule_registry.register("istio-circuit-breaker", IstioCircuitBreakerRule())


_register()

__all__ = ["IstioCircuitBreakerRule"]
