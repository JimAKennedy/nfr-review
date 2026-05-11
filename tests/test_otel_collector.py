"""Tests for the OTelCollector — OTel Collector config parsing, detection, and edge cases."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.otel import OTelCollector
from nfr_review.detect import detect_technologies
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "otel-sample-repo"
GOOD_FIXTURES = Path(__file__).parent / "fixtures" / "otel-good-repo"


@pytest.fixture
def collector() -> OTelCollector:
    return OTelCollector()


def _payload(results: list[Evidence], locator_contains: str = "") -> dict[str, Any]:
    if locator_contains:
        for r in results:
            if locator_contains in r.locator:
                return r.payload
        pytest.fail(f"No evidence with locator containing {locator_contains!r}")
    assert len(results) >= 1
    return results[0].payload


class TestRegistration:
    def test_otel_registered_in_collector_registry(self) -> None:
        import nfr_review.collectors.otel

        importlib.reload(nfr_review.collectors.otel)
        assert "otel" in collector_registry

    def test_collector_name(self, collector: OTelCollector) -> None:
        assert collector.name == "otel"

    def test_collector_version(self, collector: OTelCollector) -> None:
        assert collector.version == "0.1.0"


class TestCollectSampleRepo:
    def test_returns_evidence_list(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert isinstance(results, list)
        assert len(results) == 1

    def test_evidence_kind(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert results[0].kind == "otel-analysis"

    def test_collector_metadata(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        ev = results[0]
        assert ev.collector_name == "otel"
        assert ev.collector_version == "0.1.0"

    def test_locator_is_relative(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert not ev.locator.startswith("/")

    def test_payload_has_file_path(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert "file_path" in results[0].payload
        assert isinstance(results[0].payload["file_path"], str)

    def test_receivers_extracted(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        assert "receivers" in payload
        assert "otlp" in payload["receivers"]

    def test_processors_extracted(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        assert "processors" in payload
        assert "batch" in payload["processors"]

    def test_exporters_extracted(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        assert "exporters" in payload
        assert "logging" in payload["exporters"]

    def test_pipelines_extracted(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        assert "pipelines" in payload
        assert "traces" in payload["pipelines"]

    def test_pipeline_has_components(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        traces = _payload(results)["pipelines"]["traces"]
        assert traces["receivers"] == ["otlp"]
        assert traces["exporters"] == ["logging"]


class TestCollectGoodRepo:
    def test_returns_evidence(self, collector: OTelCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        assert len(results) == 1

    def test_multiple_receivers(self, collector: OTelCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results)
        assert "otlp" in payload["receivers"]
        assert "prometheus" in payload["receivers"]

    def test_multiple_processors(self, collector: OTelCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results)
        assert "batch" in payload["processors"]
        assert "memory_limiter" in payload["processors"]
        assert "probabilistic_sampler" in payload["processors"]

    def test_multiple_exporters(self, collector: OTelCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results)
        assert "otlp" in payload["exporters"]
        assert "prometheusremotewrite" in payload["exporters"]

    def test_all_three_signal_pipelines(self, collector: OTelCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        pipelines = _payload(results)["pipelines"]
        assert "traces" in pipelines
        assert "metrics" in pipelines
        assert "logs" in pipelines


class TestEdgeCases:
    def test_empty_directory_returns_empty(
        self, collector: OTelCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_non_otel_yaml_skipped(self, collector: OTelCollector, tmp_path: Path) -> None:
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
        self, collector: OTelCollector, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "otel-collector-config.yaml").write_text("{{invalid yaml: [unclosed\n")
        with caplog.at_level(logging.DEBUG, logger="nfr_review.collectors.otel"):
            results = collector.collect(tmp_path, config=None)
        assert results == []
        assert "YAML parse error" in caplog.text

    def test_hidden_dirs_excluded(self, collector: OTelCollector, tmp_path: Path) -> None:
        hidden = tmp_path / ".git" / "otel"
        hidden.mkdir(parents=True)
        (hidden / "otel-collector-config.yaml").write_text(
            "receivers:\n  otlp:\n    protocols:\n      grpc:\nexporters:\n"
            "  logging: {}\nservice:\n  pipelines:\n    traces:\n"
            "      receivers: [otlp]\n      exporters: [logging]\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_yaml_with_only_receivers_skipped(
        self, collector: OTelCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "partial.yaml").write_text(
            "receivers:\n  otlp:\n    protocols:\n      grpc:\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_non_yaml_files_ignored(self, collector: OTelCollector, tmp_path: Path) -> None:
        (tmp_path / "otel-collector-config.json").write_text("{}")
        (tmp_path / "readme.md").write_text("# OTel configs\n")
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_otel_named_file_with_matching_structure(
        self, collector: OTelCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "otelcol-config.yaml").write_text(
            "receivers:\n  otlp:\n    protocols:\n      grpc:\n"
            "exporters:\n  logging: {}\n"
            "service:\n  pipelines:\n    traces:\n"
            "      receivers: [otlp]\n      exporters: [logging]\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1

    def test_generic_yaml_with_pipelines_detected(
        self, collector: OTelCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "collector-config.yaml").write_text(
            "receivers:\n  otlp:\n    protocols:\n      grpc:\n"
            "exporters:\n  otlp:\n    endpoint: tempo:4317\n"
            "service:\n  pipelines:\n    traces:\n"
            "      receivers: [otlp]\n      exporters: [otlp]\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1

    def test_generic_yaml_without_pipelines_skipped(
        self, collector: OTelCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "random-config.yaml").write_text(
            "receivers:\n  something: {}\n"
            "exporters:\n  other: {}\n"
            "service:\n  telemetry:\n    logs:\n      level: debug\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_unreadable_file_skipped(
        self, collector: OTelCollector, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        f = tmp_path / "otel-collector-config.yaml"
        f.write_text(
            "receivers:\n  otlp: {}\nexporters:\n  logging: {}\n"
            "service:\n  pipelines:\n    traces:\n"
            "      receivers: [otlp]\n      exporters: [logging]\n"
        )
        f.chmod(0o000)
        try:
            with caplog.at_level(logging.DEBUG, logger="nfr_review.collectors.otel"):
                results = collector.collect(tmp_path, config=None)
            assert results == []
            assert "Cannot read" in caplog.text
        finally:
            f.chmod(0o644)

    def test_empty_yaml_file_skipped(self, collector: OTelCollector, tmp_path: Path) -> None:
        (tmp_path / "otel-collector-config.yaml").write_text("")
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_payload_keys_complete(self, collector: OTelCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results)
        expected_keys = {"file_path", "receivers", "processors", "exporters", "pipelines"}
        assert expected_keys == set(payload.keys())

    def test_receivers_sorted(self, collector: OTelCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results)
        assert payload["receivers"] == sorted(payload["receivers"])

    def test_processors_sorted(self, collector: OTelCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results)
        assert payload["processors"] == sorted(payload["processors"])


class TestDetectionEnhancement:
    def test_detect_otel_by_collector_config_file(self, tmp_path: Path) -> None:
        (tmp_path / "otel-collector-config.yaml").write_text(
            "receivers:\n  otlp: {}\nexporters:\n  logging: {}\nservice:\n  pipelines: {}\n"
        )
        assert detect_technologies(tmp_path)["otel"] is True

    def test_detect_otel_by_otelcol_filename(self, tmp_path: Path) -> None:
        (tmp_path / "otelcol.yaml").write_text(
            "receivers:\n  otlp: {}\nexporters:\n  logging: {}\n"
        )
        assert detect_technologies(tmp_path)["otel"] is True

    def test_detect_otel_no_dep_no_config(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["otel"] is False

    def test_detect_otel_nested_config(self, tmp_path: Path) -> None:
        nested = tmp_path / "deploy" / "otel"
        nested.mkdir(parents=True)
        (nested / "otel-collector-config.yml").write_text("receivers:\n  otlp: {}\n")
        assert detect_technologies(tmp_path)["otel"] is True
