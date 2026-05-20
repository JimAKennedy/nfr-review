"""Tests for C++ technology detection."""

from __future__ import annotations

from pathlib import Path

from nfr_review.detect import ALL_TECH_KEYS, detect_technologies


class TestDetectCpp:
    def test_cpp_in_all_tech_keys(self) -> None:
        assert "cpp" in ALL_TECH_KEYS

    def test_cmake_triggers_detection(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.14)")
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_makefile_triggers_detection(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("all:\n\tg++ -o main main.cpp")
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_meson_build_triggers_detection(self, tmp_path: Path) -> None:
        (tmp_path / "meson.build").write_text("project('sample', 'cpp')")
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_vcxproj_triggers_detection(self, tmp_path: Path) -> None:
        (tmp_path / "app.vcxproj").write_text("<Project/>")
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_conanfile_txt_triggers_detection(self, tmp_path: Path) -> None:
        sub = tmp_path / "build"
        sub.mkdir()
        (sub / "conanfile.txt").write_text("[requires]\nboost/1.83.0")
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_conanfile_py_triggers_detection(self, tmp_path: Path) -> None:
        (tmp_path / "conanfile.py").write_text("from conan import ConanFile")
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_vcpkg_json_triggers_detection(self, tmp_path: Path) -> None:
        (tmp_path / "vcpkg.json").write_text('{"name": "app", "dependencies": []}')
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_cpp_source_files_trigger_detection(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.cpp").write_text("int main() { return 0; }")
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_cc_source_files_trigger_detection(self, tmp_path: Path) -> None:
        (tmp_path / "app.cc").write_text("int main() { return 0; }")
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_cxx_source_files_trigger_detection(self, tmp_path: Path) -> None:
        (tmp_path / "app.cxx").write_text("int main() { return 0; }")
        assert detect_technologies(tmp_path)["cpp"] is True

    def test_negative_empty_repo(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["cpp"] is False

    def test_negative_non_cpp_repo(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'app'")
        assert detect_technologies(tmp_path)["cpp"] is False

    def test_fixture_cmake_sample_repo(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "cmake-sample-repo"
        result = detect_technologies(fixture)
        assert result["cpp"] is True

    def test_fixture_makefile_sample_repo(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "makefile-sample-repo"
        result = detect_technologies(fixture)
        assert result["cpp"] is True

    def test_fixture_cpp_source_only_repo(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "cpp-source-only-repo"
        result = detect_technologies(fixture)
        assert result["cpp"] is True
