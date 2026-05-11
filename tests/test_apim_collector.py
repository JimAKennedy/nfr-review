"""Tests for ApimPolicyCollector -- fixture-based and edge cases."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

from nfr_review.collectors.apim_policy import ApimPolicyCollector

FIXTURES = Path(__file__).parent / "fixtures" / "apim-sample-repo"


@pytest.fixture()
def collector() -> ApimPolicyCollector:
    return ApimPolicyCollector()


# ---------------------------------------------------------------------------
# Fixture-based tests
# ---------------------------------------------------------------------------


class TestApimFixtures:
    def test_discovers_all_policy_files(self, collector: ApimPolicyCollector) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        assert len(evidence) == 3

    def test_good_policy_parsed_correctly(self, collector: ApimPolicyCollector) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        good = next(e for e in evidence if "good-policy" in e.payload["file_path"])
        assert good.payload["has_rate_limit"] is True
        assert good.payload["has_auth_policy"] is True
        assert good.payload["backend_urls"] == ["{{backend-url}}"]
        assert good.payload["uses_named_values"] is True
        assert "rate-limit" in good.payload["inbound_policies"]
        assert "validate-jwt" in good.payload["inbound_policies"]
        assert "base" in good.payload["outbound_policies"]

    def test_bad_policy_parsed_correctly(self, collector: ApimPolicyCollector) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        bad = next(e for e in evidence if "bad-policy" in e.payload["file_path"])
        assert bad.payload["has_rate_limit"] is False
        assert bad.payload["has_auth_policy"] is False
        assert bad.payload["backend_urls"] == ["https://api.example.com/v1"]
        assert bad.payload["uses_named_values"] is False

    def test_partial_policy_parsed_correctly(self, collector: ApimPolicyCollector) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        partial = next(e for e in evidence if "partial-policy" in e.payload["file_path"])
        assert partial.payload["has_rate_limit"] is True
        assert partial.payload["has_auth_policy"] is False
        assert partial.payload["backend_urls"] == ["{{api-backend}}"]
        assert partial.payload["uses_named_values"] is True
        assert "rate-limit-by-key" in partial.payload["inbound_policies"]

    def test_evidence_metadata(self, collector: ApimPolicyCollector) -> None:
        evidence = collector.collect(FIXTURES, config=None)
        for ev in evidence:
            assert ev.collector_name == "apim-policy"
            assert ev.collector_version == "0.1.0"
            assert ev.kind == "apim-policy"
            assert ev.locator  # non-empty


# ---------------------------------------------------------------------------
# Edge-case tests
# ---------------------------------------------------------------------------


class TestApimEdgeCases:
    def test_empty_directory_returns_empty(
        self, collector: ApimPolicyCollector, tmp_path: Path
    ) -> None:
        evidence = collector.collect(tmp_path, config=None)
        assert evidence == []

    def test_malformed_xml_handled_gracefully(
        self, collector: ApimPolicyCollector, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()
        bad_xml = policies_dir / "broken.xml"
        bad_xml.write_text("<<< this is not valid xml >>>")

        with caplog.at_level(logging.DEBUG, logger="nfr_review.collectors.apim_policy"):
            evidence = collector.collect(tmp_path, config=None)

        assert evidence == []
        assert any("Error parsing" in record.message for record in caplog.records)

    def test_non_apim_xml_skipped(
        self, collector: ApimPolicyCollector, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()
        non_apim = policies_dir / "config.xml"
        non_apim.write_text(
            textwrap.dedent("""\
            <configuration>
                <setting name="debug" value="true" />
            </configuration>
        """)
        )

        with caplog.at_level(logging.DEBUG, logger="nfr_review.collectors.apim_policy"):
            evidence = collector.collect(tmp_path, config=None)

        assert evidence == []
        assert any("not an APIM policy" in record.message for record in caplog.records)

    def test_file_discovery_in_policies_dir(
        self, collector: ApimPolicyCollector, tmp_path: Path
    ) -> None:
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()
        policy = policies_dir / "test.xml"
        policy.write_text(
            textwrap.dedent("""\
            <policies>
                <inbound><base /></inbound>
                <backend />
                <outbound><base /></outbound>
            </policies>
        """)
        )

        evidence = collector.collect(tmp_path, config=None)
        assert len(evidence) == 1
        assert evidence[0].payload["file_path"] == "policies/test.xml"

    def test_file_discovery_via_policy_glob(
        self, collector: ApimPolicyCollector, tmp_path: Path
    ) -> None:
        # File named *policy*.xml outside standard dirs should be found
        subdir = tmp_path / "config"
        subdir.mkdir()
        policy = subdir / "my-api-policy.xml"
        policy.write_text(
            textwrap.dedent("""\
            <policies>
                <inbound><base /></inbound>
                <backend />
                <outbound><base /></outbound>
            </policies>
        """)
        )

        evidence = collector.collect(tmp_path, config=None)
        assert len(evidence) == 1
        assert "my-api-policy" in evidence[0].payload["file_path"]

    def test_duplicate_files_not_double_counted(
        self, collector: ApimPolicyCollector, tmp_path: Path
    ) -> None:
        # A file in policies/ that also matches *policy*.xml should only appear once
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()
        policy = policies_dir / "my-policy.xml"
        policy.write_text(
            textwrap.dedent("""\
            <policies>
                <inbound><base /></inbound>
                <backend />
                <outbound><base /></outbound>
            </policies>
        """)
        )

        evidence = collector.collect(tmp_path, config=None)
        assert len(evidence) == 1
