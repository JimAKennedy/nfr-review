"""Tests for build-readiness collector and HYG-BLD-001 through HYG-BLD-003 rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_collector_registry, hygiene_rule_registry
from nfr_review.hygiene.collectors.build_readiness import BuildReadinessCollector
from nfr_review.hygiene.rules.bld_build_system import BuildSystemRule
from nfr_review.hygiene.rules.bld_entry_points import EntryPointsRule
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
