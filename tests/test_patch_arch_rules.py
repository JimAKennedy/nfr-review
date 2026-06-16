"""Tests for PATCH-ARCH-001 through PATCH-ARCH-004 architectural readiness rules."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.patch_arch_graceful import GracefulShutdownMissingRule
from nfr_review.rules.patch_arch_pdb import PdbCoverageRule
from nfr_review.rules.patch_arch_singleton import SingletonDeploymentRule
from nfr_review.rules.patch_arch_strategy import UpdateStrategyRule


def _k8s_evidence(
    name: str = "my-deploy",
    file_path: str = "k8s/deployment.yaml",
    kind: str = "Deployment",
    namespace: str = "default",
    replicas: int | None = 3,
    containers: list[dict] | None = None,
    strategy: dict | str | None = None,
    update_strategy: dict | str | None = None,
    termination_grace_period: int | None = None,
    labels: dict | None = None,
    **extra: object,
) -> Evidence:
    payload: dict = {
        "file_path": file_path,
        "kind": kind,
        "name": name,
        "namespace": namespace,
        "containers": containers or [],
    }
    if replicas is not None:
        payload["replicas"] = replicas
    if strategy is not None:
        payload["strategy"] = strategy
    if update_strategy is not None:
        payload["updateStrategy"] = update_strategy
    if termination_grace_period is not None:
        payload["termination_grace_period"] = termination_grace_period
    if labels is not None:
        payload["labels"] = labels
    payload.update(extra)
    return Evidence(
        collector_name="k8s-manifest",
        collector_version="0.1.0",
        locator=f"{file_path}:{name}",
        kind="k8s-resource",
        payload=payload,
    )


def _pdb_evidence(
    name: str = "my-pdb",
    namespace: str = "default",
    match_labels: dict | None = None,
) -> Evidence:
    return Evidence(
        collector_name="k8s-manifest",
        collector_version="0.1.0",
        locator=f"k8s/pdb.yaml:{name}",
        kind="k8s-pdb",
        payload={
            "name": name,
            "namespace": namespace,
            "match_labels": match_labels,
        },
    )


# ---------------------------------------------------------------------------
# PATCH-ARCH-001: singleton-deployment
# ---------------------------------------------------------------------------


class TestSingletonDeploymentRule:
    def setup_method(self) -> None:
        self.rule = SingletonDeploymentRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-manifest evidence available"

    def test_singleton_replicas_one_red(self) -> None:
        ev = _k8s_evidence(replicas=1)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "critical"
        assert f.pattern_tag == "singleton-deployment"
        assert "explicitly set to 1" in f.summary

    def test_singleton_replicas_none_red(self) -> None:
        ev = _k8s_evidence(replicas=None)
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert "defaults to 1" in f.summary

    def test_multi_replica_green(self) -> None:
        ev = _k8s_evidence(replicas=3)
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert "3 replicas" in f.summary

    def test_daemonset_skipped_green_fallback(self) -> None:
        ev = _k8s_evidence(kind="DaemonSet")
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "No Deployment/StatefulSet" in result.findings[0].summary

    def test_statefulset_singleton_red(self) -> None:
        ev = _k8s_evidence(kind="StatefulSet", name="my-ss", replicas=1)
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "red"
        assert "StatefulSet" in result.findings[0].summary

    def test_mixed_resources(self) -> None:
        ev_ok = _k8s_evidence(name="healthy", replicas=3)
        ev_bad = _k8s_evidence(name="singleton", replicas=1)
        ev_ds = _k8s_evidence(name="ds", kind="DaemonSet")
        result = self.rule.evaluate([ev_ok, ev_bad, ev_ds], None)
        rags = [f.rag for f in result.findings]
        assert "green" in rags
        assert "red" in rags
        assert len(result.findings) == 2

    def test_evidence_locator_format(self) -> None:
        ev = _k8s_evidence(name="api", file_path="deploy/api.yaml", replicas=1)
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].evidence_locator == "deploy/api.yaml:api"


# ---------------------------------------------------------------------------
# PATCH-ARCH-002: graceful-shutdown
# ---------------------------------------------------------------------------


class TestGracefulShutdownMissingRule:
    def setup_method(self) -> None:
        self.rule = GracefulShutdownMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-manifest evidence available"

    def test_missing_prestop_amber(self) -> None:
        ev = _k8s_evidence(
            containers=[{"name": "app", "pre_stop": None}],
            termination_grace_period=60,
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) >= 1
        assert any("preStop" in f.summary for f in amber_findings)
        assert amber_findings[0].pattern_tag == "graceful-shutdown"

    def test_low_grace_period_amber(self) -> None:
        ev = _k8s_evidence(
            containers=[{"name": "app", "pre_stop": {"exec": {"command": ["sleep", "5"]}}}],
            termination_grace_period=10,
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) == 1
        assert "10s" in amber_findings[0].summary
        assert "terminationGracePeriodSeconds" in amber_findings[0].summary

    def test_no_grace_period_amber(self) -> None:
        ev = _k8s_evidence(
            containers=[{"name": "app", "pre_stop": {"exec": {"command": ["sleep", "5"]}}}],
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) == 1
        assert "not set (defaults to 30s)" in amber_findings[0].summary

    def test_all_configured_green(self) -> None:
        ev = _k8s_evidence(
            containers=[
                {"name": "app", "pre_stop": {"exec": {"command": ["sleep", "5"]}}},
                {"name": "sidecar", "pre_stop": {"httpGet": {"path": "/stop", "port": 8080}}},
            ],
            termination_grace_period=60,
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "preStop hooks" in result.findings[0].summary

    def test_evidence_locator_includes_container(self) -> None:
        ev = _k8s_evidence(
            name="web",
            file_path="k8s/web.yaml",
            containers=[{"name": "nginx", "pre_stop": None}],
            termination_grace_period=60,
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert amber_findings[0].evidence_locator == "k8s/web.yaml:web:nginx"

    def test_multiple_containers_missing_prestop(self) -> None:
        ev = _k8s_evidence(
            containers=[
                {"name": "app", "pre_stop": None},
                {"name": "sidecar", "pre_stop": None},
            ],
            termination_grace_period=60,
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) == 2
        names = {f.summary for f in amber_findings}
        assert any("app" in s for s in names)
        assert any("sidecar" in s for s in names)

    def test_grace_period_exactly_30_is_ok(self) -> None:
        ev = _k8s_evidence(
            containers=[{"name": "app", "pre_stop": {"exec": {"command": ["true"]}}}],
            termination_grace_period=30,
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# PATCH-ARCH-003: update-strategy
# ---------------------------------------------------------------------------


class TestUpdateStrategyRule:
    def setup_method(self) -> None:
        self.rule = UpdateStrategyRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-manifest evidence available"

    # -- Deployment paths --

    def test_deployment_no_strategy_amber(self) -> None:
        ev = _k8s_evidence()
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert "no explicit strategy" in f.summary
        assert f.pattern_tag == "update-strategy"

    def test_deployment_recreate_amber(self) -> None:
        ev = _k8s_evidence(strategy={"type": "Recreate"})
        result = self.rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert "Recreate" in f.summary
        assert "downtime" in f.summary

    def test_deployment_rolling_safe_green(self) -> None:
        ev = _k8s_evidence(
            strategy={"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 1}},
        )
        result = self.rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rag == "green"
        assert "RollingUpdate" in f.summary

    def test_deployment_rolling_high_max_unavailable_amber(self) -> None:
        ev = _k8s_evidence(
            strategy={"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 5}},
        )
        result = self.rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert "high" in f.summary

    def test_deployment_rolling_percentage_safe(self) -> None:
        ev = _k8s_evidence(
            strategy={"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": "25%"}},
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_deployment_rolling_percentage_unsafe(self) -> None:
        ev = _k8s_evidence(
            strategy={"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": "50%"}},
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"

    def test_deployment_rolling_default_max_unavailable_safe(self) -> None:
        ev = _k8s_evidence(
            strategy={"type": "RollingUpdate", "rollingUpdate": {}},
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"
        assert "defaults to 25%" in result.findings[0].summary

    # -- StatefulSet paths --

    def test_statefulset_no_strategy_amber(self) -> None:
        ev = _k8s_evidence(kind="StatefulSet", name="my-ss")
        result = self.rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert "no explicit updateStrategy" in f.summary

    def test_statefulset_on_delete_amber(self) -> None:
        ev = _k8s_evidence(
            kind="StatefulSet",
            name="my-ss",
            update_strategy={"type": "OnDelete"},
        )
        result = self.rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert "OnDelete" in f.summary

    def test_statefulset_rolling_green(self) -> None:
        ev = _k8s_evidence(
            kind="StatefulSet",
            name="my-ss",
            update_strategy={"type": "RollingUpdate"},
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    # -- Edge cases --

    def test_daemonset_skipped(self) -> None:
        ev = _k8s_evidence(kind="DaemonSet", strategy={"type": "Recreate"})
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "No Deployment/StatefulSet" in result.findings[0].summary

    def test_mixed_deployment_and_statefulset(self) -> None:
        ev_deploy = _k8s_evidence(
            name="api",
            strategy={"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 1}},
        )
        ev_ss = _k8s_evidence(
            kind="StatefulSet",
            name="db",
            update_strategy={"type": "OnDelete"},
        )
        result = self.rule.evaluate([ev_deploy, ev_ss], None)
        rags = {f.rag for f in result.findings}
        assert "green" in rags
        assert "amber" in rags


# ---------------------------------------------------------------------------
# PATCH-ARCH-004: pdb-coverage
# ---------------------------------------------------------------------------


class TestPdbCoverageRule:
    def setup_method(self) -> None:
        self.rule = PdbCoverageRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-manifest evidence available"

    def test_multi_replica_no_pdb_amber(self) -> None:
        ev = _k8s_evidence(replicas=3, labels={"app": "web"})
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert f.pattern_tag == "pdb-coverage"
        assert "3 replicas" in f.summary
        assert "no matching PodDisruptionBudget" in f.summary

    def test_multi_replica_with_matching_pdb_green(self) -> None:
        ev = _k8s_evidence(replicas=3, labels={"app": "web"})
        pdb = _pdb_evidence(name="web-pdb", match_labels={"app": "web"})
        result = self.rule.evaluate([ev, pdb], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert "web-pdb" in f.summary

    def test_singleton_not_checked(self) -> None:
        ev = _k8s_evidence(replicas=1, labels={"app": "web"})
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "No multi-replica" in result.findings[0].summary

    def test_replicas_none_not_checked(self) -> None:
        ev = _k8s_evidence(replicas=None, labels={"app": "web"})
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"
        assert "No multi-replica" in result.findings[0].summary

    def test_pdb_wrong_namespace_no_match(self) -> None:
        ev = _k8s_evidence(replicas=3, namespace="prod", labels={"app": "web"})
        pdb = _pdb_evidence(namespace="staging", match_labels={"app": "web"})
        result = self.rule.evaluate([ev, pdb], None)
        assert result.findings[0].rag == "amber"

    def test_pdb_partial_label_match(self) -> None:
        ev = _k8s_evidence(replicas=3, labels={"app": "web", "tier": "frontend"})
        pdb = _pdb_evidence(match_labels={"app": "web"})
        result = self.rule.evaluate([ev, pdb], None)
        assert result.findings[0].rag == "green"

    def test_pdb_label_mismatch(self) -> None:
        ev = _k8s_evidence(replicas=3, labels={"app": "web"})
        pdb = _pdb_evidence(match_labels={"app": "api"})
        result = self.rule.evaluate([ev, pdb], None)
        assert result.findings[0].rag == "amber"

    def test_no_labels_namespace_fallback(self) -> None:
        ev = _k8s_evidence(replicas=3)
        pdb = _pdb_evidence(namespace="default", match_labels={"app": "anything"})
        result = self.rule.evaluate([ev, pdb], None)
        assert result.findings[0].rag == "green"

    def test_daemonset_not_checked(self) -> None:
        ev = _k8s_evidence(kind="DaemonSet", replicas=3)
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"
        assert "No multi-replica" in result.findings[0].summary

    def test_statefulset_multi_replica_no_pdb(self) -> None:
        ev = _k8s_evidence(kind="StatefulSet", name="db", replicas=3, labels={"app": "db"})
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"
        assert "StatefulSet" in result.findings[0].summary

    def test_multiple_workloads_mixed(self) -> None:
        ev_covered = _k8s_evidence(name="api", replicas=3, labels={"app": "api"})
        ev_uncovered = _k8s_evidence(name="worker", replicas=2, labels={"app": "worker"})
        pdb = _pdb_evidence(match_labels={"app": "api"})
        result = self.rule.evaluate([ev_covered, ev_uncovered, pdb], None)
        rags = [f.rag for f in result.findings]
        assert "green" in rags
        assert "amber" in rags
        assert len(result.findings) == 2
