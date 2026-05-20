"""Tests for C++ build system detection in build-readiness collector."""

from __future__ import annotations

from pathlib import Path

from nfr_review.hygiene.collectors.build_readiness import BuildReadinessCollector
from nfr_review.hygiene.rules.bld_build_system import BuildSystemRule


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
