"""Tests for PATCH-TELEM rules — golden signal emission, mandatory labels,
and synthetic transaction config detection."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence
from nfr_review.rules.patch_telem import (
    GoldenSignalEmissionRule,
    MandatoryLabelPresenceRule,
    SyntheticTransactionConfigRule,
)


def _pipeline_ev(
    signal_types: list[str],
    resource_attributes: dict[str, Any] | None = None,
    locator: str = "observability/otel-collector-config.yaml",
) -> Evidence:
    return Evidence(
        collector_name="telemetry-config",
        collector_version="0.1.0",
        locator=locator,
        kind="telemetry-pipeline",
        payload={
            "file_path": locator,
            "receivers": ["otlp"],
            "processors": ["batch"],
            "exporters": ["otlp"],
            "pipelines": {
                s: {"receivers": ["otlp"], "processors": ["batch"], "exporters": ["otlp"]}
                for s in signal_types
            },
            "signal_types": signal_types,
            "exporter_targets": [
                {"name": "otlp", "type": "otlp", "endpoint": "localhost:4317"}
            ],
            "resource_attributes": resource_attributes or {},
            "extensions": [],
        },
    )


def _summary_ev(
    collector_configs: int = 0,
    sdk_instrumentations: int = 0,
    synthetic_configs: int = 0,
) -> Evidence:
    return Evidence(
        collector_name="telemetry-config",
        collector_version="0.1.0",
        locator=".",
        kind="telemetry-config-summary",
        payload={
            "collector_configs_found": collector_configs,
            "sdk_instrumentations_found": sdk_instrumentations,
            "synthetic_configs_found": synthetic_configs,
            "signal_coverage": {"metrics": False, "traces": False, "logs": False},
            "files_parsed": 0,
            "files_failed": 0,
        },
    )


def _synthetic_ev(
    tool: str = "grafana-synthetic-monitoring",
    targets: list[str] | None = None,
    locator: str = "synthetics/checks.yaml",
) -> Evidence:
    return Evidence(
        collector_name="telemetry-config",
        collector_version="0.1.0",
        locator=locator,
        kind="telemetry-synthetic-config",
        payload={
            "file_path": locator,
            "tool": tool,
            "test_type": "http",
            "targets": targets or [],
            "frequency": "60000",
        },
    )


class TestGoldenSignalEmission:
    def setup_method(self) -> None:
        self.rule = GoldenSignalEmissionRule()

    def test_rule_metadata(self) -> None:
        assert self.rule.id == "PATCH-TELEM-001"
        assert self.rule.band == 2
        assert "telemetry-config" in self.rule.required_collectors

    def test_skipped_when_no_evidence(self) -> None:
        result = self.rule.evaluate([], context=None)
        assert result.skipped is True
        assert "no telemetry-config" in (result.skip_reason or "")

    def test_info_when_no_pipeline_evidence(self) -> None:
        result = self.rule.evaluate([_summary_ev()], context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert "not applicable" in f.summary.lower()
        assert f.pattern_tag == "patch-telem-golden-signals"

    def test_green_when_metrics_and_traces(self) -> None:
        ev = _pipeline_ev(signal_types=["metrics", "traces"])
        result = self.rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert f.rule_id == "PATCH-TELEM-001"
        assert f.pattern_tag == "patch-telem-golden-signals"

    def test_green_when_all_three_signals(self) -> None:
        ev = _pipeline_ev(signal_types=["metrics", "traces", "logs"])
        result = self.rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"

    def test_amber_when_only_metrics(self) -> None:
        ev = _pipeline_ev(signal_types=["metrics"])
        result = self.rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "traces" in f.summary

    def test_amber_when_only_traces(self) -> None:
        ev = _pipeline_ev(signal_types=["traces"])
        result = self.rule.evaluate([ev], context=None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert "metrics" in f.summary

    def test_amber_when_only_logs(self) -> None:
        ev = _pipeline_ev(signal_types=["logs"])
        result = self.rule.evaluate([ev], context=None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert "metrics" in f.summary
        assert "traces" in f.summary

    def test_multiple_configs_aggregated(self) -> None:
        ev1 = _pipeline_ev(signal_types=["metrics"], locator="config1.yaml")
        ev2 = _pipeline_ev(signal_types=["traces"], locator="config2.yaml")
        result = self.rule.evaluate([ev1, ev2], context=None)
        f = result.findings[0]
        assert f.rag == "green"
        assert "2 config(s)" in f.summary


class TestMandatoryLabelPresence:
    def setup_method(self) -> None:
        self.rule = MandatoryLabelPresenceRule()

    def test_rule_metadata(self) -> None:
        assert self.rule.id == "PATCH-TELEM-002"
        assert self.rule.band == 2
        assert "telemetry-config" in self.rule.required_collectors

    def test_skipped_when_no_evidence(self) -> None:
        result = self.rule.evaluate([], context=None)
        assert result.skipped is True

    def test_info_when_no_pipeline_evidence(self) -> None:
        result = self.rule.evaluate([_summary_ev()], context=None)
        assert not result.skipped
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert "not applicable" in f.summary.lower()
        assert f.pattern_tag == "patch-telem-labels"

    def test_green_when_all_labels_present(self) -> None:
        ev = _pipeline_ev(
            signal_types=["metrics", "traces"],
            resource_attributes={
                "service.name": "my-svc",
                "service.version": "1.0",
                "ring": "r1",
                "side": "active",
            },
        )
        result = self.rule.evaluate([ev], context=None)
        f = result.findings[0]
        assert f.rag == "green"
        assert f.rule_id == "PATCH-TELEM-002"
        assert f.pattern_tag == "patch-telem-labels"

    def test_green_with_alias_labels(self) -> None:
        ev = _pipeline_ev(
            signal_types=["metrics"],
            resource_attributes={
                "service": "my-svc",
                "version": "1.0",
                "deployment.ring": "r2",
                "deployment.side": "passive",
            },
        )
        result = self.rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"

    def test_amber_when_missing_ring_and_side(self) -> None:
        ev = _pipeline_ev(
            signal_types=["metrics", "traces"],
            resource_attributes={
                "service.name": "my-svc",
                "service.version": "1.0",
            },
        )
        result = self.rule.evaluate([ev], context=None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "ring" in f.summary
        assert "side" in f.summary

    def test_amber_when_missing_version(self) -> None:
        ev = _pipeline_ev(
            signal_types=["metrics"],
            resource_attributes={
                "service.name": "my-svc",
                "ring": "r0",
                "side": "active",
            },
        )
        result = self.rule.evaluate([ev], context=None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert "version" in f.summary

    def test_amber_when_no_attributes(self) -> None:
        ev = _pipeline_ev(signal_types=["metrics"], resource_attributes={})
        result = self.rule.evaluate([ev], context=None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert "service" in f.summary

    def test_labels_merged_across_configs(self) -> None:
        ev1 = _pipeline_ev(
            signal_types=["metrics"],
            resource_attributes={"service.name": "svc", "service.version": "1.0"},
            locator="config1.yaml",
        )
        ev2 = _pipeline_ev(
            signal_types=["traces"],
            resource_attributes={"ring": "r1", "side": "active"},
            locator="config2.yaml",
        )
        result = self.rule.evaluate([ev1, ev2], context=None)
        assert result.findings[0].rag == "green"


class TestSyntheticTransactionConfig:
    def setup_method(self) -> None:
        self.rule = SyntheticTransactionConfigRule()

    def test_rule_metadata(self) -> None:
        assert self.rule.id == "PATCH-TELEM-003"
        assert self.rule.band == 2
        assert "telemetry-config" in self.rule.required_collectors

    def test_skipped_when_no_evidence(self) -> None:
        result = self.rule.evaluate([], context=None)
        assert result.skipped is True

    def test_info_when_no_otel_and_no_synthetic(self) -> None:
        result = self.rule.evaluate([_summary_ev()], context=None)
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert "not applicable" in f.summary.lower()
        assert f.pattern_tag == "patch-telem-synthetic"

    def test_green_when_synthetic_with_targets(self) -> None:
        ev = _synthetic_ev(
            tool="grafana-synthetic-monitoring",
            targets=["https://api.example.com/health"],
        )
        result = self.rule.evaluate([ev], context=None)
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert f.rule_id == "PATCH-TELEM-003"
        assert "grafana" in f.summary.lower()
        assert f.pattern_tag == "patch-telem-synthetic"

    def test_green_with_datadog_synthetic(self) -> None:
        ev = _synthetic_ev(
            tool="datadog-synthetics",
            targets=["https://api.example.com/health"],
        )
        result = self.rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"

    def test_green_multiple_synthetics(self) -> None:
        ev1 = _synthetic_ev(
            tool="grafana-synthetic-monitoring",
            targets=["https://a.example.com"],
            locator="synth1.yaml",
        )
        ev2 = _synthetic_ev(
            tool="datadog-synthetics",
            targets=["https://b.example.com", "https://c.example.com"],
            locator="synth2.yaml",
        )
        result = self.rule.evaluate([ev1, ev2], context=None)
        f = result.findings[0]
        assert f.rag == "green"
        assert "3 endpoint(s)" in f.summary

    def test_amber_when_synthetic_has_no_targets(self) -> None:
        ev = _synthetic_ev(tool="checkly", targets=[])
        result = self.rule.evaluate([ev], context=None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "no target" in f.summary.lower()

    def test_amber_when_otel_but_no_synthetic(self) -> None:
        pipeline = _pipeline_ev(signal_types=["metrics", "traces"])
        result = self.rule.evaluate([pipeline], context=None)
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "no synthetic" in f.summary.lower()

    def test_green_when_otel_and_synthetic_both_present(self) -> None:
        pipeline = _pipeline_ev(signal_types=["metrics", "traces"])
        synth = _synthetic_ev(targets=["https://api.example.com/health"])
        result = self.rule.evaluate([pipeline, synth], context=None)
        assert result.findings[0].rag == "green"


class TestRegistration:
    def test_rules_in_registry(self) -> None:
        import importlib

        import nfr_review.rules.patch_telem

        importlib.reload(nfr_review.rules.patch_telem)
        from nfr_review.registry import rule_registry

        assert "PATCH-TELEM-001" in rule_registry
        assert "PATCH-TELEM-002" in rule_registry
        assert "PATCH-TELEM-003" in rule_registry
