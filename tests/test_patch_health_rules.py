"""Tests for PATCH-HEALTH-001 through PATCH-HEALTH-004 probe/health rules."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.patch_health_probes import PatchingProbePresenceRule
from nfr_review.rules.patch_health_startup import StartupProbeMissingRule
from nfr_review.rules.patch_health_termination import TerminationGracePeriodRule
from nfr_review.rules.patch_health_trivial_probe import TrivialProbeRule


def _k8s_ev(
    name: str = "my-deploy",
    kind: str = "Deployment",
    containers: list[dict] | None = None,
    replicas: int | None = None,
    termination_grace_period: int | None = None,
    file_path: str = "k8s/deployment.yaml",
) -> Evidence:
    payload: dict = {
        "file_path": file_path,
        "kind": kind,
        "name": name,
        "namespace": "default",
        "containers": containers or [],
    }
    if replicas is not None:
        payload["replicas"] = replicas
    if termination_grace_period is not None:
        payload["termination_grace_period"] = termination_grace_period
    return Evidence(
        collector_name="k8s-manifest",
        collector_version="0.1.0",
        locator=f"{file_path}:{name}",
        kind="k8s-resource",
        payload=payload,
    )


def _container(
    name: str = "app",
    liveness_probe: dict | None = None,
    readiness_probe: dict | None = None,
    startup_probe: dict | None = None,
    pre_stop: dict | None = None,
) -> dict:
    return {
        "name": name,
        "image": "nginx:latest",
        "resources": None,
        "liveness_probe": liveness_probe,
        "readiness_probe": readiness_probe,
        "security_context": None,
        "startup_probe": startup_probe,
        "pre_stop": pre_stop,
    }


# ---------------------------------------------------------------------------
# PATCH-HEALTH-001 — readiness probe presence
# ---------------------------------------------------------------------------


class TestPatchHealthProbes001:
    def setup_method(self) -> None:
        self.rule = PatchingProbePresenceRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-manifest evidence available"

    def test_multi_replica_no_readiness_red(self) -> None:
        ev = _k8s_ev(
            replicas=3,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "critical"
        assert result.findings[0].pattern_tag == "patch-health-probes"
        assert "readinessProbe" in result.findings[0].summary

    def test_singleton_no_readiness_amber(self) -> None:
        ev = _k8s_ev(
            replicas=1,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "high"

    def test_unset_replicas_treated_as_singleton_amber(self) -> None:
        ev = _k8s_ev(
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"

    def test_both_probes_green(self) -> None:
        ev = _k8s_ev(
            replicas=3,
            containers=[
                _container(
                    liveness_probe={"httpGet": {"path": "/health", "port": 8080}},
                    readiness_probe={"httpGet": {"path": "/ready", "port": 8080}},
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_readiness_only_green(self) -> None:
        ev = _k8s_ev(
            replicas=3,
            containers=[
                _container(
                    readiness_probe={"httpGet": {"path": "/ready", "port": 8080}},
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"
        assert "patching-safe" in result.findings[0].summary

    def test_non_workload_kind_skipped(self) -> None:
        ev = _k8s_ev(kind="ConfigMap", containers=[])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert "No Deployment/StatefulSet" in result.findings[0].summary

    def test_statefulset_handled(self) -> None:
        ev = _k8s_ev(
            kind="StatefulSet",
            replicas=3,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "red"

    def test_multiple_containers_mixed(self) -> None:
        ev = _k8s_ev(
            replicas=3,
            containers=[
                _container(
                    name="app",
                    readiness_probe={"httpGet": {"path": "/ready", "port": 8080}},
                    liveness_probe={"httpGet": {"path": "/health", "port": 8080}},
                ),
                _container(name="sidecar"),
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 2
        rags = {f.rag for f in result.findings}
        assert "green" in rags
        assert "red" in rags


# ---------------------------------------------------------------------------
# PATCH-HEALTH-002 — trivial probe detection
# ---------------------------------------------------------------------------


class TestTrivialProbeRule002:
    def setup_method(self) -> None:
        self.rule = TrivialProbeRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_no_readiness_probes_skipped(self) -> None:
        ev = _k8s_ev(containers=[_container()])
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True
        assert "no readiness probes" in result.skip_reason

    def test_tcp_socket_only_amber(self) -> None:
        ev = _k8s_ev(
            containers=[
                _container(
                    readiness_probe={
                        "tcpSocket": {"port": 8080},
                        "periodSeconds": 10,
                        "failureThreshold": 3,
                    },
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) == 1
        assert "tcpSocket" in amber_findings[0].summary
        assert amber_findings[0].pattern_tag == "trivial-probe"

    def test_http_get_not_flagged_as_tcp(self) -> None:
        ev = _k8s_ev(
            containers=[
                _container(
                    readiness_probe={
                        "httpGet": {"path": "/ready", "port": 8080},
                        "periodSeconds": 10,
                        "failureThreshold": 3,
                    },
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_aggressive_timing_amber(self) -> None:
        ev = _k8s_ev(
            containers=[
                _container(
                    readiness_probe={
                        "httpGet": {"path": "/ready", "port": 8080},
                        "initialDelaySeconds": 0,
                        "periodSeconds": 2,
                        "failureThreshold": 3,
                    },
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) == 1
        assert "aggressive probe timing" in amber_findings[0].summary

    def test_safe_timing_no_flag(self) -> None:
        ev = _k8s_ev(
            containers=[
                _container(
                    readiness_probe={
                        "httpGet": {"path": "/ready", "port": 8080},
                        "initialDelaySeconds": 10,
                        "periodSeconds": 10,
                        "failureThreshold": 3,
                    },
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_failure_threshold_one_amber(self) -> None:
        ev = _k8s_ev(
            containers=[
                _container(
                    readiness_probe={
                        "httpGet": {"path": "/ready", "port": 8080},
                        "initialDelaySeconds": 10,
                        "periodSeconds": 10,
                        "failureThreshold": 1,
                    },
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) == 1
        assert "failureThreshold=1" in amber_findings[0].summary

    def test_failure_threshold_default_no_flag(self) -> None:
        ev = _k8s_ev(
            containers=[
                _container(
                    readiness_probe={
                        "httpGet": {"path": "/ready", "port": 8080},
                        "initialDelaySeconds": 10,
                        "periodSeconds": 10,
                    },
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_multiple_anti_patterns_multiple_findings(self) -> None:
        ev = _k8s_ev(
            containers=[
                _container(
                    readiness_probe={
                        "tcpSocket": {"port": 8080},
                        "initialDelaySeconds": 0,
                        "periodSeconds": 1,
                        "failureThreshold": 1,
                    },
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) == 3

    def test_period_defaults_to_10_when_missing(self) -> None:
        ev = _k8s_ev(
            containers=[
                _container(
                    readiness_probe={
                        "httpGet": {"path": "/ready", "port": 8080},
                        "initialDelaySeconds": 0,
                    },
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# PATCH-HEALTH-003 — startup probe presence
# ---------------------------------------------------------------------------


class TestStartupProbeRule003:
    def setup_method(self) -> None:
        self.rule = StartupProbeMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_multi_replica_no_startup_probe_amber(self) -> None:
        ev = _k8s_ev(
            replicas=3,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "high"
        assert "startupProbe" in result.findings[0].summary
        assert result.findings[0].pattern_tag == "patch-health-startup"

    def test_multi_replica_with_startup_probe_green(self) -> None:
        ev = _k8s_ev(
            replicas=3,
            containers=[
                _container(
                    startup_probe={"httpGet": {"path": "/started", "port": 8080}},
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"
        assert "startupProbe configured" in result.findings[0].summary

    def test_singleton_no_startup_probe_green(self) -> None:
        ev = _k8s_ev(
            replicas=1,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"
        assert "singleton" in result.findings[0].summary

    def test_unset_replicas_treated_as_singleton_green(self) -> None:
        ev = _k8s_ev(containers=[_container()])
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_daemonset_always_green(self) -> None:
        ev = _k8s_ev(
            kind="DaemonSet",
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "DaemonSet" in result.findings[0].summary

    def test_configmap_ignored(self) -> None:
        ev = _k8s_ev(kind="ConfigMap", containers=[])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert "No Deployment/StatefulSet/DaemonSet" in result.findings[0].summary

    def test_statefulset_multi_replica_amber(self) -> None:
        ev = _k8s_ev(
            kind="StatefulSet",
            replicas=3,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"


# ---------------------------------------------------------------------------
# PATCH-HEALTH-004 — termination grace period
# ---------------------------------------------------------------------------


class TestTerminationGracePeriodRule004:
    def setup_method(self) -> None:
        self.rule = TerminationGracePeriodRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_low_grace_period_amber(self) -> None:
        ev = _k8s_ev(
            termination_grace_period=10,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "terminationGracePeriodSeconds=10" in result.findings[0].summary
        assert result.findings[0].pattern_tag == "patch-health-termination"

    def test_default_grace_no_prestop_amber(self) -> None:
        ev = _k8s_ev(
            termination_grace_period=30,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "preStop" in result.findings[0].summary

    def test_default_grace_with_unset_termination_no_prestop_amber(self) -> None:
        ev = _k8s_ev(containers=[_container()])
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"
        assert "default" in result.findings[0].summary.lower()

    def test_none_grace_period_treated_as_default(self) -> None:
        """Payload may contain termination_grace_period=None (parsed but unset)."""
        ev = _k8s_ev(containers=[_container()])
        ev.payload["termination_grace_period"] = None
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"
        assert "default" in result.findings[0].summary.lower()

    def test_sufficient_grace_with_prestop_green(self) -> None:
        ev = _k8s_ev(
            termination_grace_period=60,
            containers=[
                _container(pre_stop={"exec": {"command": ["sleep", "5"]}}),
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "preStop hook configured" in result.findings[0].summary

    def test_high_grace_no_prestop_falls_through(self) -> None:
        ev = _k8s_ev(
            termination_grace_period=60,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert (
            result.findings[0].summary == "All workloads pass termination grace period checks."
        )

    def test_prestop_on_any_container_counts(self) -> None:
        ev = _k8s_ev(
            termination_grace_period=30,
            containers=[
                _container(name="app"),
                _container(
                    name="sidecar",
                    pre_stop={"exec": {"command": ["sleep", "3"]}},
                ),
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_multiple_resources(self) -> None:
        ev1 = _k8s_ev(
            name="good-deploy",
            termination_grace_period=60,
            containers=[
                _container(pre_stop={"exec": {"command": ["sleep", "5"]}}),
            ],
        )
        ev2 = _k8s_ev(
            name="bad-deploy",
            termination_grace_period=5,
            containers=[_container()],
        )
        result = self.rule.evaluate([ev1, ev2], None)
        assert len(result.findings) == 2
        rags = {f.rag for f in result.findings}
        assert "green" in rags
        assert "amber" in rags
