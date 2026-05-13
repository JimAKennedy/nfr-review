"""Tests for HYG-LIC-003: License header presence rule."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene.rules.lic_headers import LicenseHeaderRule
from nfr_review.models import Evidence


def _make_ev(
    locator: str = "src/app.py",
    copyrights: list[str] | None = None,
    licenses: list[dict[str, Any]] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="license-scan",
        collector_version="0.1.0",
        locator=locator,
        kind="license-scan",
        payload={
            "licenses": licenses or [],
            "copyrights": copyrights or [],
            "holders": [],
            "detected_expression_spdx": None,
        },
    )


class TestRegistration:
    def test_rule_registered(self) -> None:
        import nfr_review.hygiene.rules  # noqa: F401
        from nfr_review.hygiene import hygiene_rule_registry

        assert "HYG-LIC-003" in hygiene_rule_registry


class TestNoEvidence:
    def test_skipped_when_no_evidence(self) -> None:
        rule = LicenseHeaderRule()
        result = rule.evaluate([], None)
        assert result.skipped is True


class TestAllHeaders:
    def test_green_when_all_have_headers(self) -> None:
        ev = _make_ev(
            locator="src/app.py",
            copyrights=["Copyright 2026 Example Corp."],
        )
        rule = LicenseHeaderRule()
        result = rule.evaluate([ev], None)

        assert result.findings[0].rag == "green"

    def test_green_when_license_in_file(self) -> None:
        ev = _make_ev(
            locator="src/app.py",
            licenses=[{"spdx_key": "Apache-2.0", "score": 95.0}],
        )
        rule = LicenseHeaderRule()
        result = rule.evaluate([ev], None)

        assert result.findings[0].rag == "green"


class TestMissingHeaders:
    def test_amber_when_file_missing_header(self) -> None:
        ev = _make_ev(locator="src/no_header.py")
        rule = LicenseHeaderRule()
        result = rule.evaluate([ev], None)

        assert result.findings[0].rag == "amber"
        assert "no_header.py" in result.findings[0].summary

    def test_multiple_missing(self) -> None:
        ev1 = _make_ev(locator="src/a.py")
        ev2 = _make_ev(locator="src/b.py")
        ev3 = _make_ev(
            locator="src/c.py",
            copyrights=["Copyright 2026"],
        )
        rule = LicenseHeaderRule()
        result = rule.evaluate([ev1, ev2, ev3], None)

        assert result.findings[0].rag == "amber"
        assert "2 source file(s)" in result.findings[0].summary


class TestNonSourceFiles:
    def test_non_source_extensions_ignored(self) -> None:
        ev = _make_ev(locator="config.yaml")
        rule = LicenseHeaderRule()
        result = rule.evaluate([ev], None)

        assert result.findings[0].rag == "green"
        assert "No source files" in result.findings[0].summary


class TestMixedFiles:
    def test_only_relevant_extensions_checked(self) -> None:
        py_ev = _make_ev(
            locator="src/mod.py",
            copyrights=["Copyright 2026"],
        )
        yaml_ev = _make_ev(locator="config.yaml")
        rule = LicenseHeaderRule()
        result = rule.evaluate([py_ev, yaml_ev], None)

        assert result.findings[0].rag == "green"
