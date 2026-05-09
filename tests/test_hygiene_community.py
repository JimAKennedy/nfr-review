"""Tests for community collector and HYG-COM-001 through HYG-COM-006 rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.hygiene import hygiene_collector_registry, hygiene_rule_registry
from nfr_review.hygiene.collectors.community import CommunityCollector
from nfr_review.hygiene.rules.com_changelog import ChangelogPresenceRule
from nfr_review.hygiene.rules.com_code_of_conduct import (
    CodeOfConductPresenceRule,
)
from nfr_review.hygiene.rules.com_codeowners import CodeownersPresenceRule
from nfr_review.hygiene.rules.com_contributing import ContributingPresenceRule
from nfr_review.hygiene.rules.com_readme import ReadmePresenceRule
from nfr_review.hygiene.rules.com_security import SecurityPresenceRule
from nfr_review.models import Evidence

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(payload: dict) -> list[Evidence]:
    return [
        Evidence(
            collector_name="community",
            collector_version="0.1.0",
            locator=".",
            kind="community-analysis",
            payload=payload,
        )
    ]


def _file_info(exists: bool, path: str | None = None, size: int = 500) -> dict:
    if exists:
        return {"exists": True, "path": path or "FILE", "size": size}
    return {"exists": False, "path": None, "size": 0}


def _full_payload(**overrides: dict) -> dict:
    base = {
        "readme": _file_info(True, "README.md", 1000),
        "contributing": _file_info(True, "CONTRIBUTING.md"),
        "code_of_conduct": _file_info(True, "CODE_OF_CONDUCT.md"),
        "security": _file_info(True, "SECURITY.md"),
        "changelog": _file_info(True, "CHANGELOG.md"),
        "codeowners": _file_info(True, ".github/CODEOWNERS"),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_collector_registered(self) -> None:
        assert "community" in hygiene_collector_registry

    def test_all_rules_registered(self) -> None:
        for rule_id in [
            "HYG-COM-001",
            "HYG-COM-002",
            "HYG-COM-003",
            "HYG-COM-004",
            "HYG-COM-005",
            "HYG-COM-006",
        ]:
            assert rule_id in hygiene_rule_registry, f"{rule_id} not registered"


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------


class TestCommunityCollector:
    def test_all_files_present(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Hello\n" * 50)
        (tmp_path / "CONTRIBUTING.md").write_text("contribute")
        (tmp_path / "CODE_OF_CONDUCT.md").write_text("be nice")
        (tmp_path / "SECURITY.md").write_text("report vulns")
        (tmp_path / "CHANGELOG.md").write_text("changes")
        github_dir = tmp_path / ".github"
        github_dir.mkdir()
        (github_dir / "CODEOWNERS").write_text("* @team")

        collector = CommunityCollector()
        results = collector.collect(tmp_path, config=None)

        assert len(results) == 1
        ev = results[0]
        assert ev.kind == "community-analysis"
        assert ev.collector_name == "community"

        all_keys = (
            "readme",
            "contributing",
            "code_of_conduct",
            "security",
            "changelog",
            "codeowners",
        )
        for key in all_keys:
            assert ev.payload[key]["exists"] is True
            assert ev.payload[key]["size"] > 0

    def test_empty_directory(self, tmp_path: Path) -> None:
        collector = CommunityCollector()
        results = collector.collect(tmp_path, config=None)

        assert len(results) == 1
        ev = results[0]
        all_keys = (
            "readme",
            "contributing",
            "code_of_conduct",
            "security",
            "changelog",
            "codeowners",
        )
        for key in all_keys:
            assert ev.payload[key]["exists"] is False

    def test_alternate_readme_rst(self, tmp_path: Path) -> None:
        (tmp_path / "README.rst").write_text("title\n=====\n")
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]
        assert ev.payload["readme"]["exists"] is True
        assert ev.payload["readme"]["path"] == "README.rst"

    def test_alternate_security_github(self, tmp_path: Path) -> None:
        github_dir = tmp_path / ".github"
        github_dir.mkdir()
        (github_dir / "SECURITY.md").write_text("policy")
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]
        assert ev.payload["security"]["exists"] is True
        assert ev.payload["security"]["path"] == ".github/SECURITY.md"

    def test_alternate_security_txt(self, tmp_path: Path) -> None:
        (tmp_path / "SECURITY.txt").write_text("policy")
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]
        assert ev.payload["security"]["exists"] is True
        assert ev.payload["security"]["path"] == "SECURITY.txt"

    def test_alternate_changelog_names(self, tmp_path: Path) -> None:
        (tmp_path / "CHANGES.md").write_text("v1")
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]
        assert ev.payload["changelog"]["exists"] is True
        assert ev.payload["changelog"]["path"] == "CHANGES.md"

    def test_alternate_changelog_history(self, tmp_path: Path) -> None:
        (tmp_path / "HISTORY.md").write_text("v1")
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]
        assert ev.payload["changelog"]["exists"] is True
        assert ev.payload["changelog"]["path"] == "HISTORY.md"

    def test_codeowners_root(self, tmp_path: Path) -> None:
        (tmp_path / "CODEOWNERS").write_text("* @team")
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]
        assert ev.payload["codeowners"]["exists"] is True
        assert ev.payload["codeowners"]["path"] == "CODEOWNERS"


# ---------------------------------------------------------------------------
# Rule tests — skip path (no evidence)
# ---------------------------------------------------------------------------


class TestRulesSkipOnNoEvidence:
    @pytest.mark.parametrize(
        "rule_class",
        [
            ReadmePresenceRule,
            ContributingPresenceRule,
            CodeOfConductPresenceRule,
            SecurityPresenceRule,
            ChangelogPresenceRule,
            CodeownersPresenceRule,
        ],
    )
    def test_skip_when_no_evidence(self, rule_class: type) -> None:
        rule = rule_class()
        result = rule.evaluate([], context=None)
        assert result.skipped is True
        assert result.skip_reason is not None


# ---------------------------------------------------------------------------
# HYG-COM-001: README
# ---------------------------------------------------------------------------


class TestReadmeRule:
    def test_green_when_present_and_large(self) -> None:
        evidence = _make_evidence(_full_payload())
        result = ReadmePresenceRule().evaluate(evidence, context=None)
        assert result.findings[0].rag == "green"

    def test_red_when_missing(self) -> None:
        payload = _full_payload(readme=_file_info(False))
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"

    def test_amber_when_stub(self) -> None:
        payload = _full_payload(readme=_file_info(True, "README.md", 10))
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"

    def test_whitespace_only_treated_as_stub(self) -> None:
        payload = _full_payload(readme=_file_info(True, "README.md", 5))
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"

    def test_category_attribute(self) -> None:
        assert ReadmePresenceRule.category == "community"


# ---------------------------------------------------------------------------
# HYG-COM-002: CONTRIBUTING
# ---------------------------------------------------------------------------


class TestContributingRule:
    def test_green_when_present(self) -> None:
        evidence = _make_evidence(_full_payload())
        result = ContributingPresenceRule().evaluate(evidence, context=None)
        assert result.findings[0].rag == "green"

    def test_amber_when_missing(self) -> None:
        payload = _full_payload(contributing=_file_info(False))
        result = ContributingPresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"

    def test_category_attribute(self) -> None:
        assert ContributingPresenceRule.category == "community"


# ---------------------------------------------------------------------------
# HYG-COM-003: CODE_OF_CONDUCT
# ---------------------------------------------------------------------------


class TestCodeOfConductRule:
    def test_green_when_present(self) -> None:
        evidence = _make_evidence(_full_payload())
        result = CodeOfConductPresenceRule().evaluate(evidence, context=None)
        assert result.findings[0].rag == "green"

    def test_amber_when_missing(self) -> None:
        payload = _full_payload(code_of_conduct=_file_info(False))
        result = CodeOfConductPresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"

    def test_category_attribute(self) -> None:
        assert CodeOfConductPresenceRule.category == "community"


# ---------------------------------------------------------------------------
# HYG-COM-004: SECURITY
# ---------------------------------------------------------------------------


class TestSecurityRule:
    def test_green_when_present(self) -> None:
        evidence = _make_evidence(_full_payload())
        result = SecurityPresenceRule().evaluate(evidence, context=None)
        assert result.findings[0].rag == "green"

    def test_red_when_missing(self) -> None:
        payload = _full_payload(security=_file_info(False))
        result = SecurityPresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"

    def test_category_attribute(self) -> None:
        assert SecurityPresenceRule.category == "community"


# ---------------------------------------------------------------------------
# HYG-COM-005: CHANGELOG
# ---------------------------------------------------------------------------


class TestChangelogRule:
    def test_green_when_present(self) -> None:
        evidence = _make_evidence(_full_payload())
        result = ChangelogPresenceRule().evaluate(evidence, context=None)
        assert result.findings[0].rag == "green"

    def test_amber_when_missing(self) -> None:
        payload = _full_payload(changelog=_file_info(False))
        result = ChangelogPresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"

    def test_category_attribute(self) -> None:
        assert ChangelogPresenceRule.category == "community"


# ---------------------------------------------------------------------------
# HYG-COM-006: CODEOWNERS
# ---------------------------------------------------------------------------


class TestCodeownersRule:
    def test_green_when_present(self) -> None:
        evidence = _make_evidence(_full_payload())
        result = CodeownersPresenceRule().evaluate(evidence, context=None)
        assert result.findings[0].rag == "green"

    def test_amber_when_missing(self) -> None:
        payload = _full_payload(codeowners=_file_info(False))
        result = CodeownersPresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"

    def test_category_attribute(self) -> None:
        assert CodeownersPresenceRule.category == "community"


# ---------------------------------------------------------------------------
# Negative tests — empty directory scenario through rules
# ---------------------------------------------------------------------------


class TestNegativeEmptyDirectory:
    """All rules produce red or amber when given evidence from an empty directory."""

    @pytest.fixture()
    def empty_evidence(self) -> list[Evidence]:
        payload = {
            "readme": _file_info(False),
            "contributing": _file_info(False),
            "code_of_conduct": _file_info(False),
            "security": _file_info(False),
            "changelog": _file_info(False),
            "codeowners": _file_info(False),
        }
        return _make_evidence(payload)

    def test_readme_red(self, empty_evidence: list[Evidence]) -> None:
        result = ReadmePresenceRule().evaluate(empty_evidence, context=None)
        assert result.findings[0].rag == "red"

    def test_contributing_amber(self, empty_evidence: list[Evidence]) -> None:
        result = ContributingPresenceRule().evaluate(empty_evidence, context=None)
        assert result.findings[0].rag == "amber"

    def test_code_of_conduct_amber(self, empty_evidence: list[Evidence]) -> None:
        result = CodeOfConductPresenceRule().evaluate(empty_evidence, context=None)
        assert result.findings[0].rag == "amber"

    def test_security_red(self, empty_evidence: list[Evidence]) -> None:
        result = SecurityPresenceRule().evaluate(empty_evidence, context=None)
        assert result.findings[0].rag == "red"

    def test_changelog_amber(self, empty_evidence: list[Evidence]) -> None:
        result = ChangelogPresenceRule().evaluate(empty_evidence, context=None)
        assert result.findings[0].rag == "amber"

    def test_codeowners_amber(self, empty_evidence: list[Evidence]) -> None:
        result = CodeownersPresenceRule().evaluate(empty_evidence, context=None)
        assert result.findings[0].rag == "amber"
