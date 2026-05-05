from __future__ import annotations

import logging
from pathlib import Path

import pytest

from nfr_review.collectors.k8s_manifest import K8sManifestCollector

FIXTURES = Path(__file__).parent / "fixtures" / "java-sample-repo"


@pytest.fixture()
def collector() -> K8sManifestCollector:
    return K8sManifestCollector()


class TestK8sFixtures:
    def test_parses_fixture_dir(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        resource_ev = [e for e in evidence if e.kind == "k8s-resource"]
        summary_ev = [e for e in evidence if e.kind == "k8s-manifest-summary"]
        assert len(resource_ev) == 2
        assert len(summary_ev) == 1

    def test_good_deployment_has_probes_and_limits(
        self, collector: K8sManifestCollector
    ) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        good = next(
            e for e in evidence if e.kind == "k8s-resource" and e.payload["name"] == "good-app"
        )
        container = good.payload["containers"][0]
        assert container["liveness_probe"] is not None
        assert container["readiness_probe"] is not None
        assert container["resources"] is not None
        assert container["security_context"] is not None
        assert container["security_context"]["runAsNonRoot"] is True

    def test_bare_deployment_missing_probes_and_limits(
        self, collector: K8sManifestCollector
    ) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        bare = next(
            e for e in evidence if e.kind == "k8s-resource" and e.payload["name"] == "bare-app"
        )
        container = bare.payload["containers"][0]
        assert container["liveness_probe"] is None
        assert container["readiness_probe"] is None
        assert container["resources"] is None
        assert container["security_context"] is None

    def test_summary_has_network_policy(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        summary = next(e for e in evidence if e.kind == "k8s-manifest-summary")
        assert summary.payload["has_network_policy"] is True
        counts = summary.payload["resource_counts"]
        assert counts["Deployment"] == 2
        assert counts["NetworkPolicy"] == 1

    def test_evidence_fields(self, collector: K8sManifestCollector) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        good = next(
            e for e in evidence if e.kind == "k8s-resource" and e.payload["name"] == "good-app"
        )
        assert good.collector_name == "k8s-manifest"
        assert good.collector_version == "0.1.0"
        assert good.payload["namespace"] == "production"
        assert good.payload["kind"] == "Deployment"


class TestNonK8sYaml:
    def test_non_k8s_yaml_silently_skipped(
        self, collector: K8sManifestCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "docker-compose.yaml").write_text("services:\n  web:\n    image: nginx\n")
        evidence = collector.collect(tmp_path, config=None)
        assert len(evidence) == 1  # only the summary
        summary = evidence[0]
        assert summary.kind == "k8s-manifest-summary"
        assert summary.payload["resource_counts"] == {}

    def test_configmap_only_no_workload_evidence(
        self, collector: K8sManifestCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "configmap.yaml").write_text(
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cfg\ndata:\n  key: val\n"
        )
        evidence = collector.collect(tmp_path, config=None)
        resource_ev = [e for e in evidence if e.kind == "k8s-resource"]
        summary = next(e for e in evidence if e.kind == "k8s-manifest-summary")
        assert len(resource_ev) == 0
        assert summary.payload["resource_counts"] == {"ConfigMap": 1}
        assert summary.payload["files_parsed"] == 1


class TestMalformedYaml:
    def test_malformed_yaml_logged_and_skipped(
        self,
        collector: K8sManifestCollector,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        (tmp_path / "bad.yaml").write_text(":\n  - :\n  bad: [unterminated")
        (tmp_path / "good.yaml").write_text(
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: ok\ndata: {}\n"
        )
        with caplog.at_level(logging.WARNING):
            evidence = collector.collect(tmp_path, config=None)
        assert any("YAML parse error" in r.message for r in caplog.records)
        summary = next(e for e in evidence if e.kind == "k8s-manifest-summary")
        assert summary.payload["files_failed"] == 1
        assert summary.payload["files_parsed"] == 1


class TestEmptyDirectory:
    def test_empty_dir_returns_summary_only(
        self, collector: K8sManifestCollector, tmp_path: Path
    ) -> None:
        evidence = collector.collect(tmp_path, config=None)
        assert len(evidence) == 1
        summary = evidence[0]
        assert summary.kind == "k8s-manifest-summary"
        assert summary.payload["files_parsed"] == 0
        assert summary.payload["files_failed"] == 0
        assert summary.payload["resource_counts"] == {}


class TestMultiDocumentYaml:
    def test_multi_document_yaml(
        self, collector: K8sManifestCollector, tmp_path: Path
    ) -> None:
        content = (
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cfg1\ndata: {}\n"
            "---\n"
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: multi-app\n"
            "spec:\n  selector:\n    matchLabels:\n      app: m\n"
            "  template:\n    metadata:\n      labels:\n        app: m\n"
            "    spec:\n      containers:\n        - name: c\n          image: img\n"
        )
        (tmp_path / "multi.yaml").write_text(content)
        evidence = collector.collect(tmp_path, config=None)
        resource_ev = [e for e in evidence if e.kind == "k8s-resource"]
        summary = next(e for e in evidence if e.kind == "k8s-manifest-summary")
        assert len(resource_ev) == 1
        assert resource_ev[0].payload["name"] == "multi-app"
        assert summary.payload["resource_counts"] == {"ConfigMap": 1, "Deployment": 1}


class TestRegistration:
    def test_collector_registered(self) -> None:
        from nfr_review.registry import collector_registry

        assert "k8s-manifest" in collector_registry
        c = collector_registry.get("k8s-manifest")
        assert c.name == "k8s-manifest"
