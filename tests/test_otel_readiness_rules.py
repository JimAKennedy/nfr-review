"""Tests for S01 OTel instrumentation readiness rules."""

from __future__ import annotations

import importlib

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.otel_file_exporter import OTelFileExporterRule
from nfr_review.rules.otel_resource_attrs import OTelResourceAttrsRule
from nfr_review.rules.otel_test_agent import OTelTestAgentRule
from nfr_review.rules.otel_w3c_propagation import OTelW3CPropagationRule


def _make_sdk_evidence(
    *,
    agent_attached: bool = False,
    exporter_type: str | None = None,
    propagators: list[str] | None = None,
    resource_attributes: dict[str, str] | None = None,
    source_file: str = "docker-compose.yml",
) -> list[Evidence]:
    return [
        Evidence(
            collector_name="otel",
            collector_version="0.1.0",
            locator=source_file,
            kind="otel-sdk-config",
            payload={
                "agent_attached": agent_attached,
                "exporter_type": exporter_type,
                "propagators": propagators or [],
                "resource_attributes": resource_attributes or {},
                "source_file": source_file,
            },
        )
    ]


def _make_otel_analysis_evidence(*, exporters: list[str] | None = None) -> list[Evidence]:
    return [
        Evidence(
            collector_name="otel",
            collector_version="0.1.0",
            locator="otel-collector-config.yaml",
            kind="otel-analysis",
            payload={
                "file_path": "otel-collector-config.yaml",
                "receivers": [],
                "processors": [],
                "exporters": exporters or [],
                "pipelines": {},
            },
        )
    ]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_test_agent_registered(self) -> None:
        import nfr_review.rules.otel_test_agent

        importlib.reload(nfr_review.rules.otel_test_agent)
        assert "otel-test-agent" in rule_registry

    def test_file_exporter_registered(self) -> None:
        import nfr_review.rules.otel_file_exporter

        importlib.reload(nfr_review.rules.otel_file_exporter)
        assert "otel-file-exporter" in rule_registry

    def test_w3c_propagation_registered(self) -> None:
        import nfr_review.rules.otel_w3c_propagation

        importlib.reload(nfr_review.rules.otel_w3c_propagation)
        assert "otel-w3c-propagation" in rule_registry

    def test_resource_attrs_registered(self) -> None:
        import nfr_review.rules.otel_resource_attrs

        importlib.reload(nfr_review.rules.otel_resource_attrs)
        assert "otel-resource-attrs" in rule_registry


# ---------------------------------------------------------------------------
# Rule attributes
# ---------------------------------------------------------------------------


class TestRuleAttributes:
    def test_test_agent_attributes(self) -> None:
        rule = OTelTestAgentRule()
        assert rule.id == "otel-test-agent"
        assert rule.band == 1
        assert rule.required_collectors == ["otel"]

    def test_file_exporter_attributes(self) -> None:
        rule = OTelFileExporterRule()
        assert rule.id == "otel-file-exporter"
        assert rule.band == 1
        assert rule.required_collectors == ["otel"]

    def test_w3c_propagation_attributes(self) -> None:
        rule = OTelW3CPropagationRule()
        assert rule.id == "otel-w3c-propagation"
        assert rule.band == 1
        assert rule.required_collectors == ["otel"]

    def test_resource_attrs_attributes(self) -> None:
        rule = OTelResourceAttrsRule()
        assert rule.id == "otel-resource-attrs"
        assert rule.band == 1
        assert rule.required_collectors == ["otel"]


# ---------------------------------------------------------------------------
# OTelTestAgentRule
# ---------------------------------------------------------------------------


class TestOTelTestAgent:
    def setup_method(self) -> None:
        self.rule = OTelTestAgentRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no otel-sdk-config evidence" in result.skip_reason

    def test_skip_wrong_kind(self) -> None:
        evidence = _make_otel_analysis_evidence(exporters=["otlp"])
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True

    def test_green_agent_attached(self) -> None:
        evidence = _make_sdk_evidence(agent_attached=True)
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"

    def test_amber_no_agent(self) -> None:
        evidence = _make_sdk_evidence(agent_attached=False)
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert "agent" in result.findings[0].summary.lower()

    def test_green_agent_in_any_source(self) -> None:
        evidence = [
            Evidence(
                collector_name="otel",
                collector_version="0.1.0",
                locator="docker-compose.yml",
                kind="otel-sdk-config",
                payload={
                    "agent_attached": False,
                    "exporter_type": None,
                    "propagators": [],
                    "resource_attributes": {},
                    "source_file": "docker-compose.yml",
                },
            ),
            Evidence(
                collector_name="otel",
                collector_version="0.1.0",
                locator="pom.xml",
                kind="otel-sdk-config",
                payload={
                    "agent_attached": True,
                    "exporter_type": None,
                    "propagators": [],
                    "resource_attributes": {},
                    "source_file": "pom.xml",
                },
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_finding_fields_complete(self) -> None:
        evidence = _make_sdk_evidence(agent_attached=False)
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-test-agent"
        assert f.collector_name == "otel"
        assert f.collector_version == "0.1.0"
        assert f.confidence >= 0.0
        assert f.pattern_tag == "otel-test-agent"
        assert f.recommendation


# ---------------------------------------------------------------------------
# OTelFileExporterRule
# ---------------------------------------------------------------------------


class TestOTelFileExporter:
    def setup_method(self) -> None:
        self.rule = OTelFileExporterRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_green_file_exporter_in_sdk(self) -> None:
        evidence = _make_sdk_evidence(exporter_type="file")
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_green_file_exporter_in_collector(self) -> None:
        evidence = _make_otel_analysis_evidence(exporters=["file"])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_amber_no_file_exporter(self) -> None:
        evidence = _make_sdk_evidence(exporter_type="otlp")
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "file exporter" in result.findings[0].summary.lower()

    def test_amber_collector_without_file(self) -> None:
        evidence = _make_otel_analysis_evidence(exporters=["otlp", "jaeger"])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"

    def test_finding_fields_complete(self) -> None:
        evidence = _make_sdk_evidence(exporter_type="otlp")
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-file-exporter"
        assert f.collector_name == "otel"
        assert f.confidence >= 0.0
        assert f.pattern_tag == "otel-file-exporter"


# ---------------------------------------------------------------------------
# OTelW3CPropagationRule
# ---------------------------------------------------------------------------


class TestOTelW3CPropagation:
    def setup_method(self) -> None:
        self.rule = OTelW3CPropagationRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_green_tracecontext(self) -> None:
        evidence = _make_sdk_evidence(propagators=["tracecontext", "baggage"])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_green_w3c(self) -> None:
        evidence = _make_sdk_evidence(propagators=["w3c"])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_amber_other_propagator(self) -> None:
        evidence = _make_sdk_evidence(propagators=["b3multi"])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "b3multi" in result.findings[0].summary

    def test_amber_no_propagators(self) -> None:
        evidence = _make_sdk_evidence(propagators=[])
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "No trace-context propagation" in result.findings[0].summary

    def test_green_multiple_sources(self) -> None:
        evidence = [
            Evidence(
                collector_name="otel",
                collector_version="0.1.0",
                locator="compose.yml",
                kind="otel-sdk-config",
                payload={
                    "agent_attached": False,
                    "exporter_type": None,
                    "propagators": ["b3"],
                    "resource_attributes": {},
                    "source_file": "compose.yml",
                },
            ),
            Evidence(
                collector_name="otel",
                collector_version="0.1.0",
                locator="application.yml",
                kind="otel-sdk-config",
                payload={
                    "agent_attached": False,
                    "exporter_type": None,
                    "propagators": ["tracecontext"],
                    "resource_attributes": {},
                    "source_file": "application.yml",
                },
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_finding_fields_complete(self) -> None:
        evidence = _make_sdk_evidence(propagators=[])
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-w3c-propagation"
        assert f.collector_name == "otel"
        assert f.confidence >= 0.0
        assert f.pattern_tag == "otel-w3c-propagation"


# ---------------------------------------------------------------------------
# OTelResourceAttrsRule
# ---------------------------------------------------------------------------


class TestOTelResourceAttrs:
    def setup_method(self) -> None:
        self.rule = OTelResourceAttrsRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_green_both_attrs(self) -> None:
        evidence = _make_sdk_evidence(
            resource_attributes={
                "service.name": "my-svc",
                "service.version": "1.0.0",
            }
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_amber_missing_version(self) -> None:
        evidence = _make_sdk_evidence(resource_attributes={"service.name": "my-svc"})
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "service.version" in result.findings[0].summary

    def test_amber_missing_name(self) -> None:
        evidence = _make_sdk_evidence(resource_attributes={"service.version": "1.0"})
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "service.name" in result.findings[0].summary

    def test_amber_no_attrs(self) -> None:
        evidence = _make_sdk_evidence(resource_attributes={})
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "service.name" in result.findings[0].summary
        assert "service.version" in result.findings[0].summary

    def test_green_attrs_from_multiple_sources(self) -> None:
        evidence = [
            Evidence(
                collector_name="otel",
                collector_version="0.1.0",
                locator="compose.yml",
                kind="otel-sdk-config",
                payload={
                    "agent_attached": False,
                    "exporter_type": None,
                    "propagators": [],
                    "resource_attributes": {"service.name": "demo"},
                    "source_file": "compose.yml",
                },
            ),
            Evidence(
                collector_name="otel",
                collector_version="0.1.0",
                locator="application.yml",
                kind="otel-sdk-config",
                payload={
                    "agent_attached": False,
                    "exporter_type": None,
                    "propagators": [],
                    "resource_attributes": {"service.version": "1.0"},
                    "source_file": "application.yml",
                },
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_finding_fields_complete(self) -> None:
        evidence = _make_sdk_evidence(resource_attributes={})
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-resource-attrs"
        assert f.collector_name == "otel"
        assert f.confidence >= 0.0
        assert f.pattern_tag == "otel-resource-attrs"
