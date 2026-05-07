"""Tests for Helm NFR rules: chart-metadata, values-validation, secret-leakage."""

from __future__ import annotations

from typing import Any

import pytest

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.helm_chart_metadata import HelmChartMetadataRule
from nfr_review.rules.helm_secret_leakage import HelmSecretLeakageRule
from nfr_review.rules.helm_values_validation import HelmValuesValidationRule


def _make_evidence(
    *,
    chart_path: str = "my-chart",
    chart_name: str | None = "my-chart",
    chart_version: str | None = "1.0.0",
    app_version: str | None = "2.0.0",
    description: str | None = "A test chart",
    maintainers: list[dict[str, str]] | None = None,
    values: dict[str, Any] | None = None,
    rendered_manifests: list[dict[str, Any]] | None = None,
    template_files: list[str] | None = None,
    helm_available: bool = True,
) -> list[Evidence]:
    payload: dict[str, Any] = {
        "chart_path": chart_path,
        "chart_name": chart_name,
        "chart_version": chart_version,
        "app_version": app_version,
        "description": description,
        "values": values or {},
        "rendered_manifests": rendered_manifests or [],
        "template_files": template_files or [],
        "helm_available": helm_available,
    }
    if maintainers is not None:
        payload["maintainers"] = maintainers
    return [
        Evidence(
            collector_name="helm",
            collector_version="0.1.0",
            locator=chart_path,
            kind="helm-analysis",
            payload=payload,
        )
    ]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_chart_metadata_registered(self) -> None:
        assert "helm-chart-metadata" in rule_registry

    def test_values_validation_registered(self) -> None:
        assert "helm-values-validation" in rule_registry

    def test_secret_leakage_registered(self) -> None:
        assert "helm-secret-leakage" in rule_registry


# ---------------------------------------------------------------------------
# HelmChartMetadataRule
# ---------------------------------------------------------------------------


class TestChartMetadata:
    @pytest.fixture()
    def rule(self) -> HelmChartMetadataRule:
        return HelmChartMetadataRule()

    def test_skip_no_evidence(self, rule: HelmChartMetadataRule) -> None:
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert result.rule_id == "helm-chart-metadata"

    def test_skip_wrong_collector(self, rule: HelmChartMetadataRule) -> None:
        ev = [
            Evidence(
                collector_name="other",
                collector_version="1.0",
                locator="x",
                kind="other",
                payload={},
            )
        ]
        result = rule.evaluate(ev, None)
        assert result.skipped is True

    def test_complete_metadata_green(self, rule: HelmChartMetadataRule) -> None:
        evidence = _make_evidence(
            description="A real chart",
            app_version="1.0.0",
            chart_version="1.2.3",
            maintainers=[{"name": "Alice", "email": "alice@example.com"}],
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_missing_description_amber(self, rule: HelmChartMetadataRule) -> None:
        evidence = _make_evidence(
            description=None,
            maintainers=[{"name": "Alice"}],
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("description" in f.summary.lower() for f in amber)

    def test_missing_app_version_amber(self, rule: HelmChartMetadataRule) -> None:
        evidence = _make_evidence(
            app_version=None,
            maintainers=[{"name": "Alice"}],
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("appversion" in f.summary.lower() for f in amber)

    def test_missing_maintainers_amber(self, rule: HelmChartMetadataRule) -> None:
        evidence = _make_evidence()
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("maintainers" in f.summary.lower() for f in amber)
        assert amber[0].severity == "low"

    def test_non_semver_version_amber(self, rule: HelmChartMetadataRule) -> None:
        evidence = _make_evidence(
            chart_version="latest",
            maintainers=[{"name": "Alice"}],
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("semver" in f.summary.lower() for f in amber)

    def test_valid_semver_no_version_finding(self, rule: HelmChartMetadataRule) -> None:
        evidence = _make_evidence(
            chart_version="2.1.0-rc.1",
            maintainers=[{"name": "Alice"}],
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert not any("semver" in f.summary.lower() for f in amber)

    def test_empty_description_treated_as_missing(self, rule: HelmChartMetadataRule) -> None:
        evidence = _make_evidence(
            description="",
            maintainers=[{"name": "Alice"}],
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("description" in f.summary.lower() for f in amber)

    def test_finding_fields_match_r007(self, rule: HelmChartMetadataRule) -> None:
        evidence = _make_evidence(description=None)
        result = rule.evaluate(evidence, None)
        finding = result.findings[0]
        assert finding.rule_id == "helm-chart-metadata"
        assert finding.rag in ("red", "amber", "green", "skipped")
        assert finding.severity in ("critical", "high", "medium", "low", "info")
        assert finding.summary
        assert finding.recommendation
        assert finding.evidence_locator
        assert finding.collector_name == "helm"
        assert finding.collector_version == "0.1.0"
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.pattern_tag == "helm-chart-metadata"


# ---------------------------------------------------------------------------
# HelmValuesValidationRule
# ---------------------------------------------------------------------------


class TestValuesValidation:
    @pytest.fixture()
    def rule(self) -> HelmValuesValidationRule:
        return HelmValuesValidationRule()

    def test_skip_no_evidence(self, rule: HelmValuesValidationRule) -> None:
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert result.rule_id == "helm-values-validation"

    def test_skip_wrong_collector(self, rule: HelmValuesValidationRule) -> None:
        ev = [
            Evidence(
                collector_name="other",
                collector_version="1.0",
                locator="x",
                kind="other",
                payload={},
            )
        ]
        result = rule.evaluate(ev, None)
        assert result.skipped is True

    def test_proper_values_green(self, rule: HelmValuesValidationRule) -> None:
        evidence = _make_evidence(
            values={
                "replicaCount": 3,
                "image": {"repository": "nginx", "tag": "1.25.3"},
                "resources": {
                    "limits": {"cpu": "500m", "memory": "128Mi"},
                    "requests": {"cpu": "250m", "memory": "64Mi"},
                },
            },
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_missing_resources_amber(self, rule: HelmValuesValidationRule) -> None:
        evidence = _make_evidence(
            values={
                "replicaCount": 1,
                "image": {"repository": "nginx", "tag": "1.25"},
                "resources": {},
            },
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("resource" in f.summary.lower() for f in amber)
        resource_finding = [f for f in amber if "resource" in f.summary.lower()][0]
        assert resource_finding.severity == "high"

    def test_no_resources_key_amber(self, rule: HelmValuesValidationRule) -> None:
        evidence = _make_evidence(
            values={
                "replicaCount": 1,
                "image": {"repository": "nginx", "tag": "1.25"},
            },
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("resource" in f.summary.lower() for f in amber)

    def test_latest_image_tag_amber(self, rule: HelmValuesValidationRule) -> None:
        evidence = _make_evidence(
            values={
                "replicaCount": 1,
                "image": {"repository": "nginx", "tag": "latest"},
                "resources": {"limits": {"cpu": "1"}},
            },
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("latest" in f.summary.lower() for f in amber)
        tag_finding = [f for f in amber if "latest" in f.summary.lower()][0]
        assert tag_finding.severity == "medium"

    def test_missing_image_tag_amber(self, rule: HelmValuesValidationRule) -> None:
        evidence = _make_evidence(
            values={
                "replicaCount": 1,
                "image": {"repository": "nginx"},
                "resources": {"limits": {"cpu": "1"}},
            },
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("no image tag" in f.summary.lower() for f in amber)

    def test_missing_replica_count_amber(self, rule: HelmValuesValidationRule) -> None:
        evidence = _make_evidence(
            values={
                "image": {"repository": "nginx", "tag": "1.25"},
                "resources": {"limits": {"cpu": "1"}},
            },
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("replicacount" in f.summary.lower() for f in amber)
        replica_finding = [f for f in amber if "replicacount" in f.summary.lower()][0]
        assert replica_finding.severity == "low"

    def test_finding_fields_match_r007(self, rule: HelmValuesValidationRule) -> None:
        evidence = _make_evidence(values={"resources": {}})
        result = rule.evaluate(evidence, None)
        finding = result.findings[0]
        assert finding.rule_id == "helm-values-validation"
        assert finding.pattern_tag == "helm-values-validation"
        assert finding.collector_name == "helm"


# ---------------------------------------------------------------------------
# HelmSecretLeakageRule
# ---------------------------------------------------------------------------


class TestSecretLeakage:
    @pytest.fixture()
    def rule(self) -> HelmSecretLeakageRule:
        return HelmSecretLeakageRule()

    def test_skip_no_evidence(self, rule: HelmSecretLeakageRule) -> None:
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert result.rule_id == "helm-secret-leakage"

    def test_skip_wrong_collector(self, rule: HelmSecretLeakageRule) -> None:
        ev = [
            Evidence(
                collector_name="other",
                collector_version="1.0",
                locator="x",
                kind="other",
                payload={},
            )
        ]
        result = rule.evaluate(ev, None)
        assert result.skipped is True

    def test_no_secrets_green(self, rule: HelmSecretLeakageRule) -> None:
        evidence = _make_evidence(
            values={"replicaCount": 3, "service": {"port": 80}},
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_plaintext_password_in_values_red(self, rule: HelmSecretLeakageRule) -> None:
        evidence = _make_evidence(
            values={
                "database": {
                    "host": "localhost",
                    "password": "supersecret123",
                },
            },
        )
        result = rule.evaluate(evidence, None)
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) >= 1
        assert any("password" in f.summary.lower() for f in red)
        assert red[0].severity == "high"

    def test_api_key_in_values_red(self, rule: HelmSecretLeakageRule) -> None:
        evidence = _make_evidence(
            values={"apiKey": "sk-1234567890abcdef"},
        )
        result = rule.evaluate(evidence, None)
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) >= 1
        assert any("apikey" in f.summary.lower() for f in red)

    def test_token_in_values_red(self, rule: HelmSecretLeakageRule) -> None:
        evidence = _make_evidence(
            values={"auth": {"token": "eyJhbGciOiJIUzI1NiJ9.test"}},
        )
        result = rule.evaluate(evidence, None)
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) >= 1

    def test_template_ref_not_flagged(self, rule: HelmSecretLeakageRule) -> None:
        evidence = _make_evidence(
            values={
                "database": {
                    "password": "{{ .Values.global.dbPassword }}",
                },
            },
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_empty_value_not_flagged(self, rule: HelmSecretLeakageRule) -> None:
        evidence = _make_evidence(
            values={"database": {"password": ""}},
        )
        result = rule.evaluate(evidence, None)
        assert all(f.rag == "green" for f in result.findings)

    def test_secret_in_rendered_non_secret_manifest_critical(
        self, rule: HelmSecretLeakageRule
    ) -> None:
        evidence = _make_evidence(
            rendered_manifests=[
                {
                    "kind": "ConfigMap",
                    "metadata": {"name": "app-config"},
                    "data": {"db_password": "hardcoded123"},
                }
            ],
        )
        result = rule.evaluate(evidence, None)
        red = [f for f in result.findings if f.rag == "red"]
        critical = [f for f in red if f.severity == "critical"]
        assert len(critical) >= 1
        assert any("configmap" in f.summary.lower() for f in critical)

    def test_secret_in_k8s_secret_resource_not_flagged(
        self, rule: HelmSecretLeakageRule
    ) -> None:
        evidence = _make_evidence(
            rendered_manifests=[
                {
                    "kind": "Secret",
                    "metadata": {"name": "db-creds"},
                    "data": {"password": "base64encodedvalue"},
                }
            ],
        )
        result = rule.evaluate(evidence, None)
        assert all(f.rag == "green" for f in result.findings)

    def test_nested_secret_detected(self, rule: HelmSecretLeakageRule) -> None:
        evidence = _make_evidence(
            values={
                "external": {
                    "service": {
                        "api_key": "real-key-value-12345",
                    },
                },
            },
        )
        result = rule.evaluate(evidence, None)
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) >= 1
        assert any("api_key" in f.summary for f in red)

    def test_multiple_secrets_multiple_findings(self, rule: HelmSecretLeakageRule) -> None:
        evidence = _make_evidence(
            values={
                "database": {"password": "secret1"},
                "apiKey": "secret2",
            },
        )
        result = rule.evaluate(evidence, None)
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) >= 2

    def test_finding_fields_match_r007(self, rule: HelmSecretLeakageRule) -> None:
        evidence = _make_evidence(
            values={"password": "leaked"},
        )
        result = rule.evaluate(evidence, None)
        finding = result.findings[0]
        assert finding.rule_id == "helm-secret-leakage"
        assert finding.pattern_tag == "helm-secret-leakage"
        assert finding.collector_name == "helm"
        assert 0.0 <= finding.confidence <= 1.0

    def test_secret_value_truncated_in_summary(self, rule: HelmSecretLeakageRule) -> None:
        long_secret = "a" * 50
        evidence = _make_evidence(
            values={"password": long_secret},
        )
        result = rule.evaluate(evidence, None)
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) == 1
        assert long_secret not in red[0].summary
        assert "..." in red[0].summary
