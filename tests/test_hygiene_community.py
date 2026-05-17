"""Tests for community collector and HYG-COM-001 through HYG-COM-006 rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.hygiene import hygiene_collector_registry, hygiene_rule_registry
from nfr_review.hygiene.collectors.community import (
    CommunityCollector,
    _extract_changelog_structure,
    _extract_readme_badges,
    _extract_readme_sections,
)
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
            collector_version="0.3.0",
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
        "readme_sections": {
            "headings": ["Installation", "Usage"],
            "section_count": 2,
            "well_known_sections": ["installation", "usage"],
        },
        "readme_badges": [],
        "contributing": _file_info(True, "CONTRIBUTING.md"),
        "code_of_conduct": _file_info(True, "CODE_OF_CONDUCT.md"),
        "security": _file_info(True, "SECURITY.md"),
        "changelog": _file_info(True, "CHANGELOG.md"),
        "changelog_structure": {
            "has_versions": True,
            "version_count": 3,
            "follows_keep_a_changelog": True,
            "kac_sections_found": ["added", "changed", "fixed"],
            "has_recent_entries": True,
        },
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

    def test_readme_sections_extracted(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text(
            "# My Project\n\n## Installation\n\npip install\n\n"
            "## Usage\n\nhello()\n\n## Contributing\n\nPRs welcome\n"
        )
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]

        sections = ev.payload["readme_sections"]
        assert sections["section_count"] == 4
        assert "My Project" in sections["headings"]
        assert "Installation" in sections["headings"]
        assert "installation" in sections["well_known_sections"]
        assert "usage" in sections["well_known_sections"]
        assert "contributing" in sections["well_known_sections"]

    def test_readme_badges_extracted(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text(
            "# Project\n\n"
            "![CI](https://img.shields.io/badge/build-passing-green)\n"
            "![Coverage](https://codecov.io/gh/org/repo/branch/main/graph/badge.svg)\n"
        )
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]

        badges = ev.payload["readme_badges"]
        assert len(badges) == 2
        assert any("img.shields.io" in b for b in badges)
        assert any("codecov.io" in b for b in badges)

    def test_no_readme_yields_empty_sections_and_badges(self, tmp_path: Path) -> None:
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]

        assert ev.payload["readme_sections"]["section_count"] == 0
        assert ev.payload["readme_sections"]["headings"] == []
        assert ev.payload["readme_sections"]["well_known_sections"] == []
        assert ev.payload["readme_badges"] == []


# ---------------------------------------------------------------------------
# README structure extraction unit tests
# ---------------------------------------------------------------------------


class TestExtractReadmeSections:
    def test_empty_text(self) -> None:
        result = _extract_readme_sections("")
        assert result["section_count"] == 0
        assert result["headings"] == []
        assert result["well_known_sections"] == []

    def test_headings_at_various_levels(self) -> None:
        text = "# Title\n## Installation\n### Sub\n#### Deep\n"
        result = _extract_readme_sections(text)
        assert result["section_count"] == 4
        assert result["headings"] == ["Title", "Installation", "Sub", "Deep"]

    def test_well_known_detection(self) -> None:
        text = (
            "# Readme\n## Installation\n## Usage\n## API Reference\n"
            "## License\n## FAQ\n## Examples\n## Testing\n"
        )
        result = _extract_readme_sections(text)
        wk = result["well_known_sections"]
        assert "installation" in wk
        assert "usage" in wk
        assert "license" in wk
        assert "faq" in wk
        assert "examples" in wk
        assert "testing" in wk

    def test_install_alias(self) -> None:
        text = "## Install\n"
        result = _extract_readme_sections(text)
        assert "install" in result["well_known_sections"]

    def test_non_heading_lines_ignored(self) -> None:
        text = "Hello world\nsome text\n#not a heading\n## Real Heading\n"
        result = _extract_readme_sections(text)
        assert result["section_count"] == 1
        assert result["headings"] == ["Real Heading"]


class TestExtractReadmeBadges:
    def test_no_badges(self) -> None:
        assert _extract_readme_badges("# Hello\n\nNo badges here.\n") == []

    def test_shields_io(self) -> None:
        text = "![badge](https://img.shields.io/badge/foo-bar-blue)\n"
        result = _extract_readme_badges(text)
        assert len(result) == 1
        assert "img.shields.io" in result[0]

    def test_multiple_providers(self) -> None:
        text = (
            "![a](https://img.shields.io/badge/ci-ok-green)\n"
            "![b](https://codecov.io/gh/x/y/badge.svg)\n"
            "![c](https://badgen.net/npm/v/express)\n"
        )
        result = _extract_readme_badges(text)
        assert len(result) == 3

    def test_github_actions_badge(self) -> None:
        text = "![CI](https://github.com/org/repo/actions/workflows/ci.yml/badge.svg)\n"
        result = _extract_readme_badges(text)
        assert len(result) == 1

    def test_regular_images_not_matched(self) -> None:
        text = "![logo](https://example.com/logo.png)\n"
        assert _extract_readme_badges(text) == []


# ---------------------------------------------------------------------------
# Changelog structure extraction unit tests
# ---------------------------------------------------------------------------


class TestExtractChangelogStructure:
    def test_empty_text(self) -> None:
        result = _extract_changelog_structure("")
        assert result["has_versions"] is False
        assert result["version_count"] == 0
        assert result["follows_keep_a_changelog"] is False
        assert result["kac_sections_found"] == []
        assert result["has_recent_entries"] is False

    def test_versioned_headers(self) -> None:
        text = (
            "# Changelog\n\n"
            "## [1.2.0] - 2026-01-15\n\n"
            "### Added\n- feature\n\n"
            "## [1.1.0] - 2025-12-01\n\n"
            "### Fixed\n- bug\n\n"
            "## [1.0.0] - 2024-01-01\n\n"
            "### Added\n- initial\n"
        )
        result = _extract_changelog_structure(text)
        assert result["has_versions"] is True
        assert result["version_count"] == 3
        assert result["has_recent_entries"] is True

    def test_keep_a_changelog_format(self) -> None:
        text = (
            "## [2.0.0] - 2026-04-01\n\n"
            "### Added\n- new feat\n\n"
            "### Changed\n- behavior\n\n"
            "### Fixed\n- bug\n"
        )
        result = _extract_changelog_structure(text)
        assert result["follows_keep_a_changelog"] is True
        assert "added" in result["kac_sections_found"]
        assert "changed" in result["kac_sections_found"]
        assert "fixed" in result["kac_sections_found"]

    def test_not_keep_a_changelog_with_random_sections(self) -> None:
        text = "## [1.0.0] - 2026-03-01\n\n### Stuff\n- thing\n\n### Misc\n- other\n"
        result = _extract_changelog_structure(text)
        assert result["follows_keep_a_changelog"] is False
        assert result["kac_sections_found"] == []

    def test_single_kac_section_not_enough(self) -> None:
        text = "## [1.0.0] - 2026-03-01\n\n### Added\n- feat\n"
        result = _extract_changelog_structure(text)
        assert result["follows_keep_a_changelog"] is False
        assert result["kac_sections_found"] == ["added"]

    def test_no_recent_entries(self) -> None:
        text = (
            "## [1.0.0] - 2020-01-01\n\n"
            "### Added\n- initial\n\n"
            "## [0.9.0] - 2019-06-01\n\n"
            "### Fixed\n- bug\n"
        )
        result = _extract_changelog_structure(text)
        assert result["has_versions"] is True
        assert result["has_recent_entries"] is False

    def test_version_without_date(self) -> None:
        text = "## [1.0.0]\n\n- Some changes\n\n## [0.9.0]\n\n- Other\n"
        result = _extract_changelog_structure(text)
        assert result["has_versions"] is True
        assert result["version_count"] == 2
        assert result["has_recent_entries"] is False

    def test_version_without_brackets(self) -> None:
        text = "## 1.0.0 - 2026-05-01\n\n### Added\n- feat\n### Changed\n- x\n"
        result = _extract_changelog_structure(text)
        assert result["has_versions"] is True
        assert result["version_count"] == 1
        assert result["has_recent_entries"] is True
        assert result["follows_keep_a_changelog"] is True


# ---------------------------------------------------------------------------
# Collector integration — changelog structure
# ---------------------------------------------------------------------------


class TestCollectorChangelogStructure:
    def test_changelog_structure_populated(self, tmp_path: Path) -> None:
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\n"
            "## [1.0.0] - 2026-05-01\n\n"
            "### Added\n- feature\n\n"
            "### Fixed\n- bug\n"
        )
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]

        cs = ev.payload["changelog_structure"]
        assert cs["has_versions"] is True
        assert cs["version_count"] == 1
        assert cs["follows_keep_a_changelog"] is True
        assert cs["has_recent_entries"] is True

    def test_no_changelog_yields_empty_structure(self, tmp_path: Path) -> None:
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]

        cs = ev.payload["changelog_structure"]
        assert cs["has_versions"] is False
        assert cs["version_count"] == 0
        assert cs["follows_keep_a_changelog"] is False
        assert cs["has_recent_entries"] is False

    def test_changelog_with_no_format(self, tmp_path: Path) -> None:
        (tmp_path / "CHANGELOG.md").write_text("Just some text about changes\n")
        collector = CommunityCollector()
        ev = collector.collect(tmp_path, config=None)[0]

        cs = ev.payload["changelog_structure"]
        assert cs["has_versions"] is False
        assert cs["follows_keep_a_changelog"] is False


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
        assert result.findings[0].pattern_tag == "readme-presence"

    def test_red_when_missing(self) -> None:
        payload = _full_payload(readme=_file_info(False))
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"

    def test_amber_when_stub(self) -> None:
        payload = _full_payload(readme=_file_info(True, "README.md", 10))
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert len(result.findings) == 1

    def test_whitespace_only_treated_as_stub(self) -> None:
        payload = _full_payload(readme=_file_info(True, "README.md", 5))
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"

    def test_category_attribute(self) -> None:
        assert ReadmePresenceRule.category == "community"

    def test_missing_required_sections_fires_medium(self) -> None:
        payload = _full_payload(
            readme_sections={
                "headings": ["My Project"],
                "section_count": 1,
                "well_known_sections": [],
            },
        )
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        tags = {f.pattern_tag: f for f in result.findings}
        assert "readme-required-sections" in tags
        assert tags["readme-required-sections"].severity == "medium"
        assert tags["readme-required-sections"].rag == "amber"

    def test_missing_recommended_sections_fires_low(self) -> None:
        payload = _full_payload(
            readme_sections={
                "headings": ["My Project", "Installation", "Usage"],
                "section_count": 3,
                "well_known_sections": ["installation", "usage"],
            },
        )
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        tags = {f.pattern_tag: f for f in result.findings}
        assert "readme-recommended-sections" in tags
        assert tags["readme-recommended-sections"].severity == "low"

    def test_missing_badges_fires_info(self) -> None:
        payload = _full_payload(readme_badges=[])
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        tags = {f.pattern_tag: f for f in result.findings}
        assert "readme-badges" in tags
        assert tags["readme-badges"].severity == "info"

    def test_well_structured_readme_no_section_findings(self) -> None:
        payload = _full_payload(
            readme_sections={
                "headings": ["Project", "Installation", "Usage", "Contributing", "License"],
                "section_count": 5,
                "well_known_sections": [
                    "installation",
                    "usage",
                    "contributing",
                    "license",
                ],
            },
            readme_badges=[
                "![CI](https://img.shields.io/badge/ci-passing-green)",
            ],
        )
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        tags = {f.pattern_tag for f in result.findings}
        assert "readme-presence" in tags
        assert "readme-required-sections" not in tags
        assert "readme-recommended-sections" not in tags
        assert "readme-badges" not in tags

    def test_stub_readme_returns_single_finding(self) -> None:
        payload = _full_payload(readme=_file_info(True, "README.md", 50))
        result = ReadmePresenceRule().evaluate(_make_evidence(payload), context=None)
        assert len(result.findings) == 1
        assert result.findings[0].pattern_tag == "readme-presence"


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
