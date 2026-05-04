"""Tests for K8s Band 1 rules — positive and negative fixtures."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.k8s_network import NetworkPolicyMissingRule
from nfr_review.rules.k8s_probes import ProbesMissingRule
from nfr_review.rules.k8s_resources import ResourceLimitsMissingRule
from nfr_review.rules.k8s_security import NonRootContainerViolationRule


def _k8s_resource_evidence(
    name: str = "my-deploy",
    file_path: str = "k8s/deployment.yaml",
    containers: list[dict] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="k8s-manifest",
        collector_version="0.1.0",
        locator=f"{file_path}:{name}",
        kind="k8s-resource",
        payload={
            "file_path": file_path,
            "kind": "Deployment",
            "name": name,
            "namespace": "default",
            "containers": containers or [],
        },
    )


def _k8s_summary_evidence(
    has_network_policy: bool = False,
    resource_counts: dict | None = None,
) -> Evidence:
    return Evidence(
        collector_name="k8s-manifest",
        collector_version="0.1.0",
        locator="/repo",
        kind="k8s-manifest-summary",
        payload={
            "resource_counts": resource_counts or {},
            "has_network_policy": has_network_policy,
            "files_parsed": 1,
            "files_failed": 0,
        },
    )


# ---------------------------------------------------------------------------
# resource-limits-missing
# ---------------------------------------------------------------------------


class TestResourceLimitsMissingRule:
    def setup_method(self) -> None:
        self.rule = ResourceLimitsMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-manifest evidence available"

    def test_container_without_limits_amber(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest", "resources": None,
             "liveness_probe": None, "readiness_probe": None, "security_context": None},
        ])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "high"
        assert result.findings[0].pattern_tag == "k8s-resource-limits"
        assert "app" in result.findings[0].evidence_locator

    def test_container_with_empty_limits_amber(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest",
             "resources": {"requests": {"cpu": "100m"}},
             "liveness_probe": None, "readiness_probe": None, "security_context": None},
        ])
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"

    def test_container_with_limits_green(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest",
             "resources": {"limits": {"cpu": "500m", "memory": "256Mi"}},
             "liveness_probe": None, "readiness_probe": None, "security_context": None},
        ])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_multiple_containers_mixed(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest",
             "resources": {"limits": {"cpu": "500m"}},
             "liveness_probe": None, "readiness_probe": None, "security_context": None},
            {"name": "sidecar", "image": "envoy:latest",
             "resources": None,
             "liveness_probe": None, "readiness_probe": None, "security_context": None},
        ])
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "sidecar" in result.findings[0].summary

    def test_only_summary_evidence_skipped(self) -> None:
        ev = _k8s_summary_evidence()
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# probes-missing
# ---------------------------------------------------------------------------


class TestProbesMissingRule:
    def setup_method(self) -> None:
        self.rule = ProbesMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-manifest evidence available"

    def test_container_without_probes_amber(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest", "resources": None,
             "liveness_probe": None, "readiness_probe": None, "security_context": None},
        ])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "high"
        assert "livenessProbe" in result.findings[0].summary
        assert "readinessProbe" in result.findings[0].summary

    def test_container_missing_only_liveness_amber(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest", "resources": None,
             "liveness_probe": None,
             "readiness_probe": {"httpGet": {"path": "/ready", "port": 8080}},
             "security_context": None},
        ])
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"
        assert "livenessProbe" in result.findings[0].summary
        assert "readinessProbe" not in result.findings[0].summary

    def test_container_with_both_probes_green(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest", "resources": None,
             "liveness_probe": {"httpGet": {"path": "/health", "port": 8080}},
             "readiness_probe": {"httpGet": {"path": "/ready", "port": 8080}},
             "security_context": None},
        ])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "k8s-probes"

    def test_only_summary_evidence_skipped(self) -> None:
        ev = _k8s_summary_evidence()
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# non-root-container-violation
# ---------------------------------------------------------------------------


class TestNonRootContainerViolationRule:
    def setup_method(self) -> None:
        self.rule = NonRootContainerViolationRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-manifest evidence available"

    def test_container_without_security_context_amber(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest", "resources": None,
             "liveness_probe": None, "readiness_probe": None, "security_context": None},
        ])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert "runAsNonRoot" in result.findings[0].summary

    def test_container_with_run_as_non_root_false_amber(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest", "resources": None,
             "liveness_probe": None, "readiness_probe": None,
             "security_context": {"runAsNonRoot": False}},
        ])
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"

    def test_container_with_run_as_non_root_true_green(self) -> None:
        ev = _k8s_resource_evidence(containers=[
            {"name": "app", "image": "nginx:latest", "resources": None,
             "liveness_probe": None, "readiness_probe": None,
             "security_context": {"runAsNonRoot": True}},
        ])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "k8s-non-root"

    def test_only_summary_evidence_skipped(self) -> None:
        ev = _k8s_summary_evidence()
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# network-policy-missing
# ---------------------------------------------------------------------------


class TestNetworkPolicyMissingRule:
    def setup_method(self) -> None:
        self.rule = NetworkPolicyMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-manifest evidence available"

    def test_no_network_policy_amber(self) -> None:
        ev = _k8s_summary_evidence(has_network_policy=False)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert result.findings[0].pattern_tag == "k8s-network-policy"

    def test_has_network_policy_green(self) -> None:
        ev = _k8s_summary_evidence(has_network_policy=True)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "k8s-network-policy"

    def test_only_resource_evidence_skipped(self) -> None:
        ev = _k8s_resource_evidence(containers=[])
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True
