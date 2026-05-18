"""Tests for PATCH-SCOPE-001 and PATCH-SCOPE-002 patch class scoping rules."""

from __future__ import annotations

from pathlib import Path

from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.models import Evidence
from nfr_review.rules.patch_scope import AcceleratedCadenceRule, PatchClassSoakConfigRule

FIXTURES = Path(__file__).parent / "fixtures"
GOOD_REPO = FIXTURES / "patch-scope-good"
BAD_REPO = FIXTURES / "patch-scope-bad"


def _repo_ev(
    top_level_files: list[str] | None = None,
    top_level_dirs: list[str] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="repo-structure",
        collector_version="0.1.0",
        locator=".",
        kind="repo-structure-summary",
        payload={
            "top_level_files": top_level_files or [],
            "top_level_dirs": top_level_dirs or [],
            "has_readme": True,
            "readme_name": "README.md",
            "has_git_dir": True,
            "has_pyproject": True,
        },
    )


def _patch_config_ev(
    patch_classes: list[dict] | None = None,
    file_path: str = "patch-config.yaml",
) -> Evidence:
    return Evidence(
        collector_name="repo-structure",
        collector_version="0.1.0",
        locator=file_path,
        kind="patch-config",
        payload={
            "file_path": file_path,
            "patch_classes": patch_classes or [],
        },
    )


# ---------------------------------------------------------------------------
# PATCH-SCOPE-001 — Patch class soak configuration detection
# ---------------------------------------------------------------------------


class TestPatchClassSoakConfig:
    def setup_method(self) -> None:
        self.rule = PatchClassSoakConfigRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no repo-structure-summary evidence available"

    def test_no_config_files_info(self) -> None:
        ev = _repo_ev(
            top_level_files=["README.md", "setup.py"],
            top_level_dirs=["src", "tests"],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].severity == "info"
        assert result.findings[0].rag == "green"
        assert "No patch-class soak configuration" in result.findings[0].summary

    def test_patch_config_file_green(self) -> None:
        ev = _repo_ev(top_level_files=["patch-config.yaml"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "patch-config.yaml" in result.findings[0].summary

    def test_patching_policy_file_green(self) -> None:
        ev = _repo_ev(top_level_files=["patching-policy.yml"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert "patching-policy.yml" in result.findings[0].summary

    def test_soak_config_file_green(self) -> None:
        ev = _repo_ev(top_level_files=["soak-config.yaml"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_patch_class_file_green(self) -> None:
        ev = _repo_ev(top_level_files=["patch-classes.yaml"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_patching_config_file_green(self) -> None:
        ev = _repo_ev(top_level_files=["patching_config.yaml"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_patch_config_dir_green(self) -> None:
        ev = _repo_ev(top_level_dirs=["patch-config"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert "patch-config" in result.findings[0].summary

    def test_patching_dir_green(self) -> None:
        ev = _repo_ev(top_level_dirs=["patching"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_case_insensitive_file(self) -> None:
        ev = _repo_ev(top_level_files=["Patch-Config.yaml"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_case_insensitive_dir(self) -> None:
        ev = _repo_ev(top_level_dirs=["Patching-Policy"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_parsed_evidence_with_classes_green(self) -> None:
        repo = _repo_ev()
        parsed = _patch_config_ev(
            patch_classes=[
                {"name": "critical-security", "soak_hours": {"R0": 4, "R1": 8}},
                {"name": "routine", "soak_hours": {"R0": 24, "R1": 48}},
            ]
        )
        result = self.rule.evaluate([repo, parsed], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "2 patch class(es)" in result.findings[0].summary
        assert result.findings[0].confidence == 0.95

    def test_parsed_evidence_empty_classes_amber(self) -> None:
        repo = _repo_ev()
        parsed = _patch_config_ev(patch_classes=[])
        result = self.rule.evaluate([repo, parsed], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "no patch class definitions" in result.findings[0].summary

    def test_parsed_evidence_takes_precedence_over_file_names(self) -> None:
        repo = _repo_ev(top_level_files=["patch-config.yaml"])
        parsed = _patch_config_ev(patch_classes=[{"name": "routine", "soak_hours": [24]}])
        result = self.rule.evaluate([repo, parsed], None)
        assert result.findings[0].confidence == 0.95

    def test_rule_id_and_band(self) -> None:
        assert self.rule.id == "PATCH-SCOPE-001"
        assert self.rule.band == 2
        assert self.rule.required_collectors == ["repo-structure"]


# ---------------------------------------------------------------------------
# PATCH-SCOPE-002 — Accelerated cadence declaration
# ---------------------------------------------------------------------------


class TestAcceleratedCadence:
    def setup_method(self) -> None:
        self.rule = AcceleratedCadenceRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no repo-structure-summary evidence available"

    def test_no_config_files_info(self) -> None:
        ev = _repo_ev(
            top_level_files=["README.md"],
            top_level_dirs=["src"],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].severity == "info"
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary

    def test_config_files_but_no_parsed_evidence_info(self) -> None:
        ev = _repo_ev(top_level_files=["patch-config.yaml"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].severity == "info"
        assert "not parsed" in result.findings[0].summary

    def test_parsed_with_critical_security_green(self) -> None:
        repo = _repo_ev()
        parsed = _patch_config_ev(
            patch_classes=[
                {"name": "critical-security", "soak_hours": {"R0": 4, "R1": 8}},
                {"name": "routine", "soak_hours": {"R0": 24, "R1": 48}},
            ]
        )
        result = self.rule.evaluate([repo, parsed], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "accelerated cadence" in result.findings[0].summary

    def test_parsed_with_critical_security_list_soak_green(self) -> None:
        repo = _repo_ev()
        parsed = _patch_config_ev(
            patch_classes=[
                {"name": "critical-security", "soak_hours": [4, 8, 12]},
            ]
        )
        result = self.rule.evaluate([repo, parsed], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_parsed_without_critical_security_amber(self) -> None:
        repo = _repo_ev()
        parsed = _patch_config_ev(
            patch_classes=[
                {"name": "routine", "soak_hours": {"R0": 24, "R1": 48}},
                {"name": "high-security", "soak_hours": {"R0": 24}},
            ]
        )
        result = self.rule.evaluate([repo, parsed], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "no accelerated cadence" in result.findings[0].summary

    def test_critical_security_with_zero_soak_amber(self) -> None:
        repo = _repo_ev()
        parsed = _patch_config_ev(
            patch_classes=[
                {"name": "critical-security", "soak_hours": {"R0": 0, "R1": 8}},
            ]
        )
        result = self.rule.evaluate([repo, parsed], None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"

    def test_critical_security_no_soak_hours_amber(self) -> None:
        repo = _repo_ev()
        parsed = _patch_config_ev(
            patch_classes=[
                {"name": "critical-security"},
            ]
        )
        result = self.rule.evaluate([repo, parsed], None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"

    def test_parsed_empty_classes_falls_through_to_info(self) -> None:
        repo = _repo_ev()
        parsed = _patch_config_ev(patch_classes=[])
        result = self.rule.evaluate([repo, parsed], None)
        assert not result.skipped
        assert result.findings[0].severity == "info"
        assert result.findings[0].rag == "green"

    def test_critical_name_variants(self) -> None:
        repo = _repo_ev()
        for name in ["critical_security", "critical-sec", "critical", "Critical-Security"]:
            parsed = _patch_config_ev(patch_classes=[{"name": name, "soak_hours": [2, 4]}])
            result = self.rule.evaluate([repo, parsed], None)
            assert result.findings[0].rag == "green", f"Failed for name={name!r}"

    def test_rule_id_and_band(self) -> None:
        assert self.rule.id == "PATCH-SCOPE-002"
        assert self.rule.band == 2
        assert self.rule.required_collectors == ["repo-structure"]


# ---------------------------------------------------------------------------
# Fixture-repo integration tests — collector -> rule pipeline
# ---------------------------------------------------------------------------


def _collect_evidence(repo: Path) -> list[Evidence]:
    collector = RepoStructureCollector()
    return collector.collect(repo, None)


class TestFixtureGoodRepo:
    """patch-scope-good fixture has patching-policy.yaml -> green findings."""

    def test_collector_finds_patching_policy(self) -> None:
        evidence = _collect_evidence(GOOD_REPO)
        assert len(evidence) == 1
        files = evidence[0].payload["top_level_files"]
        assert "patching-policy.yaml" in files

    def test_scope_001_green_with_fixture(self) -> None:
        evidence = _collect_evidence(GOOD_REPO)
        rule = PatchClassSoakConfigRule()
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "patching-policy.yaml" in result.findings[0].summary

    def test_scope_002_info_unparsed_with_fixture(self) -> None:
        evidence = _collect_evidence(GOOD_REPO)
        rule = AcceleratedCadenceRule()
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].severity == "info"
        assert "not parsed" in result.findings[0].summary


class TestFixtureBadRepo:
    """patch-scope-bad fixture has no patching config -> info findings."""

    def test_collector_finds_no_patch_config(self) -> None:
        evidence = _collect_evidence(BAD_REPO)
        assert len(evidence) == 1
        files = evidence[0].payload["top_level_files"]
        assert all(not f.lower().startswith("patch") for f in files)

    def test_scope_001_info_with_fixture(self) -> None:
        evidence = _collect_evidence(BAD_REPO)
        rule = PatchClassSoakConfigRule()
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"
        assert "No patch-class soak configuration" in result.findings[0].summary

    def test_scope_002_info_with_fixture(self) -> None:
        evidence = _collect_evidence(BAD_REPO)
        rule = AcceleratedCadenceRule()
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].severity == "info"
        assert "not applicable" in result.findings[0].summary
