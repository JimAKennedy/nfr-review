# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for S06 framework mandate coverage rules.

Tests use synthetic Evidence objects rather than full Engine integration.
"""

from __future__ import annotations

import pytest

from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.correlation_id import CorrelationIdMissingRule
from nfr_review.rules.health_probe_separation import HealthProbeSeparationRule
from nfr_review.rules.jacoco_threshold import JacocoThresholdRule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COLLECTOR_VERSION = "0.1.0"


def _java_deps_evidence(deps: list[dict]) -> Evidence:
    """Build a synthetic java-deps Evidence object."""
    return Evidence(
        collector_name="java-deps",
        collector_version=_COLLECTOR_VERSION,
        locator=".",
        kind="java-deps",
        payload={
            "dependencies": deps,
            "manifest_files_found": ["pom.xml"],
            "enrichment_errors": [],
        },
    )


def _dep(name: str, version: str = "1.0.0") -> dict:
    return {
        "name": name,
        "declared_version": version,
        "version_constraint": f">={version}",
        "source_file": "pom.xml",
        "latest_version": version,
        "latest_release_date": None,
        "deps_dev_status": "ok",
    }


def _k8s_evidence(
    resource_name: str,
    containers: list[dict],
    file_path: str = "k8s/deployment.yaml",
) -> Evidence:
    return Evidence(
        collector_name="k8s-manifest",
        collector_version=_COLLECTOR_VERSION,
        locator=file_path,
        kind="k8s-resource",
        payload={
            "file_path": file_path,
            "kind": "Deployment",
            "name": resource_name,
            "namespace": "default",
            "containers": containers,
        },
    )


def _container(
    name: str,
    liveness_probe: dict | None = None,
    readiness_probe: dict | None = None,
) -> dict:
    return {
        "name": name,
        "image": "myapp:latest",
        "resources": None,
        "liveness_probe": liveness_probe,
        "readiness_probe": readiness_probe,
        "startup_probe": None,
        "security_context": None,
        "pre_stop": None,
    }


# ---------------------------------------------------------------------------
# JacocoThresholdRule
# ---------------------------------------------------------------------------


class TestJacocoThresholdRule:
    def setup_method(self) -> None:
        self.rule = JacocoThresholdRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no java-deps evidence available"

    def test_wrong_collector_skipped(self) -> None:
        ev = Evidence(
            collector_name="other-collector",
            collector_version=_COLLECTOR_VERSION,
            locator=".",
            kind="java-deps",
            payload={"dependencies": []},
        )
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True

    def test_jacoco_absent_fires_amber(self) -> None:
        ev = _java_deps_evidence(
            [
                _dep("org.springframework.boot:spring-boot-starter-web"),
                _dep("org.springframework.boot:spring-boot-starter-data-jpa"),
                _dep("com.h2database:h2", "2.2.224"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "JaCoCo" in f.summary
        assert f.pattern_tag == "jacoco-coverage"
        assert f.collector_name == "java-deps"

    def test_jacoco_present_green(self) -> None:
        ev = _java_deps_evidence(
            [
                _dep("org.springframework.boot:spring-boot-starter-web"),
                _dep("org.jacoco:jacoco-maven-plugin", "0.8.11"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.pattern_tag == "jacoco-coverage"

    def test_jacoco_agent_also_accepted(self) -> None:
        """org.jacoco:jacoco-agent should also pass (same group)."""
        ev = _java_deps_evidence(
            [
                _dep("org.jacoco:jacoco-agent", "0.8.10"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rag == "green"

    def test_empty_deps_fires_amber(self) -> None:
        ev = _java_deps_evidence([])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"

    def test_rule_attributes(self) -> None:
        assert self.rule.id == "jacoco-threshold-missing"
        assert self.rule.band == 1
        assert "java-deps" in self.rule.required_collectors
        assert "java" in self.rule.required_tech


# ---------------------------------------------------------------------------
# CorrelationIdMissingRule
# ---------------------------------------------------------------------------


class TestCorrelationIdMissingRule:
    def setup_method(self) -> None:
        self.rule = CorrelationIdMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no java-deps evidence available"

    def test_no_tracing_dep_fires_amber(self) -> None:
        ev = _java_deps_evidence(
            [
                _dep("org.springframework.boot:spring-boot-starter-web"),
                _dep("org.springframework.boot:spring-boot-starter-data-jpa"),
                _dep("com.fasterxml.jackson.core:jackson-databind"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert f.pattern_tag == "correlation-id"
        assert f.collector_name == "java-deps"

    def test_sleuth_present_green(self) -> None:
        ev = _java_deps_evidence(
            [
                _dep("org.springframework.boot:spring-boot-starter-web"),
                _dep("org.springframework.cloud:spring-cloud-starter-sleuth", "3.1.11"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rag == "green"

    def test_micrometer_tracing_exact_green(self) -> None:
        ev = _java_deps_evidence(
            [
                _dep("io.micrometer:micrometer-tracing", "1.2.5"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_micrometer_tracing_bridge_brave_green(self) -> None:
        ev = _java_deps_evidence(
            [
                _dep("io.micrometer:micrometer-tracing-bridge-brave", "1.2.5"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_micrometer_tracing_bridge_otel_green(self) -> None:
        ev = _java_deps_evidence(
            [
                _dep("io.micrometer:micrometer-tracing-bridge-otel", "1.2.5"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_opentelemetry_api_green(self) -> None:
        ev = _java_deps_evidence(
            [
                _dep("io.opentelemetry:opentelemetry-api", "1.36.0"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_empty_deps_fires_amber(self) -> None:
        ev = _java_deps_evidence([])
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"

    def test_rule_attributes(self) -> None:
        assert self.rule.id == "correlation-id-missing"
        assert self.rule.band == 1
        assert "java-deps" in self.rule.required_collectors
        assert "java" in self.rule.required_tech


# ---------------------------------------------------------------------------
# HealthProbeSeparationRule
# ---------------------------------------------------------------------------


_HTTP_PROBE = {"httpGet": {"path": "/health", "port": 8080}, "initialDelaySeconds": 5}
_DISTINCT_LIVENESS = {"httpGet": {"path": "/livez", "port": 8080}}
_DISTINCT_READINESS = {"httpGet": {"path": "/readyz", "port": 8080}}


class TestHealthProbeSeparationRule:
    def setup_method(self) -> None:
        self.rule = HealthProbeSeparationRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no k8s-resource evidence available"

    def test_wrong_kind_skipped(self) -> None:
        ev = Evidence(
            collector_name="k8s-manifest",
            collector_version=_COLLECTOR_VERSION,
            locator="k8s/pdb.yaml",
            kind="k8s-pdb",
            payload={},
        )
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True

    def test_identical_probes_fires_amber(self) -> None:
        ev = _k8s_evidence(
            "my-deployment",
            [_container("app", liveness_probe=_HTTP_PROBE, readiness_probe=_HTTP_PROBE)],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "identical" in f.summary.lower()
        assert f.pattern_tag == "k8s-probe-separation"
        assert "app" in f.evidence_locator
        assert "my-deployment" in f.evidence_locator

    def test_distinct_probes_green(self) -> None:
        ev = _k8s_evidence(
            "my-deployment",
            [
                _container(
                    "app",
                    liveness_probe=_DISTINCT_LIVENESS,
                    readiness_probe=_DISTINCT_READINESS,
                )
            ],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_only_liveness_green(self) -> None:
        """Only one probe defined — not flagged (probes-missing handles that)."""
        ev = _k8s_evidence(
            "my-deployment",
            [_container("app", liveness_probe=_HTTP_PROBE, readiness_probe=None)],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_only_readiness_green(self) -> None:
        ev = _k8s_evidence(
            "my-deployment",
            [_container("app", liveness_probe=None, readiness_probe=_HTTP_PROBE)],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_no_probes_green(self) -> None:
        """No probes at all — not flagged by this rule."""
        ev = _k8s_evidence(
            "my-deployment",
            [_container("app")],
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_multiple_containers_partial_identical(self) -> None:
        """One container OK, one identical — still fires once."""
        ev = _k8s_evidence(
            "my-deployment",
            [
                _container(
                    "sidecar",
                    liveness_probe=_DISTINCT_LIVENESS,
                    readiness_probe=_DISTINCT_READINESS,
                ),
                _container(
                    "app",
                    liveness_probe=_HTTP_PROBE,
                    readiness_probe=_HTTP_PROBE,
                ),
            ],
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) == 1
        assert "app" in amber_findings[0].evidence_locator

    def test_multiple_containers_all_identical_fires_twice(self) -> None:
        ev = _k8s_evidence(
            "my-deployment",
            [
                _container("app", liveness_probe=_HTTP_PROBE, readiness_probe=_HTTP_PROBE),
                _container("init", liveness_probe=_HTTP_PROBE, readiness_probe=_HTTP_PROBE),
            ],
        )
        result = self.rule.evaluate([ev], None)
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) == 2

    def test_rule_attributes(self) -> None:
        assert self.rule.id == "health-probe-separation"
        assert self.rule.band == 1
        assert "k8s-manifest" in self.rule.required_collectors
        assert "kubernetes" in self.rule.required_tech


# ---------------------------------------------------------------------------
# Cross-cutting: all rules return RuleResult from evaluate()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_class",
    [JacocoThresholdRule, CorrelationIdMissingRule, HealthProbeSeparationRule],
)
def test_empty_evidence_returns_rule_result(rule_class: type) -> None:
    rule = rule_class()
    result = rule.evaluate([], None)
    assert isinstance(result, RuleResult)
    assert result.skipped is True


@pytest.mark.parametrize(
    "rule_class",
    [JacocoThresholdRule, CorrelationIdMissingRule, HealthProbeSeparationRule],
)
def test_rule_has_required_attributes(rule_class: type) -> None:
    rule = rule_class()
    assert isinstance(rule.id, str) and rule.id
    assert rule.band == 1
    assert isinstance(rule.required_collectors, list)
    assert isinstance(rule.required_tech, list)
