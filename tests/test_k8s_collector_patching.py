"""Tests for K8s collector patching-readiness fields.

Covers:
- replicas, strategy, anti_affinity, termination_grace_period extracted at workload level
- startup_probe and pre_stop extracted per container
- PodDisruptionBudget emits k8s-pdb evidence
- Both file-based fixtures (k8s-patch-ready, k8s-patch-unready) and inline YAML
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from nfr_review.collectors.k8s_manifest import K8sManifestCollector

PATCH_READY_FIXTURES = Path(__file__).parent / "fixtures" / "k8s-patch-ready"
PATCH_UNREADY_FIXTURES = Path(__file__).parent / "fixtures" / "k8s-patch-unready"


@pytest.fixture()
def collector() -> K8sManifestCollector:
    return K8sManifestCollector()


# ---------------------------------------------------------------------------
# Inline YAML helpers — these tests are self-contained and do not depend on
# the fixture files created by T03.
# ---------------------------------------------------------------------------

_PATCH_READY_DEPLOYMENT = dedent("""\
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: patch-ready-app
      namespace: production
    spec:
      replicas: 3
      selector:
        matchLabels:
          app: patch-ready-app
      strategy:
        type: RollingUpdate
        rollingUpdate:
          maxSurge: 1
          maxUnavailable: 0
      template:
        metadata:
          labels:
            app: patch-ready-app
        spec:
          terminationGracePeriodSeconds: 60
          affinity:
            podAntiAffinity:
              preferredDuringSchedulingIgnoredDuringExecution:
                - weight: 100
                  podAffinityTerm:
                    labelSelector:
                      matchLabels:
                        app: patch-ready-app
                    topologyKey: kubernetes.io/hostname
          containers:
            - name: app
              image: myregistry.example.com/patch-ready-app:1.2.3
              resources:
                requests:
                  cpu: 100m
                  memory: 128Mi
                limits:
                  cpu: 500m
                  memory: 512Mi
              startupProbe:
                httpGet:
                  path: /healthz/startup
                  port: 8080
                initialDelaySeconds: 5
                periodSeconds: 5
                failureThreshold: 12
              livenessProbe:
                httpGet:
                  path: /healthz/live
                  port: 8080
              readinessProbe:
                httpGet:
                  path: /healthz/ready
                  port: 8080
              lifecycle:
                preStop:
                  exec:
                    command:
                      - /bin/sh
                      - -c
                      - sleep 10
              securityContext:
                runAsNonRoot: true
                allowPrivilegeEscalation: false
""")

_PATCH_READY_PDB = dedent("""\
    apiVersion: policy/v1
    kind: PodDisruptionBudget
    metadata:
      name: patch-ready-app-pdb
      namespace: production
    spec:
      minAvailable: 2
      selector:
        matchLabels:
          app: patch-ready-app
""")

_PATCH_UNREADY_DEPLOYMENT = dedent("""\
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: patch-unready-app
      namespace: production
    spec:
      replicas: 1
      selector:
        matchLabels:
          app: patch-unready-app
      template:
        metadata:
          labels:
            app: patch-unready-app
        spec:
          containers:
            - name: app
              image: myregistry.example.com/patch-unready-app:0.9.0
              resources:
                requests:
                  cpu: 100m
                  memory: 128Mi
                limits:
                  cpu: 500m
                  memory: 512Mi
              livenessProbe:
                httpGet:
                  path: /healthz
                  port: 8080
              readinessProbe:
                httpGet:
                  path: /ready
                  port: 8080
""")


@pytest.fixture()
def patch_ready_dir(tmp_path: Path) -> Path:
    """Inline patch-ready fixture: Deployment + PDB."""
    (tmp_path / "deployment.yaml").write_text(_PATCH_READY_DEPLOYMENT)
    (tmp_path / "pdb.yaml").write_text(_PATCH_READY_PDB)
    return tmp_path


@pytest.fixture()
def patch_unready_dir(tmp_path: Path) -> Path:
    """Inline patch-unready fixture: singleton Deployment, no extras."""
    (tmp_path / "deployment.yaml").write_text(_PATCH_UNREADY_DEPLOYMENT)
    return tmp_path


# ---------------------------------------------------------------------------
# Patch-ready inline tests
# ---------------------------------------------------------------------------


class TestPatchReadyInline:
    def test_replicas_greater_than_one(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_ready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        assert resource.payload["replicas"] is not None
        assert resource.payload["replicas"] > 1

    def test_strategy_is_rolling_update(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_ready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        strategy = resource.payload["strategy"]
        assert strategy is not None
        assert strategy.get("type") == "RollingUpdate"

    def test_anti_affinity_present(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_ready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        assert resource.payload["anti_affinity"] is not None

    def test_termination_grace_period_gte_30(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_ready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        tgp = resource.payload["termination_grace_period"]
        assert tgp is not None
        assert tgp >= 30

    def test_startup_probe_present(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_ready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        container = resource.payload["containers"][0]
        assert container["startup_probe"] is not None

    def test_pre_stop_present(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_ready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        container = resource.payload["containers"][0]
        assert container["pre_stop"] is not None

    def test_pdb_evidence_emitted(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_ready_dir, config=None)
        pdb_ev = [e for e in evidence if e.kind == "k8s-pdb"]
        assert len(pdb_ev) == 1

    def test_pdb_payload_fields(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_ready_dir, config=None)
        pdb = next(e for e in evidence if e.kind == "k8s-pdb")
        assert pdb.payload["name"] == "patch-ready-app-pdb"
        assert pdb.payload["namespace"] == "production"
        assert pdb.payload["min_available"] == 2
        assert pdb.payload["max_unavailable"] is None
        assert pdb.payload["match_labels"] == {"app": "patch-ready-app"}

    def test_pdb_counted_in_summary(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_ready_dir, config=None)
        summary = next(e for e in evidence if e.kind == "k8s-manifest-summary")
        assert summary.payload["resource_counts"].get("PodDisruptionBudget") == 1

    def test_liveness_and_readiness_probes_still_present(
        self, collector: K8sManifestCollector, patch_ready_dir: Path
    ) -> None:
        """Existing probe fields are unaffected by new field additions."""
        evidence = collector.collect(patch_ready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        container = resource.payload["containers"][0]
        assert container["liveness_probe"] is not None
        assert container["readiness_probe"] is not None


# ---------------------------------------------------------------------------
# Patch-unready inline tests
# ---------------------------------------------------------------------------


class TestPatchUnreadyInline:
    def test_replicas_is_one(
        self, collector: K8sManifestCollector, patch_unready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_unready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        assert resource.payload["replicas"] == 1

    def test_no_strategy(
        self, collector: K8sManifestCollector, patch_unready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_unready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        assert resource.payload["strategy"] is None

    def test_no_anti_affinity(
        self, collector: K8sManifestCollector, patch_unready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_unready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        assert resource.payload["anti_affinity"] is None

    def test_no_startup_probe(
        self, collector: K8sManifestCollector, patch_unready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_unready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        container = resource.payload["containers"][0]
        assert container["startup_probe"] is None

    def test_no_pre_stop(
        self, collector: K8sManifestCollector, patch_unready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_unready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        container = resource.payload["containers"][0]
        assert container["pre_stop"] is None

    def test_no_pdb_evidence(
        self, collector: K8sManifestCollector, patch_unready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_unready_dir, config=None)
        pdb_ev = [e for e in evidence if e.kind == "k8s-pdb"]
        assert len(pdb_ev) == 0

    def test_termination_grace_period_none_when_not_set(
        self, collector: K8sManifestCollector, patch_unready_dir: Path
    ) -> None:
        evidence = collector.collect(patch_unready_dir, config=None)
        resource = next(e for e in evidence if e.kind == "k8s-resource")
        assert resource.payload["termination_grace_period"] is None


# ---------------------------------------------------------------------------
# File-based fixture tests (depend on T03 having created the fixture dirs)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not PATCH_READY_FIXTURES.exists(),
    reason="k8s-patch-ready fixtures not present",
)
class TestPatchReadyFixtures:
    def test_patch_ready_deployment_evidence(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(PATCH_READY_FIXTURES, config=None)
        resource = next(
            e
            for e in evidence
            if e.kind == "k8s-resource" and e.payload["name"] == "patch-ready-app"
        )
        assert resource.payload["replicas"] == 3
        assert resource.payload["strategy"] is not None
        assert resource.payload["strategy"]["type"] == "RollingUpdate"
        assert resource.payload["anti_affinity"] is not None
        assert resource.payload["termination_grace_period"] == 60

    def test_patch_ready_container_fields(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(PATCH_READY_FIXTURES, config=None)
        resource = next(
            e
            for e in evidence
            if e.kind == "k8s-resource" and e.payload["name"] == "patch-ready-app"
        )
        container = resource.payload["containers"][0]
        assert container["startup_probe"] is not None
        assert container["pre_stop"] is not None
        assert container["liveness_probe"] is not None
        assert container["readiness_probe"] is not None

    def test_patch_ready_pdb_evidence(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(PATCH_READY_FIXTURES, config=None)
        pdb_ev = [e for e in evidence if e.kind == "k8s-pdb"]
        assert len(pdb_ev) == 1
        pdb = pdb_ev[0]
        assert pdb.payload["name"] == "patch-ready-app-pdb"
        assert pdb.payload["min_available"] == 2
        assert pdb.payload["match_labels"] == {"app": "patch-ready-app"}

    def test_patch_ready_summary_counts(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(PATCH_READY_FIXTURES, config=None)
        summary = next(e for e in evidence if e.kind == "k8s-manifest-summary")
        counts = summary.payload["resource_counts"]
        assert counts.get("Deployment") == 1
        assert counts.get("PodDisruptionBudget") == 1


@pytest.mark.skipif(
    not PATCH_UNREADY_FIXTURES.exists(),
    reason="k8s-patch-unready fixtures not present",
)
class TestPatchUnreadyFixtures:
    def test_patch_unready_deployment_evidence(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(PATCH_UNREADY_FIXTURES, config=None)
        resource = next(
            e
            for e in evidence
            if e.kind == "k8s-resource" and e.payload["name"] == "patch-unready-app"
        )
        assert resource.payload["replicas"] == 1
        assert resource.payload["strategy"] is None
        assert resource.payload["anti_affinity"] is None
        assert resource.payload["termination_grace_period"] == 5

    def test_patch_unready_container_fields(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(PATCH_UNREADY_FIXTURES, config=None)
        resource = next(
            e
            for e in evidence
            if e.kind == "k8s-resource" and e.payload["name"] == "patch-unready-app"
        )
        container = resource.payload["containers"][0]
        assert container["startup_probe"] is None
        assert container["pre_stop"] is None

    def test_patch_unready_no_pdb(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(PATCH_UNREADY_FIXTURES, config=None)
        pdb_ev = [e for e in evidence if e.kind == "k8s-pdb"]
        assert len(pdb_ev) == 0
