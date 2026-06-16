# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dockerfile-k8s-user-conflict — detects when a Dockerfile sets a
non-root USER but the K8s deployment overrides it with runAsUser: 0."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_ROOT_NAMES = frozenset({"root", "0"})


def _is_nonroot_user(user: str) -> bool:
    """Return True if the USER directive sets a non-root user."""
    return user.strip() not in _ROOT_NAMES and user.strip() != ""


def _runasuser_is_root(security_context: dict[str, Any] | None) -> bool:
    """Return True if the securityContext explicitly sets runAsUser: 0."""
    if not isinstance(security_context, dict):
        return False
    run_as_user = security_context.get("runAsUser")
    return run_as_user == 0


class DockerfileK8sUserConflictRule:
    """Flag deployments that override a Dockerfile non-root USER with runAsUser: 0."""

    id = "dockerfile-k8s-user-conflict"
    band: Band = 1
    required_collectors: list[str] = ["dockerfile", "k8s-manifest"]
    required_tech: list[str] = ["dockerfile", "kubernetes"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        df_evidence = filter_evidence(evidence, "dockerfile", "dockerfile-analysis")
        k8s_evidence = filter_evidence(evidence, "k8s-manifest", "k8s-resource")

        if not df_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no dockerfile evidence available",
            )
        if not k8s_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no k8s-manifest evidence available",
            )

        # Determine whether any Dockerfile sets a non-root user
        dockerfile_nonroot = False
        dockerfile_path = ""
        for ev in df_evidence:
            user_directives = ev.payload.user_directives
            for directive in user_directives:
                user = directive.get("user", "")
                if _is_nonroot_user(user):
                    dockerfile_nonroot = True
                    dockerfile_path = ev.payload.file_path
                    break
            if dockerfile_nonroot:
                break

        if not dockerfile_nonroot:
            # No non-root USER in any Dockerfile — rule doesn't apply
            first_k8s = k8s_evidence[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "dockerfile-k8s-user-conflict",
                        first_k8s,
                        summary=(
                            "No Dockerfile non-root USER / K8s runAsUser:0 conflict detected."
                        ),
                        confidence=0.8,
                        evidence_locator="all-artifacts",
                    )
                ],
            )

        findings: list[Finding] = []
        for ev in k8s_evidence:
            resource_name = ev.payload.name
            file_path = ev.payload.file_path

            # Check pod-level securityContext
            pod_sc = ev.payload.security_context
            if _runasuser_is_root(pod_sc):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(
                            f"K8s resource '{resource_name}' pod-level securityContext sets"
                            f" runAsUser: 0, overriding non-root USER in '{dockerfile_path}'."
                        ),
                        recommendation=(
                            "Remove runAsUser: 0 from the pod securityContext or align"
                            " the Dockerfile USER directive with the K8s security context."
                        ),
                        evidence_locator=f"{file_path}:{resource_name}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="dockerfile-k8s-user-conflict",
                    )
                )
                continue

            # Check container-level securityContext
            for container in ev.payload.containers:
                container_name = container.get("name", "")
                container_sc = container.get("security_context")
                if _runasuser_is_root(container_sc):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="high",
                            summary=(
                                f"Container '{container_name}' in '{resource_name}'"
                                f" sets runAsUser: 0, overriding non-root USER"
                                f" in '{dockerfile_path}'."
                            ),
                            recommendation=(
                                "Remove runAsUser: 0 from the container securityContext or"
                                " align the Dockerfile USER directive with the K8s security"
                                " context."
                            ),
                            evidence_locator=f"{file_path}:{resource_name}:{container_name}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.95,
                            pattern_tag="dockerfile-k8s-user-conflict",
                        )
                    )

        if not findings:
            first_k8s = k8s_evidence[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "dockerfile-k8s-user-conflict",
                    first_k8s,
                    summary=(
                        "Dockerfile non-root USER is not overridden by runAsUser: 0"
                        " in any K8s resource."
                    ),
                    confidence=0.9,
                    evidence_locator="all-workloads",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "dockerfile-k8s-user-conflict" not in rule_registry:
        rule_registry.register("dockerfile-k8s-user-conflict", DockerfileK8sUserConflictRule())


_register()

__all__ = ["DockerfileK8sUserConflictRule"]
