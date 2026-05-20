"""Tests for TelemetryConfigCollector — OTel pipeline topology, SDK instrumentation
patterns, exporter targets, resource attributes, and synthetic test configurations."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.telemetry_config import TelemetryConfigCollector
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "telemetry-sample-repo"
GOOD_FIXTURES = Path(__file__).parent / "fixtures" / "telemetry-good-repo"


@pytest.fixture
def collector() -> TelemetryConfigCollector:
    return TelemetryConfigCollector()


def _by_kind(results: list[Evidence], kind: str) -> list[Evidence]:
    return [ev for ev in results if ev.kind == kind]


def _payload(results: list[Evidence], kind: str, name: str = "") -> dict[str, Any]:
    for ev in results:
        if ev.kind == kind and (
            not name
            or ev.payload.get("name") == name
            or ev.payload.get("file_path", "").endswith(name)
        ):
            return ev.payload
    pytest.fail(f"No evidence with kind={kind!r} name={name!r}")


class TestRegistration:
    def test_registered_in_collector_registry(self) -> None:
        import nfr_review.collectors.telemetry_config

        importlib.reload(nfr_review.collectors.telemetry_config)
        assert "telemetry-config" in collector_registry

    def test_collector_name(self, collector: TelemetryConfigCollector) -> None:
        assert collector.name == "telemetry-config"

    def test_collector_version(self, collector: TelemetryConfigCollector) -> None:
        assert collector.version == "0.1.0"


class TestPipelineEvidence:
    def test_pipeline_evidence_emitted(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        pipelines = _by_kind(results, "telemetry-pipeline")
        assert len(pipelines) == 1

    def test_receivers_extracted(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        assert "otlp" in p["receivers"]
        assert "prometheus" in p["receivers"]

    def test_processors_extracted(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        assert "batch" in p["processors"]
        assert "resource" in p["processors"]

    def test_exporters_extracted(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        assert "otlp" in p["exporters"]
        assert "prometheus" in p["exporters"]

    def test_signal_types(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        assert set(p["signal_types"]) == {"metrics", "traces"}

    def test_exporter_targets(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        targets = {t["name"]: t for t in p["exporter_targets"]}
        assert targets["otlp"]["endpoint"] == "tempo.monitoring:4317"
        assert targets["prometheus"]["endpoint"] == "0.0.0.0:8889"

    def test_resource_attributes(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        assert p["resource_attributes"]["service.name"] == "my-service"
        assert p["resource_attributes"]["deployment.environment"] == "production"

    def test_extensions_extracted(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        assert "health_check" in p["extensions"]

    def test_pipeline_detail(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        assert "traces" in p["pipelines"]
        assert "otlp" in p["pipelines"]["traces"]["receivers"]


class TestGoodRepoPipeline:
    def test_all_three_signals(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        assert set(p["signal_types"]) == {"metrics", "traces", "logs"}

    def test_named_exporters(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        target_names = {t["name"] for t in p["exporter_targets"]}
        assert "otlp/traces" in target_names
        assert "otlp/logs" in target_names
        assert "prometheus" in target_names

    def test_exporter_target_endpoints(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        targets = {t["name"]: t for t in p["exporter_targets"]}
        assert targets["otlp/traces"]["endpoint"] == "tempo.monitoring:4317"
        assert targets["otlp/logs"]["endpoint"] == "loki.monitoring:4317"

    def test_resource_attrs_from_processors(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        attrs = p["resource_attributes"]
        assert attrs["service.name"] == "payment-service"
        assert attrs["team"] == "platform"

    def test_resource_attrs_from_service_telemetry(
        self, collector: TelemetryConfigCollector
    ) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        attrs = p["resource_attributes"]
        assert attrs["service.namespace"] == "payments"
        assert attrs["cloud.provider"] == "azure"

    def test_multiple_extensions(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "telemetry-pipeline")
        assert "health_check" in p["extensions"]
        assert "zpages" in p["extensions"]


class TestSDKInstrumentation:
    def test_sdk_init_detected(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        sdk = _by_kind(results, "telemetry-sdk-init")
        assert len(sdk) == 1

    def test_sdk_language(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-sdk-init")
        assert p["language"] == "python"

    def test_sdk_packages(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-sdk-init")
        assert "opentelemetry" in p["sdk_packages"] or any(
            "opentelemetry" in pkg for pkg in p["sdk_packages"]
        )

    def test_sdk_traces_signal(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-sdk-init")
        assert "traces" in p["configured_signals"]

    def test_sdk_manual_type(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-sdk-init")
        assert p["instrumentation_type"] == "manual"

    def test_good_repo_auto_instrumentation(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "telemetry-sdk-init")
        assert p["instrumentation_type"] == "auto"

    def test_good_repo_all_signals(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "telemetry-sdk-init")
        assert set(p["configured_signals"]) == {"traces", "metrics", "logs"}


class TestSyntheticConfig:
    def test_synthetic_detected(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        synth = _by_kind(results, "telemetry-synthetic-config")
        assert len(synth) == 1

    def test_datadog_tool(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-synthetic-config")
        assert p["tool"] == "datadog-synthetics"

    def test_datadog_targets(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-synthetic-config")
        assert "https://api.example.com/health" in p["targets"]

    def test_datadog_frequency(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-synthetic-config")
        assert p["frequency"] == "60"

    def test_good_repo_grafana_synthetic(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        synth = _by_kind(results, "telemetry-synthetic-config")
        assert len(synth) == 1
        p = synth[0].payload
        assert p["tool"] == "grafana-synthetic-monitoring"
        assert len(p["targets"]) == 2
        assert "https://api.payments.example.com/health" in p["targets"]


class TestSummary:
    def test_summary_always_emitted(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        summaries = _by_kind(results, "telemetry-config-summary")
        assert len(summaries) == 1

    def test_sample_repo_counts(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-config-summary")
        assert p["collector_configs_found"] == 1
        assert p["sdk_instrumentations_found"] == 1
        assert p["synthetic_configs_found"] == 1

    def test_signal_coverage(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        p = _payload(results, "telemetry-config-summary")
        assert p["signal_coverage"]["traces"] is True
        assert p["signal_coverage"]["metrics"] is True
        assert p["signal_coverage"]["logs"] is False

    def test_good_repo_full_coverage(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        p = _payload(results, "telemetry-config-summary")
        assert p["signal_coverage"]["traces"] is True
        assert p["signal_coverage"]["metrics"] is True
        assert p["signal_coverage"]["logs"] is True

    def test_empty_dir_summary(
        self, collector: TelemetryConfigCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        summaries = _by_kind(results, "telemetry-config-summary")
        assert len(summaries) == 1
        p = summaries[0].payload
        assert p["collector_configs_found"] == 0
        assert p["sdk_instrumentations_found"] == 0
        assert p["synthetic_configs_found"] == 0


class TestEdgeCases:
    def test_empty_directory(
        self, collector: TelemetryConfigCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].kind == "telemetry-config-summary"

    def test_non_otel_yaml_ignored(
        self, collector: TelemetryConfigCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "app-config.yaml").write_text(
            "database:\n  host: localhost\n  port: 5432\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].kind == "telemetry-config-summary"

    def test_malformed_yaml_logged_as_warning(
        self,
        collector: TelemetryConfigCollector,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        (tmp_path / "bad.yaml").write_text("{{invalid yaml: [unclosed\n")
        with caplog.at_level(logging.WARNING, logger="nfr_review.collectors.telemetry_config"):
            results = collector.collect(tmp_path, config=None)
        assert "YAML parse error" in caplog.text
        p = _payload(results, "telemetry-config-summary")
        assert p["files_failed"] == 1

    def test_hidden_dirs_excluded(
        self, collector: TelemetryConfigCollector, tmp_path: Path
    ) -> None:
        hidden = tmp_path / ".git" / "otel"
        hidden.mkdir(parents=True)
        (hidden / "otel-collector-config.yaml").write_text(
            "receivers:\n  otlp: {}\nexporters:\n  debug: {}\n"
            "service:\n  pipelines:\n    traces:\n"
            "      receivers: [otlp]\n      exporters: [debug]\n"
        )
        results = collector.collect(tmp_path, config=None)
        pipelines = _by_kind(results, "telemetry-pipeline")
        assert len(pipelines) == 0

    def test_locator_is_relative(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            if ev.kind != "telemetry-config-summary":
                assert not ev.locator.startswith("/")

    def test_collector_metadata(self, collector: TelemetryConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert ev.collector_name == "telemetry-config"
            assert ev.collector_version == "0.1.0"

    def test_non_source_files_ignored(
        self, collector: TelemetryConfigCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "readme.md").write_text("from opentelemetry import trace\n")
        results = collector.collect(tmp_path, config=None)
        sdk = _by_kind(results, "telemetry-sdk-init")
        assert len(sdk) == 0

    def test_unreadable_yaml_skipped(
        self,
        collector: TelemetryConfigCollector,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        f = tmp_path / "otel-collector-config.yaml"
        f.write_text(
            "receivers:\n  otlp: {}\nexporters:\n  debug: {}\n"
            "service:\n  pipelines:\n    traces:\n"
            "      receivers: [otlp]\n      exporters: [debug]\n"
        )
        f.chmod(0o000)
        try:
            with caplog.at_level(
                logging.WARNING, logger="nfr_review.collectors.telemetry_config"
            ):
                results = collector.collect(tmp_path, config=None)
            pipelines = _by_kind(results, "telemetry-pipeline")
            assert len(pipelines) == 0
            assert "Cannot read" in caplog.text
        finally:
            f.chmod(0o644)
