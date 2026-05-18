"""Tests for PATCH-DEPS rules (001, 002, 003)."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.patch_deps import (
    CrossRingDependencyRule,
    DependencyDeclarationRule,
    SharedFateIndicatorRule,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COL = "k8s-manifest"
_VER = "0.1.0"


def _k8s_ev(
    name: str,
    kind: str = "Deployment",
    annotations: dict | None = None,
    labels: dict | None = None,
    node_selector: dict | None = None,
    containers: list[dict] | None = None,
    locator: str | None = None,
) -> Evidence:
    return Evidence(
        collector_name=_COL,
        collector_version=_VER,
        locator=locator or f"k8s/{name}.yaml:{name}",
        kind="k8s-resource",
        payload={
            "file_path": f"k8s/{name}.yaml",
            "kind": kind,
            "name": name,
            "namespace": "default",
            "annotations": annotations,
            "labels": labels,
            "replicas": 2,
            "strategy": None,
            "node_selector": node_selector,
            "node_affinity": None,
            "anti_affinity": None,
            "termination_grace_period": 30,
            "containers": containers
            or [{"name": name, "image": f"{name}:latest", "env": None}],
        },
    )


def _summary_ev(resource_counts: dict | None = None) -> Evidence:
    return Evidence(
        collector_name=_COL,
        collector_version=_VER,
        locator=".",
        kind="k8s-manifest-summary",
        payload={
            "resource_counts": resource_counts or {"Deployment": 1},
            "has_network_policy": False,
            "files_parsed": 1,
            "files_failed": 0,
        },
    )


def _container(
    name: str = "app",
    env: list[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "image": f"{name}:latest",
        "env": env,
    }


# ===========================================================================
# PATCH-DEPS-001: Dependency declaration detection
# ===========================================================================


class TestDeps001:
    rule = DependencyDeclarationRule()

    def test_skipped_when_no_k8s_evidence(self):
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no k8s-manifest" in result.skip_reason

    def test_no_workloads_info(self):
        ev = [_summary_ev()]
        result = self.rule.evaluate(ev, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()

    def test_workload_with_part_of_annotation_green(self):
        ev = [
            _k8s_ev("api-svc", annotations={"app.kubernetes.io/part-of": "payments"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "app.kubernetes.io/part-of" in result.findings[0].summary

    def test_workload_with_backstage_annotation_green(self):
        ev = [
            _k8s_ev("web", annotations={"backstage.io/techdocs-ref": "dir:docs/"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_workload_with_backstage_system_annotation_green(self):
        ev = [
            _k8s_ev("web", annotations={"backstage.io/system": "checkout"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_workload_with_custom_depends_on_green(self):
        ev = [
            _k8s_ev("worker", annotations={"depends-on": "api-svc,cache"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_workload_no_annotations_amber(self):
        ev = [
            _k8s_ev("api-svc", annotations=None),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "no dependency declaration" in result.findings[0].summary.lower()

    def test_workload_with_unrelated_annotations_amber(self):
        ev = [
            _k8s_ev("api-svc", annotations={"prometheus.io/scrape": "true"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_mixed_workloads(self):
        ev = [
            _k8s_ev("api-svc", annotations={"app.kubernetes.io/part-of": "platform"}),
            _k8s_ev("worker", annotations=None),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 2
        rags = [f.rag for f in result.findings]
        assert "green" in rags
        assert "amber" in rags

    def test_finding_metadata(self):
        ev = [
            _k8s_ev("svc", annotations={"app.kubernetes.io/part-of": "x"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        f = result.findings[0]
        assert f.rule_id == "PATCH-DEPS-001"
        assert f.pattern_tag == "patch-deps-declaration"
        assert f.collector_name == _COL

    def test_rule_id_and_band(self):
        assert self.rule.id == "PATCH-DEPS-001"
        assert self.rule.band == 2


# ===========================================================================
# PATCH-DEPS-002: Shared-fate indicator detection
# ===========================================================================


class TestDeps002:
    rule = SharedFateIndicatorRule()

    def test_skipped_when_no_k8s_evidence(self):
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no k8s-manifest" in result.skip_reason

    def test_no_workloads_info(self):
        ev = [_summary_ev()]
        result = self.rule.evaluate(ev, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_shared_node_selector_amber(self):
        ns = {"nodepool": "high-mem"}
        ev = [
            _k8s_ev("api-svc", node_selector=ns),
            _k8s_ev("worker", node_selector=ns),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        ambers = [f for f in result.findings if f.rag == "amber"]
        assert len(ambers) == 1
        assert "api-svc" in ambers[0].summary
        assert "worker" in ambers[0].summary
        assert "nodeSelector" in ambers[0].summary

    def test_different_node_selectors_green(self):
        ev = [
            _k8s_ev("api-svc", node_selector={"nodepool": "high-mem"}),
            _k8s_ev("worker", node_selector={"nodepool": "general"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_shared_db_host_amber(self):
        db_env = [{"name": "DB_HOST", "value": "pg-primary.db.svc.cluster.local"}]
        ev = [
            _k8s_ev("api-svc", containers=[_container("api", env=db_env)]),
            _k8s_ev("worker", containers=[_container("worker", env=db_env)]),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        ambers = [f for f in result.findings if f.rag == "amber"]
        assert len(ambers) == 1
        assert "database host" in ambers[0].summary.lower()
        assert "api-svc" in ambers[0].summary
        assert "worker" in ambers[0].summary

    def test_different_db_hosts_green(self):
        ev = [
            _k8s_ev(
                "api-svc",
                containers=[
                    _container("api", env=[{"name": "DB_HOST", "value": "pg-a.local"}])
                ],
            ),
            _k8s_ev(
                "worker",
                containers=[_container("w", env=[{"name": "DB_HOST", "value": "pg-b.local"}])],
            ),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_single_workload_no_shared_fate(self):
        ev = [
            _k8s_ev("api-svc", node_selector={"nodepool": "high-mem"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_both_node_and_db_shared(self):
        ns = {"nodepool": "high-mem"}
        db_env = [{"name": "DATABASE_HOST", "value": "shared-db"}]
        ev = [
            _k8s_ev("svc-a", node_selector=ns, containers=[_container("a", env=db_env)]),
            _k8s_ev("svc-b", node_selector=ns, containers=[_container("b", env=db_env)]),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        ambers = [f for f in result.findings if f.rag == "amber"]
        assert len(ambers) == 2

    def test_no_env_no_node_selector_green(self):
        ev = [
            _k8s_ev("api-svc"),
            _k8s_ev("worker"),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_finding_metadata(self):
        ns = {"nodepool": "same"}
        ev = [
            _k8s_ev("a", node_selector=ns),
            _k8s_ev("b", node_selector=ns),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        f = [f for f in result.findings if f.rag == "amber"][0]
        assert f.rule_id == "PATCH-DEPS-002"
        assert f.pattern_tag == "patch-deps-shared-fate"

    def test_rule_id_and_band(self):
        assert self.rule.id == "PATCH-DEPS-002"
        assert self.rule.band == 1


# ===========================================================================
# PATCH-DEPS-003: Cross-ring dependency direction
# ===========================================================================


class TestDeps003:
    rule = CrossRingDependencyRule()

    def test_skipped_when_no_k8s_evidence(self):
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no k8s-manifest" in result.skip_reason

    def test_no_workloads_info(self):
        ev = [_summary_ev()]
        result = self.rule.evaluate(ev, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_no_ring_labels_info(self):
        ev = [
            _k8s_ev("api-svc", labels={"app": "api"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "no ring labels" in result.findings[0].summary.lower()

    def test_higher_ring_depends_on_lower_amber(self):
        ev = [
            _k8s_ev(
                "frontend",
                labels={"ring": "2"},
                containers=[
                    _container(
                        "fe",
                        env=[
                            {
                                "name": "API_URL",
                                "value": "http://backend.default.svc.cluster.local:8080",
                            }
                        ],
                    )
                ],
            ),
            _k8s_ev("backend", labels={"ring": "1"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        ambers = [f for f in result.findings if f.rag == "amber"]
        assert len(ambers) == 1
        assert "frontend" in ambers[0].summary
        assert "backend" in ambers[0].summary
        assert "ring 2" in ambers[0].summary
        assert "ring 1" in ambers[0].summary

    def test_lower_ring_depends_on_higher_green(self):
        ev = [
            _k8s_ev(
                "backend",
                labels={"ring": "1"},
                containers=[
                    _container(
                        "be",
                        env=[
                            {
                                "name": "CACHE_URL",
                                "value": "http://cache.default.svc.cluster.local",
                            }
                        ],
                    )
                ],
            ),
            _k8s_ev("cache", labels={"ring": "2"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "no cross-ring" in result.findings[0].summary.lower()

    def test_same_ring_no_violation(self):
        ev = [
            _k8s_ev(
                "svc-a",
                labels={"ring": "1"},
                containers=[
                    _container(
                        "a",
                        env=[
                            {"name": "PEER", "value": "http://svc-b.default.svc.cluster.local"}
                        ],
                    )
                ],
            ),
            _k8s_ev("svc-b", labels={"ring": "1"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_custom_ring_label_key(self):
        ev = [
            _k8s_ev(
                "frontend",
                labels={"app.kubernetes.io/ring": "2"},
                containers=[
                    _container(
                        "fe",
                        env=[{"name": "API", "value": "http://backend.ns.svc.cluster.local"}],
                    )
                ],
            ),
            _k8s_ev("backend", labels={"app.kubernetes.io/ring": "1"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        ambers = [f for f in result.findings if f.rag == "amber"]
        assert len(ambers) == 1

    def test_finding_metadata(self):
        ev = [
            _k8s_ev(
                "fe",
                labels={"ring": "2"},
                containers=[
                    _container(
                        "c", env=[{"name": "X", "value": "http://be.ns.svc.cluster.local"}]
                    )
                ],
            ),
            _k8s_ev("be", labels={"ring": "1"}),
            _summary_ev(),
        ]
        result = self.rule.evaluate(ev, None)
        f = [f for f in result.findings if f.rag == "amber"][0]
        assert f.rule_id == "PATCH-DEPS-003"
        assert f.pattern_tag == "patch-deps-cross-ring"
        assert f.severity == "high"

    def test_rule_id_and_band(self):
        assert self.rule.id == "PATCH-DEPS-003"
        assert self.rule.band == 1


# ===========================================================================
# Registration
# ===========================================================================


class TestRegistration:
    def test_rules_registered(self):
        import importlib

        import nfr_review.rules.patch_deps

        importlib.reload(nfr_review.rules.patch_deps)

        from nfr_review.registry import rule_registry

        assert "PATCH-DEPS-001" in rule_registry
        assert "PATCH-DEPS-002" in rule_registry
        assert "PATCH-DEPS-003" in rule_registry

    def test_rule_ids(self):
        assert DependencyDeclarationRule().id == "PATCH-DEPS-001"
        assert SharedFateIndicatorRule().id == "PATCH-DEPS-002"
        assert CrossRingDependencyRule().id == "PATCH-DEPS-003"

    def test_required_collectors(self):
        assert DependencyDeclarationRule().required_collectors == [_COL]
        assert SharedFateIndicatorRule().required_collectors == [_COL]
        assert CrossRingDependencyRule().required_collectors == [_COL]
