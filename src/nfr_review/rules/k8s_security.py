"""Rule: non-root-container-violation — checks containers enforce runAsNonRoot."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class NonRootContainerViolationRule:
    """Flag containers without securityContext.runAsNonRoot=true."""

    id = "non-root-container-violation"
    band: Band = 1
    required_collectors: list[str] = ["k8s-manifest"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        k8s_resources = [
            e
            for e in evidence
            if e.collector_name == "k8s-manifest" and e.kind == "k8s-resource"
        ]
        if not k8s_resources:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no k8s-manifest evidence available",
            )

        findings: list[Finding] = []
        for ev in k8s_resources:
            resource_name = ev.payload.get("name", "")
            file_path = ev.payload.get("file_path", ev.locator)
            pod_sec_ctx = ev.payload.get("pod_security_context")
            pod_non_root = (
                isinstance(pod_sec_ctx, dict)
                and pod_sec_ctx.get("runAsNonRoot") is True
            )
            for container in ev.payload.get("containers", []):
                container_name = container.get("name", "")
                sec_ctx = container.get("security_context")
                container_non_root = (
                    isinstance(sec_ctx, dict)
                    and sec_ctx.get("runAsNonRoot") is True
                )
                if not pod_non_root and not container_non_root:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Container '{container_name}' in"
                                f" {resource_name} does not set"
                                f" runAsNonRoot=true."
                            ),
                            recommendation=(
                                "Set securityContext.runAsNonRoot: true to"
                                " prevent the container from running as the"
                                " root user, reducing attack surface."
                            ),
                            evidence_locator=(
                                f"{file_path}:{resource_name}:{container_name}"
                            ),
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="k8s-non-root",
                        )
                    )

        if not findings:
            first = k8s_resources[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="All containers enforce runAsNonRoot.",
                    recommendation="No action required — non-root is enforced.",
                    evidence_locator="all-workloads",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.9,
                    pattern_tag="k8s-non-root",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "non-root-container-violation" not in rule_registry:
        rule_registry.register(
            "non-root-container-violation", NonRootContainerViolationRule()
        )


_register()

__all__ = ["NonRootContainerViolationRule"]
