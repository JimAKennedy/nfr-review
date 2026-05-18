"""Tests for build-readiness collector and HYG-BLD-001 through HYG-BLD-005 rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_collector_registry, hygiene_rule_registry
from nfr_review.hygiene.collectors.build_readiness import BuildReadinessCollector
from nfr_review.hygiene.rules.bld_build_system import BuildSystemRule
from nfr_review.hygiene.rules.bld_entry_points import EntryPointsRule
from nfr_review.hygiene.rules.bld_pre_commit import PreCommitRule
from nfr_review.hygiene.rules.bld_version_strategy import VersionStrategyRule
from nfr_review.models import Evidence

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(payload: dict[str, Any]) -> list[Evidence]:
    return [
        Evidence(
            collector_name="build-readiness",
            collector_version="0.1.0",
            locator=".",
            kind="build-readiness-analysis",
            payload=payload,
        )
    ]


def _build_payload(
    *,
    has_build_system: bool = True,
    backend: str | None = "hatchling",
    build_path: str | None = "pyproject.toml",
    version_declared: bool = True,
    version_value: str | None = "1.0.0",
    version_source: str | None = "pyproject.toml",
    has_entry_points: bool = True,
    scripts: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "build_system": {
            "has_build_system": has_build_system,
            "backend": backend,
            "path": build_path,
        },
        "version": {
            "declared": version_declared,
            "value": version_value,
            "source": version_source,
        },
        "entry_points": {
            "has_entry_points": has_entry_points,
            "scripts": scripts or ({"my-cli": "mypackage:main"} if has_entry_points else {}),
        },
    }


_MINIMAL_PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sample"
version = "1.2.3"

[project.scripts]
sample-cli = "sample:main"
"""

_NO_BUILD_SYSTEM_PYPROJECT = """\
[project]
name = "sample"
version = "0.1.0"
"""

_NO_VERSION_PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sample"
"""

_DYNAMIC_VERSION_PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sample"
dynamic = ["version"]
"""

_NO_ENTRY_POINTS_PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sample"
version = "1.0.0"
"""

_MALFORMED_TOML = "this is [not valid toml ={{{"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_collector_registered(self) -> None:
        assert "build-readiness" in hygiene_collector_registry

    def test_all_rules_registered(self) -> None:
        for rule_id in ["HYG-BLD-001", "HYG-BLD-002", "HYG-BLD-003"]:
            assert rule_id in hygiene_rule_registry, f"{rule_id} not registered"

    def test_collector_name_and_version(self) -> None:
        c = BuildReadinessCollector()
        assert c.name == "build-readiness"
        assert c.version == "0.1.0"

    def test_rule_categories(self) -> None:
        assert BuildSystemRule.category == "build-readiness"
        assert VersionStrategyRule.category == "build-readiness"
        assert EntryPointsRule.category == "build-readiness"

    def test_rule_bands(self) -> None:
        assert BuildSystemRule.band == 1
        assert VersionStrategyRule.band == 1
        assert EntryPointsRule.band == 1

    def test_rule_required_collectors(self) -> None:
        assert BuildSystemRule.required_collectors == ["build-readiness"]
        assert VersionStrategyRule.required_collectors == ["build-readiness"]
        assert EntryPointsRule.required_collectors == ["build-readiness"]


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------


class TestCollector:
    def test_full_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        assert len(results) == 1
        ev = results[0]
        assert ev.kind == "build-readiness-analysis"
        assert ev.collector_name == "build-readiness"
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "hatchling.build"
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "1.2.3"
        assert ev.payload["entry_points"]["has_entry_points"] is True
        assert "sample-cli" in ev.payload["entry_points"]["scripts"]

    def test_no_pyproject_no_setup(self, tmp_path: Path) -> None:
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is False
        assert ev.payload["version"]["declared"] is False
        assert ev.payload["entry_points"]["has_entry_points"] is False

    def test_setup_py_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text(
            'from setuptools import setup\nsetup(name="pkg", version="2.0.0")\n'
        )
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert "setup.py" in ev.payload["build_system"]["backend"]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "2.0.0"

    def test_setup_cfg_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "setup.cfg").write_text("[metadata]\nname = pkg\nversion = 3.0.0\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert "setup.cfg" in ev.payload["build_system"]["backend"]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "3.0.0"

    def test_pyproject_without_build_system(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_NO_BUILD_SYSTEM_PYPROJECT)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is False
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "0.1.0"

    def test_pyproject_without_version(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_NO_VERSION_PYPROJECT)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is False

    def test_dynamic_version(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_DYNAMIC_VERSION_PYPROJECT)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "(dynamic)"
        assert "dynamic" in ev.payload["version"]["source"]

    def test_version_from_init_py(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "mypkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text('__version__ = "4.5.6"\n')
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "4.5.6"

    def test_version_from_toplevel_init_py(self, tmp_path: Path) -> None:
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("__version__ = '0.9.0'\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "0.9.0"

    def test_malformed_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_MALFORMED_TOML)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is False
        assert ev.payload["version"]["declared"] is False

    def test_entry_points_from_setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text('setup(console_scripts=["cli=pkg:main"])\n')
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["entry_points"]["has_entry_points"] is True

    def test_no_entry_points(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_NO_ENTRY_POINTS_PYPROJECT)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["entry_points"]["has_entry_points"] is False

    def test_gui_scripts(self, tmp_path: Path) -> None:
        toml = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sample"
version = "1.0.0"

[project.gui-scripts]
my-gui = "sample:gui_main"
"""
        (tmp_path / "pyproject.toml").write_text(toml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["entry_points"]["has_entry_points"] is True
        assert "my-gui" in ev.payload["entry_points"]["scripts"]

    def test_empty_directory(self, tmp_path: Path) -> None:
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        assert len(results) == 1
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is False
        assert ev.payload["version"]["declared"] is False
        assert ev.payload["entry_points"]["has_entry_points"] is False

    def test_pyproject_priority_over_setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        (tmp_path / "setup.py").write_text(
            'from setuptools import setup\nsetup(name="pkg", version="0.0.1")\n'
        )
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "hatchling.build"
        assert ev.payload["version"]["value"] == "1.2.3"


# ---------------------------------------------------------------------------
# HYG-BLD-001: Build System Presence
# ---------------------------------------------------------------------------


class TestBuildSystemRule:
    def test_green_when_build_system_present(self) -> None:
        rule = BuildSystemRule()
        payload = _build_payload()
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_red_when_no_build_system(self) -> None:
        rule = BuildSystemRule()
        payload = _build_payload(has_build_system=False, backend=None, build_path=None)
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"

    def test_skip_when_no_evidence(self) -> None:
        rule = BuildSystemRule()
        result = rule.evaluate([], context=None)
        assert result.skipped
        assert "no build-readiness-analysis" in (result.skip_reason or "")

    def test_skip_with_wrong_evidence_kind(self) -> None:
        rule = BuildSystemRule()
        ev = [
            Evidence(
                collector_name="other",
                collector_version="0.1.0",
                locator=".",
                kind="other-analysis",
                payload={},
            )
        ]
        result = rule.evaluate(ev, context=None)
        assert result.skipped

    def test_green_includes_backend_info(self) -> None:
        rule = BuildSystemRule()
        payload = _build_payload(backend="flit_core.buildapi")
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert "flit_core.buildapi" in result.findings[0].summary

    def test_red_recommendation_mentions_pyproject(self) -> None:
        rule = BuildSystemRule()
        payload = _build_payload(has_build_system=False, backend=None, build_path=None)
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert "pyproject.toml" in result.findings[0].recommendation

    def test_finding_metadata(self) -> None:
        rule = BuildSystemRule()
        payload = _build_payload()
        result = rule.evaluate(_make_evidence(payload), context=None)
        f = result.findings[0]
        assert f.rule_id == "HYG-BLD-001"
        assert f.collector_name == "build-readiness"
        assert f.confidence == 1.0
        assert f.pattern_tag == "build-system-presence"


# ---------------------------------------------------------------------------
# HYG-BLD-002: Version Strategy
# ---------------------------------------------------------------------------


class TestVersionStrategyRule:
    def test_green_when_version_declared(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload()
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "green"

    def test_amber_when_no_version(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload(
            version_declared=False,
            version_value=None,
            version_source=None,
        )
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"

    def test_skip_when_no_evidence(self) -> None:
        rule = VersionStrategyRule()
        result = rule.evaluate([], context=None)
        assert result.skipped

    def test_green_includes_version_value(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload(version_value="2.3.4", version_source="pyproject.toml")
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert "2.3.4" in result.findings[0].summary

    def test_amber_recommendation_mentions_pyproject(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload(
            version_declared=False,
            version_value=None,
            version_source=None,
        )
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert "pyproject.toml" in result.findings[0].recommendation

    def test_finding_metadata(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload()
        result = rule.evaluate(_make_evidence(payload), context=None)
        f = result.findings[0]
        assert f.rule_id == "HYG-BLD-002"
        assert f.pattern_tag == "version-strategy"

    def test_green_for_valid_semver(self) -> None:
        rule = VersionStrategyRule()
        for ver in ["1.2.3", "0.1.0", "10.20.30"]:
            payload = _build_payload(version_value=ver)
            result = rule.evaluate(_make_evidence(payload), context=None)
            assert result.findings[0].rag == "green", f"Expected green for {ver}"

    def test_green_for_semver_with_prerelease(self) -> None:
        rule = VersionStrategyRule()
        for ver in ["0.1.0-alpha", "1.0.0-beta.1", "2.0.0-rc.1"]:
            payload = _build_payload(version_value=ver)
            result = rule.evaluate(_make_evidence(payload), context=None)
            assert result.findings[0].rag == "green", f"Expected green for {ver}"

    def test_amber_for_non_semver_date_based(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload(version_value="2026.05")
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "low"
        assert "Semantic Versioning" in result.findings[0].summary

    def test_amber_for_non_semver_single_number(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload(version_value="v1")
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"

    def test_amber_for_non_semver_text(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload(version_value="abc")
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"

    def test_amber_for_two_part_version(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload(version_value="1.0")
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"

    def test_semver_recommendation_includes_link(self) -> None:
        rule = VersionStrategyRule()
        payload = _build_payload(version_value="bad")
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert "semver.org" in result.findings[0].recommendation


# ---------------------------------------------------------------------------
# HYG-BLD-003: Entry Points
# ---------------------------------------------------------------------------


class TestEntryPointsRule:
    def test_green_when_entry_points_present(self) -> None:
        rule = EntryPointsRule()
        payload = _build_payload()
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "green"

    def test_amber_when_no_entry_points(self) -> None:
        rule = EntryPointsRule()
        payload = _build_payload(has_entry_points=False, scripts=None)
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"

    def test_skip_when_no_evidence(self) -> None:
        rule = EntryPointsRule()
        result = rule.evaluate([], context=None)
        assert result.skipped

    def test_info_skip_when_no_build_system(self) -> None:
        rule = EntryPointsRule()
        payload = _build_payload(
            has_build_system=False,
            backend=None,
            build_path=None,
            has_entry_points=False,
            scripts=None,
        )
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"
        assert "not applicable" in result.findings[0].summary.lower()

    def test_green_includes_count(self) -> None:
        rule = EntryPointsRule()
        scripts = {"cli1": "pkg:main1", "cli2": "pkg:main2"}
        payload = _build_payload(scripts=scripts)
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert "2" in result.findings[0].summary

    def test_amber_recommendation_mentions_scripts(self) -> None:
        rule = EntryPointsRule()
        payload = _build_payload(has_entry_points=False, scripts=None)
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert "project.scripts" in result.findings[0].recommendation

    def test_finding_metadata(self) -> None:
        rule = EntryPointsRule()
        payload = _build_payload()
        result = rule.evaluate(_make_evidence(payload), context=None)
        f = result.findings[0]
        assert f.rule_id == "HYG-BLD-003"
        assert f.pattern_tag == "entry-points"


# ---------------------------------------------------------------------------
# Negative / Edge cases
# ---------------------------------------------------------------------------


class TestNegativeCases:
    def test_malformed_toml_collector_no_crash(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_MALFORMED_TOML)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        assert len(results) == 1
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is False
        assert ev.payload["version"]["declared"] is False
        assert ev.payload["entry_points"]["has_entry_points"] is False

    def test_missing_all_files(self, tmp_path: Path) -> None:
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is False

    def test_pyproject_without_project_section(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[build-system]\nrequires = ['hatchling']\nbuild-backend = 'hatchling.build'\n"
        )
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["version"]["declared"] is False
        assert ev.payload["entry_points"]["has_entry_points"] is False

    def test_empty_dir_rule_bld001_red(self, tmp_path: Path) -> None:
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "red"

    def test_empty_dir_rule_bld002_amber(self, tmp_path: Path) -> None:
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "amber"

    def test_empty_dir_rule_bld003_info_skip(self, tmp_path: Path) -> None:
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = EntryPointsRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"

    def test_empty_payload_keys(self) -> None:
        rule = BuildSystemRule()
        result = rule.evaluate(_make_evidence({}), context=None)
        assert result.findings[0].rag == "red"

    def test_version_empty_payload(self) -> None:
        rule = VersionStrategyRule()
        result = rule.evaluate(_make_evidence({}), context=None)
        assert result.findings[0].rag == "amber"

    def test_entry_points_empty_payload_no_build(self) -> None:
        rule = EntryPointsRule()
        result = rule.evaluate(_make_evidence({}), context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"


# ---------------------------------------------------------------------------
# Polyglot Build System Detection
# ---------------------------------------------------------------------------


class TestPolyglotBuildSystem:
    """Tests for Maven, Gradle, Go, Rust, and .NET detection."""

    def test_maven_detected(self, tmp_path: Path) -> None:
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>1.0.0</version>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "maven"
        assert ev.payload["build_system"]["path"] == "pom.xml"

    def test_maven_invalid_xml_not_detected(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text("this is not valid xml <<< >>>")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is False

    def test_gradle_groovy_detected(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "gradle"
        assert ev.payload["build_system"]["path"] == "build.gradle"

    def test_gradle_kotlin_detected(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle.kts").write_text('plugins { id("java") }\n')
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "gradle"
        assert ev.payload["build_system"]["path"] == "build.gradle.kts"

    def test_go_detected(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "go"
        assert ev.payload["build_system"]["path"] == "go.mod"

    def test_rust_detected(self, tmp_path: Path) -> None:
        cargo_toml = """\
[package]
name = "myapp"
version = "0.1.0"
edition = "2021"
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "cargo"
        assert ev.payload["build_system"]["path"] == "Cargo.toml"

    def test_dotnet_csproj_detected(self, tmp_path: Path) -> None:
        csproj = """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
  </PropertyGroup>
</Project>
"""
        (tmp_path / "MyApp.csproj").write_text(csproj)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "dotnet"
        assert ev.payload["build_system"]["path"] == "MyApp.csproj"

    def test_dotnet_sln_detected(self, tmp_path: Path) -> None:
        (tmp_path / "MyApp.sln").write_text("Microsoft Visual Studio Solution File\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "dotnet"
        assert ev.payload["build_system"]["path"] == "MyApp.sln"

    def test_python_pyproject_wins_over_pom_xml(self, tmp_path: Path) -> None:
        """Python pyproject.toml takes priority over pom.xml when both exist."""
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>1.0.0</version>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "hatchling.build"
        assert ev.payload["build_system"]["path"] == "pyproject.toml"


# ---------------------------------------------------------------------------
# Polyglot Version Detection
# ---------------------------------------------------------------------------


class TestPolyglotVersion:
    """Tests for version extraction from Maven, Gradle, Rust, .NET, and Go."""

    def test_maven_with_namespace_extracts_version(self, tmp_path: Path) -> None:
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>2.5.1</version>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "2.5.1"
        assert ev.payload["version"]["source"] == "pom.xml"

    def test_maven_without_namespace_extracts_version(self, tmp_path: Path) -> None:
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>1.0.0-SNAPSHOT</version>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "1.0.0-SNAPSHOT"
        assert ev.payload["version"]["source"] == "pom.xml"

    def test_maven_no_version_tag(self, tmp_path: Path) -> None:
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        # Maven detected as build system but no version declared
        assert ev.payload["version"]["declared"] is False
        assert ev.payload["version"]["value"] is None

    def test_gradle_build_gradle_extracts_version(self, tmp_path: Path) -> None:
        gradle_content = """\
plugins {
    id 'java'
}

group = 'com.example'
version = '3.2.1'

repositories {
    mavenCentral()
}
"""
        (tmp_path / "build.gradle").write_text(gradle_content)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "3.2.1"
        assert ev.payload["version"]["source"] == "build.gradle"

    def test_gradle_kts_extracts_version(self, tmp_path: Path) -> None:
        gradle_content = """\
plugins {
    id("java")
}

group = "com.example"
version = "4.0.0-beta"

repositories {
    mavenCentral()
}
"""
        (tmp_path / "build.gradle.kts").write_text(gradle_content)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "4.0.0-beta"
        assert ev.payload["version"]["source"] == "build.gradle.kts"

    def test_gradle_no_version_returns_not_declared(self, tmp_path: Path) -> None:
        gradle_content = """\
plugins {
    id 'java'
}

group = 'com.example'

repositories {
    mavenCentral()
}
"""
        (tmp_path / "build.gradle").write_text(gradle_content)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is False

    def test_cargo_toml_extracts_version(self, tmp_path: Path) -> None:
        cargo_toml = """\
[package]
name = "myapp"
version = "0.3.7"
edition = "2021"

[dependencies]
serde = "1.0"
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "0.3.7"
        assert ev.payload["version"]["source"] == "Cargo.toml"

    def test_cargo_toml_no_version_returns_not_declared(self, tmp_path: Path) -> None:
        cargo_toml = """\
[package]
name = "myapp"
edition = "2021"

[dependencies]
serde = "1.0"
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is False

    def test_csproj_extracts_version(self, tmp_path: Path) -> None:
        csproj = """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Version>5.1.0</Version>
  </PropertyGroup>
</Project>
"""
        (tmp_path / "MyApp.csproj").write_text(csproj)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "5.1.0"
        assert ev.payload["version"]["source"] == "MyApp.csproj"

    def test_csproj_assembly_version_fallback(self, tmp_path: Path) -> None:
        csproj = """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <AssemblyVersion>2.0.0.0</AssemblyVersion>
  </PropertyGroup>
</Project>
"""
        (tmp_path / "MyLib.csproj").write_text(csproj)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "2.0.0.0"
        assert ev.payload["version"]["source"] == "MyLib.csproj"

    def test_csproj_no_version_returns_not_declared(self, tmp_path: Path) -> None:
        csproj = """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
  </PropertyGroup>
</Project>
"""
        (tmp_path / "MyApp.csproj").write_text(csproj)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is False

    def test_go_mod_returns_git_tags(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "(git-tags)"
        assert ev.payload["version"]["source"] == "go.mod"

    def test_python_version_takes_priority_over_polyglot(self, tmp_path: Path) -> None:
        """When pyproject.toml and Cargo.toml both exist, Python version wins."""
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        cargo_toml = """\
[package]
name = "myapp"
version = "0.3.7"
edition = "2021"
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["version"]["declared"] is True
        assert ev.payload["version"]["value"] == "1.2.3"
        assert ev.payload["version"]["source"] == "pyproject.toml"


# ---------------------------------------------------------------------------
# Priority Ordering
# ---------------------------------------------------------------------------


class TestPolyglotPriorityOrdering:
    """Verify that when multiple build systems coexist, priority order is correct.

    Priority: Python (pyproject.toml) > setup.py > setup.cfg >
    Maven > Gradle > Go > Rust > .NET
    """

    def test_maven_wins_over_gradle(self, tmp_path: Path) -> None:
        """When both pom.xml and build.gradle exist, Maven wins."""
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>2.0.0</version>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'\nversion = '1.0.0'\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "maven"
        assert ev.payload["build_system"]["path"] == "pom.xml"

    def test_go_wins_over_rust(self, tmp_path: Path) -> None:
        """When both go.mod and Cargo.toml exist, Go wins."""
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        cargo_toml = """\
[package]
name = "myapp"
version = "0.1.0"
edition = "2021"
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "go"
        assert ev.payload["build_system"]["path"] == "go.mod"

    def test_gradle_wins_over_go(self, tmp_path: Path) -> None:
        """When both build.gradle and go.mod exist, Gradle wins."""
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'\n")
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "gradle"
        assert ev.payload["build_system"]["path"] == "build.gradle"

    def test_rust_wins_over_dotnet(self, tmp_path: Path) -> None:
        """When both Cargo.toml and .csproj exist, Rust wins."""
        cargo_toml = """\
[package]
name = "myapp"
version = "0.1.0"
edition = "2021"
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        csproj = """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
  </PropertyGroup>
</Project>
"""
        (tmp_path / "MyApp.csproj").write_text(csproj)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "cargo"
        assert ev.payload["build_system"]["path"] == "Cargo.toml"

    def test_maven_wins_over_go_and_dotnet(self, tmp_path: Path) -> None:
        """Maven > Go > .NET — Maven should win."""
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>1.0.0</version>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        (tmp_path / "MyApp.csproj").write_text("<Project></Project>\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "maven"


# ---------------------------------------------------------------------------
# BLD-001 Rule Evaluation for Polyglot Ecosystems
# ---------------------------------------------------------------------------


class TestPolyglotBLD001RuleEvaluation:
    """BLD-001 rule evaluation for non-Python ecosystems."""

    def test_maven_bld001_green_with_maven_in_summary(self, tmp_path: Path) -> None:
        """Maven pom.xml produces BLD-001 green with 'maven' in summary."""
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>1.0.0</version>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "maven" in result.findings[0].summary.lower()

    def test_go_bld001_green_with_go_in_summary(self, tmp_path: Path) -> None:
        """Go go.mod produces BLD-001 green with 'go' in summary."""
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "go" in result.findings[0].summary.lower()

    def test_gradle_bld001_green_with_gradle_in_summary(self, tmp_path: Path) -> None:
        """Gradle build.gradle produces BLD-001 green with 'gradle' in summary."""
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'\n")
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "gradle" in result.findings[0].summary.lower()

    def test_rust_bld001_green_with_cargo_in_summary(self, tmp_path: Path) -> None:
        """Rust Cargo.toml produces BLD-001 green with 'cargo' in summary."""
        cargo_toml = """\
[package]
name = "myapp"
version = "0.1.0"
edition = "2021"
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "cargo" in result.findings[0].summary.lower()

    def test_dotnet_bld001_green_with_dotnet_in_summary(self, tmp_path: Path) -> None:
        """.NET csproj produces BLD-001 green with 'dotnet' in summary."""
        csproj = """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
  </PropertyGroup>
</Project>
"""
        (tmp_path / "MyApp.csproj").write_text(csproj)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "dotnet" in result.findings[0].summary.lower()

    def test_no_build_files_bld001_red(self, tmp_path: Path) -> None:
        """No recognized build files produces BLD-001 red."""
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "red"


# ---------------------------------------------------------------------------
# BLD-002 Rule Evaluation for Polyglot Ecosystems
# ---------------------------------------------------------------------------


class TestPolyglotBLD002RuleEvaluation:
    """BLD-002 rule evaluation for version extraction across ecosystems."""

    def test_maven_version_bld002_green(self, tmp_path: Path) -> None:
        """Maven with version → BLD-002 green."""
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>3.1.0</version>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "3.1.0" in result.findings[0].summary

    def test_gradle_version_bld002_green_with_value(self, tmp_path: Path) -> None:
        """Gradle with version → BLD-002 green with version value in summary."""
        gradle_content = """\
plugins {
    id 'java'
}
version = '2.4.0'
"""
        (tmp_path / "build.gradle").write_text(gradle_content)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "2.4.0" in result.findings[0].summary

    def test_go_git_tags_bld002_green(self, tmp_path: Path) -> None:
        """Go (git-tags) → BLD-002 green with '(git-tags)' in summary."""
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "(git-tags)" in result.findings[0].summary

    def test_rust_version_bld002_green(self, tmp_path: Path) -> None:
        """Rust Cargo.toml with version → BLD-002 green."""
        cargo_toml = """\
[package]
name = "myapp"
version = "1.2.3"
edition = "2021"
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "1.2.3" in result.findings[0].summary

    def test_dotnet_version_bld002_green(self, tmp_path: Path) -> None:
        """.NET csproj with Version → BLD-002 green."""
        csproj = """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Version>6.0.1</Version>
  </PropertyGroup>
</Project>
"""
        (tmp_path / "MyApp.csproj").write_text(csproj)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "6.0.1" in result.findings[0].summary

    def test_no_version_anywhere_bld002_amber(self, tmp_path: Path) -> None:
        """No version anywhere → BLD-002 amber."""
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'\n")
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "amber"


# ---------------------------------------------------------------------------
# Python Regression Guards
# ---------------------------------------------------------------------------


class TestPythonRegressionGuards:
    """Explicitly verify Python detection still works after polyglot additions."""

    def test_pyproject_hatchling_still_green(self, tmp_path: Path) -> None:
        """pyproject.toml with hatchling → BLD-001 still green."""
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "hatchling" in result.findings[0].summary.lower()

    def test_setup_py_with_version_still_detected(self, tmp_path: Path) -> None:
        """setup.py with version → still detected for both BLD-001 and BLD-002."""
        (tmp_path / "setup.py").write_text(
            'from setuptools import setup\nsetup(name="pkg", version="2.0.0")\n'
        )
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)

        bld001 = BuildSystemRule()
        result_001 = bld001.evaluate(ev_list, context=None)
        assert result_001.findings[0].rag == "green"
        assert "setup.py" in result_001.findings[0].summary.lower()

        bld002 = VersionStrategyRule()
        result_002 = bld002.evaluate(ev_list, context=None)
        assert result_002.findings[0].rag == "green"
        assert "2.0.0" in result_002.findings[0].summary

    def test_dynamic_version_still_detected(self, tmp_path: Path) -> None:
        """Dynamic version in pyproject.toml → BLD-002 green with (dynamic)."""
        (tmp_path / "pyproject.toml").write_text(_DYNAMIC_VERSION_PYPROJECT)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "(dynamic)" in result.findings[0].summary

    def test_pyproject_wins_over_all_polyglot(self, tmp_path: Path) -> None:
        """Python pyproject.toml takes priority over all polyglot alternatives."""
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        cargo_toml = """\
[package]
name = "myapp"
version = "0.9.9"
edition = "2021"
"""
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        ev = ev_list[0]
        # Build system → Python wins
        assert ev.payload["build_system"]["backend"] == "hatchling.build"
        # Version → Python version wins
        assert ev.payload["version"]["value"] == "1.2.3"
        assert ev.payload["version"]["source"] == "pyproject.toml"

    def test_setup_cfg_version_still_works(self, tmp_path: Path) -> None:
        """setup.cfg with version → BLD-002 green."""
        (tmp_path / "setup.cfg").write_text("[metadata]\nname = pkg\nversion = 3.0.0\n")
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "3.0.0" in result.findings[0].summary


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestPolyglotEdgeCases:
    """Edge cases for polyglot detection."""

    def test_pom_and_cargo_present_maven_wins(self, tmp_path: Path) -> None:
        """Both pom.xml and Cargo.toml present — Maven wins for build, Maven version used."""
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>7.0.0</version>
</project>
"""
        cargo_toml = """\
[package]
name = "myapp"
version = "0.1.0"
edition = "2021"
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        # Build system: Maven wins
        assert ev.payload["build_system"]["backend"] == "maven"
        assert ev.payload["build_system"]["path"] == "pom.xml"
        # Version: Maven version used (appears first in detection order)
        assert ev.payload["version"]["value"] == "7.0.0"
        assert ev.payload["version"]["source"] == "pom.xml"

    def test_empty_cargo_toml_no_package_section(self, tmp_path: Path) -> None:
        """Cargo.toml without [package] section is still detected as Rust."""
        # Note: _detect_build_system only checks if Cargo.toml exists, not its content
        (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1.0"\n')
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        # Build system still detected (file presence is enough)
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "cargo"
        # But version is NOT extracted (no [package].version)
        assert ev.payload["version"]["declared"] is False

    def test_gradle_kts_wins_over_groovy_gradle(self, tmp_path: Path) -> None:
        """build.gradle.kts takes priority over build.gradle."""
        (tmp_path / "build.gradle.kts").write_text('version = "2.0.0"\n')
        (tmp_path / "build.gradle").write_text("version = '1.0.0'\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["path"] == "build.gradle.kts"

    def test_invalid_xml_pom_falls_through_to_next(self, tmp_path: Path) -> None:
        """Invalid XML pom.xml is skipped, detection falls through to next system."""
        (tmp_path / "pom.xml").write_text("not valid xml <<<>>>")
        (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        # Invalid pom.xml skipped, Go detected instead
        assert ev.payload["build_system"]["backend"] == "go"
        assert ev.payload["build_system"]["path"] == "go.mod"

    def test_sln_detected_when_no_csproj(self, tmp_path: Path) -> None:
        """.sln is detected even without .csproj."""
        (tmp_path / "Solution.sln").write_text("Microsoft Visual Studio Solution File\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "dotnet"
        assert ev.payload["build_system"]["path"] == "Solution.sln"

    def test_maven_snapshot_version_detected(self, tmp_path: Path) -> None:
        """Maven SNAPSHOT version is properly extracted via BLD-002."""
        pom_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>myapp</artifactId>
  <version>1.0.0-SNAPSHOT</version>
</project>
"""
        (tmp_path / "pom.xml").write_text(pom_xml)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "1.0.0-SNAPSHOT" in result.findings[0].summary


# ---------------------------------------------------------------------------
# Pre-commit / Git Hooks Detection
# ---------------------------------------------------------------------------


class TestPreCommitDetection:
    """Tests for _detect_pre_commit in build-readiness collector."""

    def test_pre_commit_config_yaml(self, tmp_path: Path) -> None:
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["pre_commit"]["has_pre_commit"] is True
        assert ev.payload["pre_commit"]["pre_commit_tool"] == "pre-commit"

    def test_husky_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".husky").mkdir()
        (tmp_path / ".husky" / "pre-commit").write_text("#!/bin/sh\nnpx lint-staged\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["pre_commit"]["has_pre_commit"] is True
        assert ev.payload["pre_commit"]["pre_commit_tool"] == "husky"

    def test_lefthook_yml(self, tmp_path: Path) -> None:
        (tmp_path / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["pre_commit"]["has_pre_commit"] is True
        assert ev.payload["pre_commit"]["pre_commit_tool"] == "lefthook"

    def test_lefthook_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "lefthook.yaml").write_text("pre-commit:\n  commands: {}\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["pre_commit"]["has_pre_commit"] is True
        assert ev.payload["pre_commit"]["pre_commit_tool"] == "lefthook"

    def test_lint_staged_in_package_json(self, tmp_path: Path) -> None:
        import json

        pkg = {"name": "myapp", "lint-staged": {"*.js": ["eslint --fix"]}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["pre_commit"]["has_pre_commit"] is True
        assert ev.payload["pre_commit"]["pre_commit_tool"] == "lint-staged"

    def test_no_pre_commit_tools(self, tmp_path: Path) -> None:
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["pre_commit"]["has_pre_commit"] is False
        assert ev.payload["pre_commit"]["pre_commit_tool"] is None

    def test_package_json_without_lint_staged(self, tmp_path: Path) -> None:
        import json

        pkg = {"name": "myapp", "version": "1.0.0"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["pre_commit"]["has_pre_commit"] is False
        assert ev.payload["pre_commit"]["pre_commit_tool"] is None

    def test_malformed_package_json_no_crash(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("not valid json {{{")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["pre_commit"]["has_pre_commit"] is False
        assert ev.payload["pre_commit"]["pre_commit_tool"] is None

    def test_pre_commit_priority_over_husky(self, tmp_path: Path) -> None:
        """When both .pre-commit-config.yaml and .husky exist, pre-commit wins."""
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        (tmp_path / ".husky").mkdir()
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["pre_commit"]["pre_commit_tool"] == "pre-commit"

    def test_payload_structure_includes_pre_commit(self, tmp_path: Path) -> None:
        """Verify pre_commit is always present in payload even with no tools."""
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert "pre_commit" in ev.payload
        assert "has_pre_commit" in ev.payload["pre_commit"]
        assert "pre_commit_tool" in ev.payload["pre_commit"]


# ---------------------------------------------------------------------------
# HYG-BLD-004: Pre-commit Rule
# ---------------------------------------------------------------------------


class TestPreCommitRule:
    def test_rule_registered(self) -> None:
        assert "HYG-BLD-004" in hygiene_rule_registry

    def test_rule_metadata(self) -> None:
        assert PreCommitRule.id == "HYG-BLD-004"
        assert PreCommitRule.category == "build-readiness"
        assert PreCommitRule.band == 1

    def test_skip_when_no_evidence(self) -> None:
        rule = PreCommitRule()
        result = rule.evaluate([], context=None)
        assert result.skipped

    def test_green_when_pre_commit_present(self, tmp_path: Path) -> None:
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = PreCommitRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "pre-commit" in result.findings[0].summary

    def test_amber_when_no_hooks(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = PreCommitRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "low"

    def test_finding_pattern_tag(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = PreCommitRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].pattern_tag == "pre-commit-hooks"

    def test_amber_recommendation_mentions_tools(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT)
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = PreCommitRule()
        result = rule.evaluate(ev_list, context=None)
        assert "pre-commit.com" in result.findings[0].recommendation
