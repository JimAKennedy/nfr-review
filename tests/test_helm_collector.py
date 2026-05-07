"""Tests for the HelmCollector — subprocess rendering, graceful degradation, and edge cases."""

from __future__ import annotations

import importlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.helm import HelmCollector
from nfr_review.detect import ALL_TECH_KEYS
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "helm-sample-repo"
GOOD_FIXTURES = Path(__file__).parent / "fixtures" / "helm-good-chart"

_HELM_AVAILABLE = shutil.which("helm") is not None


@pytest.fixture
def collector() -> HelmCollector:
    return HelmCollector()


def _payload(results: list[Evidence]) -> dict[str, Any]:
    assert len(results) >= 1
    return results[0].payload


class TestRegistration:
    def test_helm_registered_in_collector_registry(self) -> None:
        import nfr_review.collectors.helm

        importlib.reload(nfr_review.collectors.helm)
        assert "helm" in collector_registry


class TestDetection:
    def test_helm_in_all_tech_keys(self) -> None:
        assert "helm" in ALL_TECH_KEYS

    def test_all_tech_keys_count(self) -> None:
        assert len(ALL_TECH_KEYS) == 17


class TestCollectWithoutHelm:
    """Tests that work regardless of helm availability by parsing static files."""

    def test_finds_chart_in_fixture(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert len(results) == 1

    def test_evidence_kind(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert results[0].kind == "helm-analysis"

    def test_collector_metadata(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        ev = results[0]
        assert ev.collector_name == "helm"
        assert ev.collector_version == "0.1.0"

    def test_chart_metadata_parsed(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        assert payload["chart_name"] == "sample-app"
        assert payload["chart_version"] == "0.1.0"
        assert payload["app_version"] == "1.0.0"
        assert "sample Helm chart" in payload["description"]

    def test_values_parsed(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        assert isinstance(payload["values"], dict)
        assert payload["values"]["replicaCount"] == 1
        assert payload["values"]["database"]["password"] == "supersecretpassword123"

    def test_template_files_listed(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        tpl_files = payload["template_files"]
        assert any("deployment.yaml" in f for f in tpl_files)
        assert any("service.yaml" in f for f in tpl_files)
        assert any("secret.yaml" in f for f in tpl_files)
        assert any("_helpers.tpl" in f for f in tpl_files)

    def test_locator_is_relative(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert not results[0].locator.startswith("/")

    def test_good_chart_parsed(self, collector: HelmCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results)
        assert payload["chart_name"] == "good-app"
        assert payload["chart_version"] == "1.2.3"
        assert payload["values"]["resources"]["limits"]["cpu"] == "500m"


@pytest.mark.skipif(not _HELM_AVAILABLE, reason="helm binary not on PATH")
class TestCollectWithHelm:
    def test_rendered_manifests_present(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        assert payload["helm_available"] is True
        assert len(payload["rendered_manifests"]) > 0

    def test_rendered_manifests_contain_deployment(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        kinds = [m.get("kind") for m in payload["rendered_manifests"]]
        assert "Deployment" in kinds

    def test_rendered_manifests_contain_service(self, collector: HelmCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        kinds = [m.get("kind") for m in payload["rendered_manifests"]]
        assert "Service" in kinds


class TestGracefulDegradation:
    def test_no_helm_returns_evidence_with_empty_manifests(
        self, collector: HelmCollector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("nfr_review.collectors.helm.shutil.which", lambda _: None)
        results = collector.collect(FIXTURES, config=None)
        assert len(results) == 1
        payload = _payload(results)
        assert payload["helm_available"] is False
        assert payload["rendered_manifests"] == []
        assert payload["chart_name"] == "sample-app"
        assert isinstance(payload["values"], dict)

    def test_no_crash_when_helm_missing(
        self, collector: HelmCollector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("nfr_review.collectors.helm.shutil.which", lambda _: None)
        results = collector.collect(FIXTURES, config=None)
        assert isinstance(results, list)


class TestHelmTemplateFailure:
    def test_called_process_error_returns_empty_manifests(
        self, collector: HelmCollector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nfr_review.collectors.helm.shutil.which", lambda _: "/usr/bin/helm"
        )

        def _mock_run(*args: Any, **kwargs: Any) -> None:
            raise subprocess.CalledProcessError(1, "helm template", stderr="error")

        monkeypatch.setattr("nfr_review.collectors.helm.subprocess.run", _mock_run)
        results = collector.collect(FIXTURES, config=None)
        assert len(results) == 1
        assert _payload(results)["rendered_manifests"] == []

    def test_timeout_returns_empty_manifests(
        self, collector: HelmCollector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nfr_review.collectors.helm.shutil.which", lambda _: "/usr/bin/helm"
        )

        def _mock_run(*args: Any, **kwargs: Any) -> None:
            raise subprocess.TimeoutExpired("helm template", 30)

        monkeypatch.setattr("nfr_review.collectors.helm.subprocess.run", _mock_run)
        results = collector.collect(FIXTURES, config=None)
        assert len(results) == 1
        assert _payload(results)["rendered_manifests"] == []

    def test_file_not_found_returns_empty_manifests(
        self, collector: HelmCollector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nfr_review.collectors.helm.shutil.which", lambda _: "/usr/bin/helm"
        )

        def _mock_run(*args: Any, **kwargs: Any) -> None:
            raise FileNotFoundError("helm")

        monkeypatch.setattr("nfr_review.collectors.helm.subprocess.run", _mock_run)
        results = collector.collect(FIXTURES, config=None)
        assert len(results) == 1
        assert _payload(results)["rendered_manifests"] == []


class TestMalformedChart:
    def test_invalid_chart_yaml_skipped(
        self, collector: HelmCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "Chart.yaml").write_text(": invalid: yaml: [[[")
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_missing_chart_fields(self, collector: HelmCollector, tmp_path: Path) -> None:
        (tmp_path / "Chart.yaml").write_text("apiVersion: v2\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        payload = _payload(results)
        assert payload["chart_name"] is None
        assert payload["chart_version"] is None


class TestEdgeCases:
    def test_empty_repo_returns_empty(self, collector: HelmCollector, tmp_path: Path) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_chart_yaml_only_no_templates(
        self, collector: HelmCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "Chart.yaml").write_text("apiVersion: v2\nname: bare\nversion: 0.1.0\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        payload = _payload(results)
        assert payload["template_files"] == []
        assert payload["values"] == {}

    def test_no_values_yaml(self, collector: HelmCollector, tmp_path: Path) -> None:
        (tmp_path / "Chart.yaml").write_text("apiVersion: v2\nname: noval\nversion: 0.1.0\n")
        (tmp_path / "templates").mkdir()
        (tmp_path / "templates" / "svc.yaml").write_text("kind: Service\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert _payload(results)["values"] == {}

    def test_collector_name_and_version(self, collector: HelmCollector) -> None:
        assert collector.name == "helm"
        assert collector.version == "0.1.0"

    def test_hidden_chart_skipped(self, collector: HelmCollector, tmp_path: Path) -> None:
        hidden = tmp_path / ".git" / "charts"
        hidden.mkdir(parents=True)
        (hidden / "Chart.yaml").write_text("apiVersion: v2\nname: hidden\n")
        visible = tmp_path / "charts"
        visible.mkdir()
        (visible / "Chart.yaml").write_text("apiVersion: v2\nname: visible\nversion: 1.0.0\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert _payload(results)["chart_name"] == "visible"
