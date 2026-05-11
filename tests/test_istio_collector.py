"""Tests for the IstioCollector — Istio CRD parsing, detection, and edge cases."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.istio import IstioCollector
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "istio-sample-repo"
GOOD_FIXTURES = Path(__file__).parent / "fixtures" / "istio-good-repo"


@pytest.fixture
def collector() -> IstioCollector:
    return IstioCollector()


def _payload(results: list[Evidence], locator_contains: str = "") -> dict[str, Any]:
    if locator_contains:
        for r in results:
            if locator_contains in r.locator:
                return r.payload
        pytest.fail(f"No evidence with locator containing {locator_contains!r}")
    assert len(results) >= 1
    return results[0].payload


def _resources(results: list[Evidence], locator_contains: str = "") -> list[dict[str, Any]]:
    return _payload(results, locator_contains)["resources"]


class TestRegistration:
    def test_istio_registered_in_collector_registry(self) -> None:
        import nfr_review.collectors.istio

        importlib.reload(nfr_review.collectors.istio)
        assert "istio" in collector_registry

    def test_collector_name(self, collector: IstioCollector) -> None:
        assert collector.name == "istio"

    def test_collector_version(self, collector: IstioCollector) -> None:
        assert collector.version == "0.1.0"


class TestCollectSampleRepo:
    def test_returns_evidence_list(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert isinstance(results, list)
        assert len(results) == 4

    def test_evidence_kind(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert ev.kind == "istio-analysis"

    def test_collector_metadata(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert ev.collector_name == "istio"
            assert ev.collector_version == "0.1.0"

    def test_locator_is_relative(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert not ev.locator.startswith("/")

    def test_payload_has_file_path(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert "file_path" in ev.payload
            assert isinstance(ev.payload["file_path"], str)

    def test_payload_has_resources_list(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert "resources" in ev.payload
            assert isinstance(ev.payload["resources"], list)
            assert len(ev.payload["resources"]) >= 1

    def test_peer_authentication_parsed(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        resources = _resources(results, "peer-authentication")
        assert len(resources) == 1
        r = resources[0]
        assert r["kind"] == "PeerAuthentication"
        assert r["name"] == "default"
        assert r["namespace"] == "istio-system"
        assert r["spec"]["mtls"]["mode"] == "PERMISSIVE"

    def test_destination_rule_parsed(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        resources = _resources(results, "destination-rule")
        assert len(resources) == 1
        r = resources[0]
        assert r["kind"] == "DestinationRule"
        assert r["name"] == "reviews"
        assert r["api_version"] == "networking.istio.io/v1alpha3"

    def test_virtual_service_parsed(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        resources = _resources(results, "virtual-service")
        assert len(resources) == 1
        r = resources[0]
        assert r["kind"] == "VirtualService"
        assert r["name"] == "reviews-route"

    def test_gateway_parsed(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        resources = _resources(results, "gateway")
        assert len(resources) == 1
        r = resources[0]
        assert r["kind"] == "Gateway"
        assert r["name"] == "bookinfo-gateway"
        assert r["api_version"] == "networking.istio.io/v1beta1"

    def test_resource_fields_present(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        resources = _resources(results, "peer-authentication")
        r = resources[0]
        expected_keys = {"kind", "api_version", "name", "namespace", "spec", "line"}
        assert expected_keys == set(r.keys())

    def test_line_is_positive_int(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            for r in ev.payload["resources"]:
                assert isinstance(r["line"], int)
                assert r["line"] >= 1


class TestCollectGoodRepo:
    def test_strict_mtls_parsed(self, collector: IstioCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        resources = _resources(results, "peer-authentication")
        assert resources[0]["spec"]["mtls"]["mode"] == "STRICT"

    def test_traffic_policy_present(self, collector: IstioCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        resources = _resources(results, "destination-rule")
        spec = resources[0]["spec"]
        assert "trafficPolicy" in spec
        assert "connectionPool" in spec["trafficPolicy"]
        assert "outlierDetection" in spec["trafficPolicy"]

    def test_virtual_service_timeout(self, collector: IstioCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        resources = _resources(results, "virtual-service")
        spec = resources[0]["spec"]
        assert spec["http"][0]["timeout"] == "5s"


class TestApiVersionTolerance:
    def test_v1alpha3_detected(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        resources = _resources(results, "destination-rule")
        assert resources[0]["api_version"] == "networking.istio.io/v1alpha3"

    def test_v1beta1_detected(self, collector: IstioCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        resources = _resources(results, "peer-authentication")
        assert resources[0]["api_version"] == "security.istio.io/v1beta1"

    def test_v1_detected(self, collector: IstioCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        resources = _resources(results, "virtual-service")
        assert resources[0]["api_version"] == "networking.istio.io/v1"


class TestMultiDocumentYaml:
    def test_multi_document_file(self, collector: IstioCollector, tmp_path: Path) -> None:
        multi_doc = tmp_path / "multi.yaml"
        multi_doc.write_text(
            "apiVersion: security.istio.io/v1beta1\n"
            "kind: PeerAuthentication\n"
            "metadata:\n"
            "  name: ns-strict\n"
            "  namespace: production\n"
            "spec:\n"
            "  mtls:\n"
            "    mode: STRICT\n"
            "---\n"
            "apiVersion: networking.istio.io/v1alpha3\n"
            "kind: DestinationRule\n"
            "metadata:\n"
            "  name: productpage\n"
            "spec:\n"
            "  host: productpage\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        resources = results[0].payload["resources"]
        assert len(resources) == 2
        assert resources[0]["kind"] == "PeerAuthentication"
        assert resources[1]["kind"] == "DestinationRule"

    def test_multi_doc_mixed_istio_and_non_istio(
        self, collector: IstioCollector, tmp_path: Path
    ) -> None:
        mixed = tmp_path / "mixed.yaml"
        mixed.write_text(
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: my-svc\n"
            "spec:\n"
            "  ports:\n"
            "    - port: 80\n"
            "---\n"
            "apiVersion: networking.istio.io/v1alpha3\n"
            "kind: VirtualService\n"
            "metadata:\n"
            "  name: my-vs\n"
            "spec:\n"
            "  hosts:\n"
            "    - my-svc\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        resources = results[0].payload["resources"]
        assert len(resources) == 1
        assert resources[0]["kind"] == "VirtualService"


class TestEdgeCases:
    def test_empty_directory_returns_empty(
        self, collector: IstioCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_non_istio_yaml_skipped(self, collector: IstioCollector, tmp_path: Path) -> None:
        (tmp_path / "service.yaml").write_text(
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: my-service\n"
            "spec:\n"
            "  ports:\n"
            "    - port: 80\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_malformed_yaml_logged_not_crashed(
        self, collector: IstioCollector, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "bad.yaml").write_text("{{invalid yaml: [unclosed\n")
        (tmp_path / "good.yaml").write_text(
            "apiVersion: security.istio.io/v1beta1\n"
            "kind: PeerAuthentication\n"
            "metadata:\n"
            "  name: test\n"
            "spec:\n"
            "  mtls:\n"
            "    mode: STRICT\n"
        )
        with caplog.at_level(logging.DEBUG, logger="nfr_review.collectors.istio"):
            results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].payload["resources"][0]["name"] == "test"
        assert "YAML parse error" in caplog.text

    def test_yaml_without_apiversion_skipped(
        self, collector: IstioCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "noapi.yaml").write_text("kind: Something\nmetadata:\n  name: test\n")
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_yaml_without_kind_skipped(
        self, collector: IstioCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "nokind.yaml").write_text(
            "apiVersion: networking.istio.io/v1alpha3\nmetadata:\n  name: test\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_hidden_dirs_excluded(self, collector: IstioCollector, tmp_path: Path) -> None:
        hidden = tmp_path / ".git" / "istio"
        hidden.mkdir(parents=True)
        (hidden / "peer-auth.yaml").write_text(
            "apiVersion: security.istio.io/v1beta1\n"
            "kind: PeerAuthentication\n"
            "metadata:\n"
            "  name: hidden\n"
            "spec:\n"
            "  mtls:\n"
            "    mode: STRICT\n"
        )
        visible = tmp_path / "mesh"
        visible.mkdir()
        (visible / "peer-auth.yaml").write_text(
            "apiVersion: security.istio.io/v1beta1\n"
            "kind: PeerAuthentication\n"
            "metadata:\n"
            "  name: visible\n"
            "spec:\n"
            "  mtls:\n"
            "    mode: STRICT\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].payload["resources"][0]["name"] == "visible"

    def test_unreadable_file_skipped(
        self, collector: IstioCollector, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        f = tmp_path / "secret.yaml"
        f.write_text(
            "apiVersion: security.istio.io/v1beta1\n"
            "kind: PeerAuthentication\n"
            "metadata:\n"
            "  name: secret\n"
            "spec:\n"
            "  mtls:\n"
            "    mode: STRICT\n"
        )
        f.chmod(0o000)
        try:
            with caplog.at_level(logging.DEBUG, logger="nfr_review.collectors.istio"):
                results = collector.collect(tmp_path, config=None)
            assert results == []
            assert "Cannot read" in caplog.text
        finally:
            f.chmod(0o644)

    def test_non_yaml_files_ignored(self, collector: IstioCollector, tmp_path: Path) -> None:
        (tmp_path / "readme.md").write_text("# Istio configs\n")
        (tmp_path / "config.json").write_text("{}")
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_null_document_in_multi_doc(
        self, collector: IstioCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "with-null.yaml").write_text(
            "---\n"
            "---\n"
            "apiVersion: networking.istio.io/v1alpha3\n"
            "kind: VirtualService\n"
            "metadata:\n"
            "  name: after-null\n"
            "spec:\n"
            "  hosts:\n"
            "    - example\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].payload["resources"][0]["name"] == "after-null"

    def test_namespace_none_when_missing(
        self, collector: IstioCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "no-ns.yaml").write_text(
            "apiVersion: networking.istio.io/v1alpha3\n"
            "kind: DestinationRule\n"
            "metadata:\n"
            "  name: no-namespace\n"
            "spec:\n"
            "  host: example\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert results[0].payload["resources"][0]["namespace"] is None
