"""Tests for C++ build system detection in build-readiness collector."""

from __future__ import annotations

from pathlib import Path

from nfr_review.hygiene.collectors.build_readiness import BuildReadinessCollector
from nfr_review.hygiene.collectors.documentation import DocumentationCollector
from nfr_review.hygiene.rules.bld_build_system import BuildSystemRule
from nfr_review.hygiene.rules.bld_entry_points import EntryPointsRule
from nfr_review.hygiene.rules.bld_version_strategy import VersionStrategyRule
from nfr_review.hygiene.rules.doc_pkg_metadata import PkgMetadataRule


class TestCppBuildSystemDetection:
    def test_cmake_detected(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\nproject(sample LANGUAGES CXX)\n"
        )
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "cmake"
        assert ev.payload["build_system"]["path"] == "CMakeLists.txt"

    def test_meson_detected(self, tmp_path: Path) -> None:
        (tmp_path / "meson.build").write_text("project('sample', 'cpp')\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "meson"
        assert ev.payload["build_system"]["path"] == "meson.build"

    def test_makefile_detected(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("all:\n\tg++ -o main main.cpp\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "make"
        assert ev.payload["build_system"]["path"] == "Makefile"

    def test_cmake_source_only_no_build_system(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.cpp").write_text("int main() { return 0; }")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is False

    def test_fixture_cmake_sample_repo(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "cmake-sample-repo"
        c = BuildReadinessCollector()
        results = c.collect(fixture, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "cmake"

    def test_fixture_makefile_sample_repo(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "makefile-sample-repo"
        c = BuildReadinessCollector()
        results = c.collect(fixture, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is True
        assert ev.payload["build_system"]["backend"] == "make"

    def test_fixture_cpp_source_only_no_build(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "cpp-source-only-repo"
        c = BuildReadinessCollector()
        results = c.collect(fixture, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["has_build_system"] is False


class TestCppBLD001RuleEvaluation:
    def test_cmake_bld001_green(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.14)\n")
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "cmake" in result.findings[0].summary.lower()

    def test_meson_bld001_green(self, tmp_path: Path) -> None:
        (tmp_path / "meson.build").write_text("project('sample', 'cpp')\n")
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "meson" in result.findings[0].summary.lower()

    def test_make_bld001_green(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("all:\n\tg++ -o main main.cpp\n")
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = BuildSystemRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "make" in result.findings[0].summary.lower()


class TestCppBuildSystemPriority:
    def test_cmake_wins_over_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.14)\n")
        (tmp_path / "Makefile").write_text("all:\n\tg++ -o main main.cpp\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "cmake"

    def test_meson_wins_over_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "meson.build").write_text("project('sample', 'cpp')\n")
        (tmp_path / "Makefile").write_text("all:\n\tg++ -o main main.cpp\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "meson"

    def test_dotnet_wins_over_cmake(self, tmp_path: Path) -> None:
        """Higher-priority .NET detection comes before CMake in detection order."""
        (tmp_path / "MyApp.csproj").write_text("<Project/>")
        (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.14)\n")
        c = BuildReadinessCollector()
        results = c.collect(tmp_path, config=None)
        ev = results[0]
        assert ev.payload["build_system"]["backend"] == "dotnet"


class TestCmakeVersionDetection:
    def test_cmake_version_found(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(mylib VERSION 2.1.0 LANGUAGES CXX)\n"
        )
        c = BuildReadinessCollector()
        ev = c.collect(tmp_path, config=None)[0]
        ver = ev.payload["version"]
        assert ver["declared"] is True
        assert ver["value"] == "2.1.0"
        assert ver["source"] == "CMakeLists.txt"

    def test_cmake_version_missing(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\nproject(mylib LANGUAGES CXX)\n"
        )
        c = BuildReadinessCollector()
        ev = c.collect(tmp_path, config=None)[0]
        ver = ev.payload["version"]
        assert ver["declared"] is False

    def test_cmake_version_bld002_green(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(mylib VERSION 1.0.0 LANGUAGES CXX)\n"
        )
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "CMakeLists.txt" in result.findings[0].summary

    def test_cmake_version_bld002_amber_when_missing(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\nproject(mylib LANGUAGES CXX)\n"
        )
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = VersionStrategyRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "amber"
        assert "CMakeLists.txt" in result.findings[0].summary

    def test_fixture_cmake_sample_repo_version(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "cmake-sample-repo"
        c = BuildReadinessCollector()
        ev = c.collect(fixture, config=None)[0]
        ver = ev.payload["version"]
        assert ver["declared"] is True
        assert ver["value"] == "1.2.0"
        assert ver["source"] == "CMakeLists.txt"


class TestCmakeManifestDetection:
    def test_cmake_manifest_detected(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            'project(mylib VERSION 1.0.0 DESCRIPTION "A library" LANGUAGES CXX)\n'
        )
        c = DocumentationCollector()
        ev = c.collect(tmp_path, config=None)[0]
        manifests = ev.payload["manifests"]
        assert len(manifests) == 1
        m = manifests[0]
        assert m["path"] == "CMakeLists.txt"
        assert "name" in m["fields_present"]
        assert "version" in m["fields_present"]
        assert "description" in m["fields_present"]

    def test_cmake_manifest_no_red_from_doc001(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(mylib VERSION 1.0.0 LANGUAGES CXX)\n"
        )
        c = DocumentationCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = PkgMetadataRule()
        result = rule.evaluate(ev_list, context=None)
        assert all(f.rag != "red" for f in result.findings)

    def test_cmake_only_project_no_version(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\nproject(mylib LANGUAGES CXX)\n"
        )
        c = DocumentationCollector()
        ev = c.collect(tmp_path, config=None)[0]
        manifests = ev.payload["manifests"]
        assert len(manifests) == 1
        assert "name" in manifests[0]["fields_present"]
        assert "version" in manifests[0]["fields_missing"]


class TestBLD003AutoSkip:
    def test_cmake_backend_skips_entry_points(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\nproject(mylib LANGUAGES CXX)\n"
        )
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = EntryPointsRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()
        assert "cmake" in result.findings[0].summary.lower()

    def test_meson_backend_skips_entry_points(self, tmp_path: Path) -> None:
        (tmp_path / "meson.build").write_text("project('sample', 'cpp')\n")
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = EntryPointsRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()
        assert "meson" in result.findings[0].summary.lower()

    def test_cargo_backend_skips_entry_points(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "sample"\nversion = "0.1.0"\n')
        c = BuildReadinessCollector()
        ev_list = c.collect(tmp_path, config=None)
        rule = EntryPointsRule()
        result = rule.evaluate(ev_list, context=None)
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()
