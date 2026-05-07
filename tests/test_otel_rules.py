"""Tests for OTel NFR rules: exporter-config, pipeline-completeness, sampling."""

from __future__ import annotations

import importlib
from typing import Any

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.otel_exporter import OTelExporterConfigRule
from nfr_review.rules.otel_pipeline import OTelPipelineCompletenessRule
from nfr_review.rules.otel_sampling import OTelSamplingRule


def _make_otel_evidence(
    *,
    receivers: list[str] | None = None,
    processors: list[str] | None = None,
    exporters: list[str] | None = None,
    pipelines: dict[str, Any] | None = None,
    locator: str = "otel-collector-config.yaml",
) -> list[Evidence]:
    return [
        Evidence(
            collector_name="otel",
            collector_version="0.1.0",
            locator=locator,
            kind="otel-analysis",
            payload={
                "file_path": locator,
                "receivers": receivers or [],
                "processors": processors or [],
                "exporters": exporters or [],
                "pipelines": pipelines or {},
            },
        )
    ]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_exporter_registered(self) -> None:
        import nfr_review.rules.otel_exporter

        importlib.reload(nfr_review.rules.otel_exporter)
        assert "otel-exporter-config" in rule_registry

    def test_pipeline_registered(self) -> None:
        import nfr_review.rules.otel_pipeline

        importlib.reload(nfr_review.rules.otel_pipeline)
        assert "otel-pipeline-completeness" in rule_registry

    def test_sampling_registered(self) -> None:
        import nfr_review.rules.otel_sampling

        importlib.reload(nfr_review.rules.otel_sampling)
        assert "otel-sampling" in rule_registry


# ---------------------------------------------------------------------------
# Rule attributes
# ---------------------------------------------------------------------------


class TestRuleAttributes:
    def test_exporter_attributes(self) -> None:
        rule = OTelExporterConfigRule()
        assert rule.id == "otel-exporter-config"
        assert rule.band == 1
        assert rule.required_collectors == ["otel"]
        assert rule.required_tech == ["otel"]

    def test_pipeline_attributes(self) -> None:
        rule = OTelPipelineCompletenessRule()
        assert rule.id == "otel-pipeline-completeness"
        assert rule.band == 1
        assert rule.required_collectors == ["otel"]
        assert rule.required_tech == ["otel"]

    def test_sampling_attributes(self) -> None:
        rule = OTelSamplingRule()
        assert rule.id == "otel-sampling"
        assert rule.band == 1
        assert rule.required_collectors == ["otel"]
        assert rule.required_tech == ["otel"]


# ---------------------------------------------------------------------------
# OTelExporterConfigRule
# ---------------------------------------------------------------------------


class TestOTelExporterConfig:
    def setup_method(self) -> None:
        self.rule = OTelExporterConfigRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no otel-analysis evidence" in result.skip_reason

    def test_skip_wrong_collector(self) -> None:
        evidence = [
            Evidence(
                collector_name="istio",
                collector_version="0.1.0",
                locator="istio.yaml",
                kind="istio-analysis",
                payload={},
            )
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True

    def test_red_only_logging_exporter(self) -> None:
        evidence = _make_otel_evidence(exporters=["logging"])
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert "production exporter" in f.summary.lower() or "No production" in f.summary

    def test_red_only_debug_exporter(self) -> None:
        evidence = _make_otel_evidence(exporters=["debug"])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"

    def test_red_multiple_dev_exporters(self) -> None:
        evidence = _make_otel_evidence(exporters=["logging", "debug", "file"])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"

    def test_red_no_exporters(self) -> None:
        evidence = _make_otel_evidence(exporters=[])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"

    def test_amber_single_prod_exporter(self) -> None:
        evidence = _make_otel_evidence(exporters=["otlp"])
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert "redundancy" in result.findings[0].recommendation.lower()

    def test_amber_single_prod_with_dev(self) -> None:
        evidence = _make_otel_evidence(exporters=["jaeger", "logging"])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"

    def test_green_multiple_prod_exporters(self) -> None:
        evidence = _make_otel_evidence(exporters=["otlp", "prometheus"])
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"

    def test_green_named_exporter_instances(self) -> None:
        evidence = _make_otel_evidence(exporters=["otlp/primary", "jaeger/backup"])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_finding_fields_complete(self) -> None:
        evidence = _make_otel_evidence(exporters=["logging"])
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-exporter-config"
        assert f.collector_name == "otel"
        assert f.collector_version == "0.1.0"
        assert f.confidence >= 0.0
        assert f.evidence_locator == "otel-collector-config.yaml"
        assert f.pattern_tag == "otel-exporter-config"
        assert f.recommendation


# ---------------------------------------------------------------------------
# OTelPipelineCompletenessRule
# ---------------------------------------------------------------------------


class TestOTelPipelineCompleteness:
    def setup_method(self) -> None:
        self.rule = OTelPipelineCompletenessRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no otel-analysis evidence" in result.skip_reason

    def test_skip_wrong_kind(self) -> None:
        evidence = [
            Evidence(
                collector_name="otel",
                collector_version="0.1.0",
                locator="other.yaml",
                kind="other-kind",
                payload={},
            )
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True

    def test_red_no_pipelines(self) -> None:
        evidence = _make_otel_evidence(
            receivers=["otlp"],
            exporters=["otlp"],
            pipelines={},
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        assert "No pipelines" in result.findings[0].summary

    def test_red_undefined_receiver_reference(self) -> None:
        evidence = _make_otel_evidence(
            receivers=["otlp"],
            exporters=["otlp"],
            pipelines={
                "traces": {
                    "receivers": ["otlp", "nonexistent"],
                    "exporters": ["otlp"],
                }
            },
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"
        assert "undefined" in result.findings[0].summary.lower()

    def test_red_undefined_exporter_reference(self) -> None:
        evidence = _make_otel_evidence(
            receivers=["otlp"],
            exporters=["otlp"],
            pipelines={
                "traces": {
                    "receivers": ["otlp"],
                    "exporters": ["otlp", "ghost"],
                }
            },
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"
        assert "undefined" in result.findings[0].summary.lower()

    def test_amber_only_traces(self) -> None:
        evidence = _make_otel_evidence(
            receivers=["otlp"],
            exporters=["otlp"],
            pipelines={
                "traces": {
                    "receivers": ["otlp"],
                    "exporters": ["otlp"],
                }
            },
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert "logs" in result.findings[0].summary.lower()
        assert "metrics" in result.findings[0].summary.lower()

    def test_amber_traces_and_metrics_only(self) -> None:
        evidence = _make_otel_evidence(
            receivers=["otlp"],
            exporters=["otlp"],
            pipelines={
                "traces": {"receivers": ["otlp"], "exporters": ["otlp"]},
                "metrics": {"receivers": ["otlp"], "exporters": ["otlp"]},
            },
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "logs" in result.findings[0].summary.lower()

    def test_green_all_three_signals(self) -> None:
        evidence = _make_otel_evidence(
            receivers=["otlp"],
            exporters=["otlp"],
            pipelines={
                "traces": {"receivers": ["otlp"], "exporters": ["otlp"]},
                "metrics": {"receivers": ["otlp"], "exporters": ["otlp"]},
                "logs": {"receivers": ["otlp"], "exporters": ["otlp"]},
            },
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"

    def test_green_named_pipelines(self) -> None:
        evidence = _make_otel_evidence(
            receivers=["otlp"],
            exporters=["otlp"],
            pipelines={
                "traces/primary": {"receivers": ["otlp"], "exporters": ["otlp"]},
                "metrics/prometheus": {"receivers": ["otlp"], "exporters": ["otlp"]},
                "logs/loki": {"receivers": ["otlp"], "exporters": ["otlp"]},
            },
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_finding_fields_complete(self) -> None:
        evidence = _make_otel_evidence(
            receivers=["otlp"],
            exporters=["otlp"],
            pipelines={},
        )
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-pipeline-completeness"
        assert f.collector_name == "otel"
        assert f.collector_version == "0.1.0"
        assert f.confidence >= 0.0
        assert f.evidence_locator == "otel-collector-config.yaml"
        assert f.pattern_tag == "otel-pipeline-completeness"
        assert f.recommendation


# ---------------------------------------------------------------------------
# OTelSamplingRule
# ---------------------------------------------------------------------------


class TestOTelSampling:
    def setup_method(self) -> None:
        self.rule = OTelSamplingRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no otel-analysis evidence" in result.skip_reason

    def test_skip_wrong_collector(self) -> None:
        evidence = [
            Evidence(
                collector_name="terraform",
                collector_version="0.1.0",
                locator="main.tf",
                kind="terraform-analysis",
                payload={},
            )
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True

    def test_amber_no_sampling(self) -> None:
        evidence = _make_otel_evidence(
            processors=["batch", "attributes"],
            pipelines={
                "traces": {
                    "receivers": ["otlp"],
                    "processors": ["batch"],
                    "exporters": ["otlp"],
                }
            },
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert (
            "sampling" in result.findings[0].summary.lower()
            or "rate" in result.findings[0].summary.lower()
        )

    def test_amber_empty_processors(self) -> None:
        evidence = _make_otel_evidence(processors=[], pipelines={})
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"

    def test_green_probabilistic_sampler(self) -> None:
        evidence = _make_otel_evidence(
            processors=["probabilistic_sampler", "batch"],
            pipelines={
                "traces": {
                    "receivers": ["otlp"],
                    "processors": ["probabilistic_sampler", "batch"],
                    "exporters": ["otlp"],
                }
            },
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"

    def test_green_tail_sampling(self) -> None:
        evidence = _make_otel_evidence(
            processors=["tail_sampling"],
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_green_filter_processor(self) -> None:
        evidence = _make_otel_evidence(
            processors=["filter"],
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_green_memory_limiter(self) -> None:
        evidence = _make_otel_evidence(
            processors=["memory_limiter"],
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_green_named_processor_instance(self) -> None:
        evidence = _make_otel_evidence(
            processors=["probabilistic_sampler/default"],
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_finding_fields_complete(self) -> None:
        evidence = _make_otel_evidence(processors=["batch"])
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-sampling"
        assert f.collector_name == "otel"
        assert f.collector_version == "0.1.0"
        assert f.confidence >= 0.0
        assert f.evidence_locator == "otel-collector-config.yaml"
        assert f.pattern_tag == "otel-sampling"
        assert f.recommendation
