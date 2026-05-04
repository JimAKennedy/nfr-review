"""Rule: network-policy-missing — checks repo for presence of NetworkPolicy resources."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class NetworkPolicyMissingRule:
    """Flag when no NetworkPolicy resource exists in the repository."""

    id = "network-policy-missing"
    band: Band = 1
    required_collectors: list[str] = ["k8s-manifest"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summary_ev = next(
            (
                e
                for e in evidence
                if e.collector_name == "k8s-manifest" and e.kind == "k8s-manifest-summary"
            ),
            None,
        )
        if summary_ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no k8s-manifest evidence available",
            )

        has_network_policy = summary_ev.payload.get("has_network_policy", False)

        if has_network_policy:
            finding = Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary="NetworkPolicy resource found in repository.",
                recommendation="No action required — network policies are defined.",
                evidence_locator=summary_ev.locator,
                collector_name=summary_ev.collector_name,
                collector_version=summary_ev.collector_version,
                confidence=0.9,
                pattern_tag="k8s-network-policy",
            )
        else:
            finding = Finding(
                rule_id=self.id,
                rag="amber",
                severity="medium",
                summary="No NetworkPolicy resource found in the repository.",
                recommendation=(
                    "Define NetworkPolicy resources to restrict pod-to-pod"
                    " traffic and enforce least-privilege network access."
                ),
                evidence_locator=summary_ev.locator,
                collector_name=summary_ev.collector_name,
                collector_version=summary_ev.collector_version,
                confidence=0.9,
                pattern_tag="k8s-network-policy",
            )

        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "network-policy-missing" not in rule_registry:
        rule_registry.register("network-policy-missing", NetworkPolicyMissingRule())


_register()

__all__ = ["NetworkPolicyMissingRule"]
