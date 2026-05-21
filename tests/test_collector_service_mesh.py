"""Tests for the ServiceMeshCollector — Istio VirtualService/DestinationRule and
argo-rollouts Rollout/AnalysisTemplate parsing."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.service_mesh import ServiceMeshCollector
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "service-mesh-sample-repo"
GOOD_FIXTURES = Path(__file__).parent / "fixtures" / "service-mesh-good-repo"


@pytest.fixture
def collector() -> ServiceMeshCollector:
    return ServiceMeshCollector()


def _by_kind(results: list[Evidence], kind: str) -> list[Evidence]:
    return [ev for ev in results if ev.kind == kind]


def _payload(results: list[Evidence], kind: str, name: str = "") -> dict[str, Any]:
    for ev in results:
        if ev.kind == kind and (not name or ev.payload.get("name") == name):
            return ev.payload
    pytest.fail(f"No evidence with kind={kind!r} name={name!r}")


class TestRegistration:
    def test_registered_in_collector_registry(self) -> None:
        import nfr_review.collectors.service_mesh

        importlib.reload(nfr_review.collectors.service_mesh)
        assert "service-mesh" in collector_registry

    def test_collector_name(self, collector: ServiceMeshCollector) -> None:
        assert collector.name == "service-mesh"

    def test_collector_version(self, collector: ServiceMeshCollector) -> None:
        assert collector.version == "0.1.0"


class TestVirtualService:
    def test_vs_evidence_emitted(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        vs = _by_kind(results, "service-mesh-virtual-service")
        assert len(vs) == 1

    def test_vs_name_and_namespace(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-virtual-service")
        assert p["name"] == "reviews-route"
        assert p["namespace"] == "default"

    def test_vs_hosts(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-virtual-service")
        assert p["hosts"] == ["reviews"]

    def test_vs_weighted_routing_detected(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-virtual-service")
        assert p["has_weighted_routing"] is True

    def test_vs_route_destinations(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-virtual-service")
        dests = p["http_routes"][0]["destinations"]
        assert len(dests) == 2
        assert dests[0]["host"] == "reviews"
        assert dests[0]["subset"] == "v1"
        assert dests[0]["weight"] == 80
        assert dests[1]["weight"] == 20

    def test_vs_total_routes(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-virtual-service")
        assert p["total_routes"] == 1

    def test_good_vs_has_timeout_and_retries(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "service-mesh-virtual-service")
        route = p["http_routes"][0]
        assert route["timeout"] == "5s"
        assert route["retries"]["attempts"] == 3
        assert route["retries"]["per_try_timeout"] == "2s"
        assert route["retries"]["retry_on"] == "5xx,reset,connect-failure"


class TestDestinationRule:
    def test_dr_evidence_emitted(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        dr = _by_kind(results, "service-mesh-destination-rule")
        assert len(dr) == 1

    def test_dr_no_traffic_policy(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-destination-rule")
        assert p["has_connection_pool"] is False
        assert p["has_outlier_detection"] is False
        assert p["connection_pool"] is None
        assert p["outlier_detection"] is None

    def test_dr_subsets(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-destination-rule")
        assert len(p["subsets"]) == 2
        assert p["subsets"][0]["name"] == "v1"

    def test_good_dr_has_connection_pool(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "service-mesh-destination-rule")
        assert p["has_connection_pool"] is True
        assert p["connection_pool"]["tcp"]["maxConnections"] == 100

    def test_good_dr_has_outlier_detection(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "service-mesh-destination-rule")
        assert p["has_outlier_detection"] is True
        assert p["outlier_detection"]["consecutive5xxErrors"] == 5

    def test_good_dr_tls_mode(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "service-mesh-destination-rule")
        assert p["tls_mode"] == "ISTIO_MUTUAL"


class TestRollout:
    def test_rollout_evidence_emitted(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        ro = _by_kind(results, "service-mesh-rollout")
        assert len(ro) == 1

    def test_rollout_canary_strategy(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-rollout")
        assert p["strategy_type"] == "canary"

    def test_rollout_canary_steps(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-rollout")
        steps = p["canary_steps"]
        assert len(steps) == 6
        assert steps[0] == {"setWeight": 20}
        assert steps[1] == {"pause": {"duration": "60s"}}

    def test_rollout_max_surge(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-rollout")
        assert p["canary_max_surge"] == "25%"
        assert p["canary_max_unavailable"] == "0"

    def test_rollout_no_analysis(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-rollout")
        assert p["has_analysis"] is False
        assert p["analysis_refs"] == []

    def test_good_rollout_has_analysis_refs(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "service-mesh-rollout")
        assert p["has_analysis"] is True
        assert "success-rate" in p["analysis_refs"]
        assert "latency-check" in p["analysis_refs"]
        assert "error-rate" in p["analysis_refs"]

    def test_good_rollout_anti_affinity(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "service-mesh-rollout")
        assert p["anti_affinity"] is not None

    def test_good_rollout_replicas(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "service-mesh-rollout")
        assert p["replicas"] == 5


class TestAnalysisTemplate:
    def test_at_evidence_emitted(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        at = _by_kind(results, "service-mesh-analysis-template")
        assert len(at) == 1

    def test_at_metrics(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-analysis-template")
        assert p["has_metrics"] is True
        assert len(p["metrics"]) == 1
        m = p["metrics"][0]
        assert m["name"] == "success-rate"
        assert m["interval"] == "30s"
        assert m["count"] == 5
        assert m["success_condition"] == "result[0] >= 0.95"

    def test_at_args(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-analysis-template")
        assert len(p["args"]) == 1
        assert p["args"][0]["name"] == "service-name"
        assert p["args"][0]["value"] == "reviews"

    def test_good_at_multiple_metrics(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "service-mesh-analysis-template")
        assert len(p["metrics"]) == 2
        names = {m["name"] for m in p["metrics"]}
        assert names == {"success-rate", "latency-p99"}

    def test_good_at_failure_condition(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "service-mesh-analysis-template")
        sr_metric = next(m for m in p["metrics"] if m["name"] == "success-rate")
        assert sr_metric["failure_condition"] == "result[0] < 0.80"


class TestSummary:
    def test_summary_always_emitted(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        summaries = _by_kind(results, "service-mesh-summary")
        assert len(summaries) == 1

    def test_sample_repo_counts(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "service-mesh-summary")
        assert p["virtual_services"] == 1
        assert p["destination_rules"] == 1
        assert p["rollouts"] == 1
        assert p["analysis_templates"] == 1
        assert p["files_parsed"] == 4

    def test_empty_dir_summary(self, collector: ServiceMeshCollector, tmp_path: Path) -> None:
        results = collector.collect(tmp_path, config=None)
        summaries = _by_kind(results, "service-mesh-summary")
        assert len(summaries) == 1
        p = summaries[0].payload
        assert p["virtual_services"] == 0
        assert p["files_parsed"] == 0


class TestEdgeCases:
    def test_empty_directory(self, collector: ServiceMeshCollector, tmp_path: Path) -> None:
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].kind == "service-mesh-summary"

    def test_non_mesh_yaml_ignored(
        self, collector: ServiceMeshCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "service.yaml").write_text(
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: svc\n"
            "spec:\n"
            "  ports:\n"
            "    - port: 80\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].kind == "service-mesh-summary"

    def test_malformed_yaml_logged(
        self,
        collector: ServiceMeshCollector,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        (tmp_path / "bad.yaml").write_text("{{invalid yaml: [unclosed\n")
        (tmp_path / "good.yaml").write_text(
            "apiVersion: networking.istio.io/v1alpha3\n"
            "kind: VirtualService\n"
            "metadata:\n"
            "  name: test-vs\n"
            "spec:\n"
            "  hosts:\n"
            "    - test\n"
            "  http:\n"
            "    - route:\n"
            "        - destination:\n"
            "            host: test\n"
        )
        with caplog.at_level(logging.DEBUG, logger="nfr_review.collectors.service_mesh"):
            results = collector.collect(tmp_path, config=None)
        vs = _by_kind(results, "service-mesh-virtual-service")
        assert len(vs) == 1
        assert "YAML parse error" in caplog.text

    def test_hidden_dirs_excluded(
        self, collector: ServiceMeshCollector, tmp_path: Path
    ) -> None:
        hidden = tmp_path / ".git" / "mesh"
        hidden.mkdir(parents=True)
        (hidden / "vs.yaml").write_text(
            "apiVersion: networking.istio.io/v1alpha3\n"
            "kind: VirtualService\n"
            "metadata:\n"
            "  name: hidden\n"
            "spec:\n"
            "  hosts:\n"
            "    - hidden\n"
        )
        results = collector.collect(tmp_path, config=None)
        vs = _by_kind(results, "service-mesh-virtual-service")
        assert len(vs) == 0

    def test_multi_doc_yaml(self, collector: ServiceMeshCollector, tmp_path: Path) -> None:
        (tmp_path / "multi.yaml").write_text(
            "apiVersion: networking.istio.io/v1alpha3\n"
            "kind: VirtualService\n"
            "metadata:\n"
            "  name: vs-multi\n"
            "spec:\n"
            "  hosts:\n"
            "    - multi\n"
            "  http:\n"
            "    - route:\n"
            "        - destination:\n"
            "            host: multi\n"
            "---\n"
            "apiVersion: networking.istio.io/v1alpha3\n"
            "kind: DestinationRule\n"
            "metadata:\n"
            "  name: dr-multi\n"
            "spec:\n"
            "  host: multi\n"
        )
        results = collector.collect(tmp_path, config=None)
        vs = _by_kind(results, "service-mesh-virtual-service")
        dr = _by_kind(results, "service-mesh-destination-rule")
        assert len(vs) == 1
        assert len(dr) == 1

    def test_null_document_handled(
        self, collector: ServiceMeshCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "with-null.yaml").write_text(
            "---\n"
            "---\n"
            "apiVersion: argoproj.io/v1alpha1\n"
            "kind: Rollout\n"
            "metadata:\n"
            "  name: after-null\n"
            "spec:\n"
            "  replicas: 1\n"
            "  strategy:\n"
            "    canary:\n"
            "      steps:\n"
            "        - setWeight: 50\n"
        )
        results = collector.collect(tmp_path, config=None)
        ro = _by_kind(results, "service-mesh-rollout")
        assert len(ro) == 1
        assert ro[0].payload["name"] == "after-null"

    def test_blue_green_strategy(
        self, collector: ServiceMeshCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "bg-rollout.yaml").write_text(
            "apiVersion: argoproj.io/v1alpha1\n"
            "kind: Rollout\n"
            "metadata:\n"
            "  name: bg-rollout\n"
            "spec:\n"
            "  replicas: 2\n"
            "  strategy:\n"
            "    blueGreen:\n"
            "      activeService: active-svc\n"
            "      previewService: preview-svc\n"
            "      analysis:\n"
            "        templates:\n"
            "          - templateName: smoke-test\n"
        )
        results = collector.collect(tmp_path, config=None)
        p = _payload(results, "service-mesh-rollout")
        assert p["strategy_type"] == "blueGreen"
        assert p["canary_steps"] is None
        assert "smoke-test" in p["analysis_refs"]

    def test_locator_is_relative(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            if ev.kind != "service-mesh-summary":
                assert not ev.locator.startswith("/")

    def test_collector_metadata(self, collector: ServiceMeshCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert ev.collector_name == "service-mesh"
            assert ev.collector_version == "0.1.0"

    def test_unreadable_file_skipped(
        self,
        collector: ServiceMeshCollector,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        f = tmp_path / "secret.yaml"
        f.write_text(
            "apiVersion: argoproj.io/v1alpha1\n"
            "kind: Rollout\n"
            "metadata:\n"
            "  name: secret\n"
            "spec:\n"
            "  replicas: 1\n"
        )
        f.chmod(0o000)
        try:
            with caplog.at_level(logging.DEBUG, logger="nfr_review.collectors.service_mesh"):
                results = collector.collect(tmp_path, config=None)
            ro = _by_kind(results, "service-mesh-rollout")
            assert len(ro) == 0
            assert "Cannot read" in caplog.text
        finally:
            f.chmod(0o644)

    def test_vs_no_weighted_routing(
        self, collector: ServiceMeshCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "vs-no-weight.yaml").write_text(
            "apiVersion: networking.istio.io/v1\n"
            "kind: VirtualService\n"
            "metadata:\n"
            "  name: simple-vs\n"
            "spec:\n"
            "  hosts:\n"
            "    - simple\n"
            "  http:\n"
            "    - route:\n"
            "        - destination:\n"
            "            host: simple\n"
        )
        results = collector.collect(tmp_path, config=None)
        p = _payload(results, "service-mesh-virtual-service")
        assert p["has_weighted_routing"] is False
