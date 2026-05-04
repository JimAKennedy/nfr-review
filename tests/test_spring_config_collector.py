"""Tests for the SpringConfigCollector — YAML/properties parsing, payload
structure, profile extraction, and fault isolation."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from nfr_review.collectors.spring_config import SpringConfigCollector

FIXTURES = Path(__file__).parent / "fixtures" / "java-sample-repo"


@pytest.fixture
def collector() -> SpringConfigCollector:
    return SpringConfigCollector()


class TestFileDiscovery:
    def test_finds_all_application_yaml_files(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        locators = {e.locator for e in results}
        assert any("application.yaml" in loc for loc in locators)
        assert any("application-prod.yaml" in loc for loc in locators)
        assert any("application-dev.yaml" in loc for loc in locators)

    def test_ignores_non_spring_yaml_files(
        self, collector: SpringConfigCollector, tmp_path: Path
    ) -> None:
        """Only application*.yaml / bootstrap*.yaml are collected."""
        resources = tmp_path / "src" / "main" / "resources"
        resources.mkdir(parents=True)
        (resources / "application.yaml").write_text("server:\n  port: 8080\n")
        (resources / "custom-config.yaml").write_text("custom:\n  key: value\n")
        (resources / "docker-compose.yaml").write_text("services:\n  app:\n    image: test\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert "application.yaml" in results[0].locator


class TestYamlParsing:
    def test_extracts_management_section(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        base = next(
            e
            for e in results
            if e.locator.endswith("application.yaml")
            and "prod" not in e.locator
            and "dev" not in e.locator
        )
        management = base.payload["management"]
        assert management["endpoints"]["web"]["exposure"]["include"] == "health,info,metrics"
        assert management["endpoint"]["health"]["show-details"] == "when-authorized"

    def test_extracts_logging_section(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        base = next(
            e
            for e in results
            if e.locator.endswith("application.yaml")
            and "prod" not in e.locator
            and "dev" not in e.locator
        )
        logging_section = base.payload["logging"]
        assert logging_section["level"]["root"] == "INFO"
        assert logging_section["level"]["com.example"] == "DEBUG"

    def test_extracts_server_section(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        base = next(
            e
            for e in results
            if e.locator.endswith("application.yaml")
            and "prod" not in e.locator
            and "dev" not in e.locator
        )
        server = base.payload["server"]
        assert server["port"] == 8080

    def test_extracts_spring_security_section(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        base = next(
            e
            for e in results
            if e.locator.endswith("application.yaml")
            and "prod" not in e.locator
            and "dev" not in e.locator
        )
        spring_sec = base.payload["spring_security"]
        assert (
            spring_sec["oauth2"]["resourceserver"]["jwt"]["issuer-uri"]
            == "https://auth.example.com"
        )

    def test_extracts_actuator_exposure(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        base = next(
            e
            for e in results
            if e.locator.endswith("application.yaml")
            and "prod" not in e.locator
            and "dev" not in e.locator
        )
        actuator = base.payload["actuator"]
        assert actuator["include"] == "health,info,metrics"

    def test_raw_keys_lists_top_level_keys(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        base = next(
            e
            for e in results
            if e.locator.endswith("application.yaml")
            and "prod" not in e.locator
            and "dev" not in e.locator
        )
        raw_keys = base.payload["raw_keys"]
        assert "server" in raw_keys
        assert "management" in raw_keys
        assert "logging" in raw_keys
        assert "spring" in raw_keys


class TestProfileExtraction:
    def test_prod_profile_extracted(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        prod = next(e for e in results if "application-prod.yaml" in e.locator)
        assert prod.payload["profile"] == "prod"

    def test_dev_profile_extracted(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        dev = next(e for e in results if "application-dev.yaml" in e.locator)
        assert dev.payload["profile"] == "dev"

    def test_base_config_has_no_profile(self, collector: SpringConfigCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        base = next(
            e
            for e in results
            if e.locator.endswith("application.yaml")
            and "prod" not in e.locator
            and "dev" not in e.locator
        )
        assert base.payload["profile"] is None


class TestEvidenceFields:
    def test_evidence_has_correct_collector_fields(
        self, collector: SpringConfigCollector
    ) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert len(results) >= 3
        for ev in results:
            assert ev.collector_name == "spring-config"
            assert ev.collector_version == "0.1.0"
            assert ev.kind == "spring-config-file"
            assert ev.locator  # non-empty


class TestFaultIsolation:
    def test_malformed_yaml_skipped_with_warning(
        self,
        collector: SpringConfigCollector,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        resources = tmp_path / "src" / "main" / "resources"
        resources.mkdir(parents=True)
        good = resources / "application.yaml"
        good.write_text("server:\n  port: 8080\n")
        bad = resources / "application-broken.yaml"
        bad.write_text(":\n  - [\ninvalid: {yaml: [}\n")
        with caplog.at_level(logging.WARNING, logger="nfr_review.collectors.spring_config"):
            results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert "application.yaml" in results[0].locator
        assert any(
            "Parse error" in rec.message or "broken" in rec.message for rec in caplog.records
        )

    def test_binary_yaml_file_handled_gracefully(
        self,
        collector: SpringConfigCollector,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        resources = tmp_path / "src" / "main" / "resources"
        resources.mkdir(parents=True)
        binary_file = resources / "application.yaml"
        binary_file.write_bytes(b"\x00\x01\x02\xff\xfe\x80binary garbage")
        with caplog.at_level(logging.WARNING, logger="nfr_review.collectors.spring_config"):
            results = collector.collect(tmp_path, config=None)
        # Either skipped or produced an error — should not crash
        assert isinstance(results, list)

    def test_empty_directory_returns_empty_list(
        self, collector: SpringConfigCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_empty_yaml_file_handled(
        self, collector: SpringConfigCollector, tmp_path: Path
    ) -> None:
        resources = tmp_path / "src" / "main" / "resources"
        resources.mkdir(parents=True)
        (resources / "application.yaml").write_text("")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].payload["raw_keys"] == []


class TestPropertiesSupport:
    def test_properties_file_parsed(
        self, collector: SpringConfigCollector, tmp_path: Path
    ) -> None:
        resources = tmp_path / "src" / "main" / "resources"
        resources.mkdir(parents=True)
        props = resources / "application.properties"
        props.write_text(
            "server.port=8080\n"
            "management.endpoints.web.exposure.include=health,info\n"
            "logging.level.root=INFO\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        ev = results[0]
        assert ev.payload["server"]["port"] == "8080"
        mgmt_include = ev.payload["management"]["endpoints"]["web"]
        assert mgmt_include["exposure"]["include"] == "health,info"
        assert ev.payload["logging"]["level"]["root"] == "INFO"
