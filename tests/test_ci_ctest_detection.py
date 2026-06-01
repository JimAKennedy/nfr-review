# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for CTest / CMake test detection in the CI artifact collector."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.ci_artifact import CiArtifactCollector

CTEST_FIXTURES = Path(__file__).parent / "fixtures" / "cmake-ctest-repo"


@pytest.fixture
def collector() -> CiArtifactCollector:
    return CiArtifactCollector()


class TestCTestInCiWorkflow:
    def test_detects_ctest_in_github_actions(self, collector: CiArtifactCollector) -> None:
        results = collector.collect(CTEST_FIXTURES, config=None)
        pipeline = next(e for e in results if e.kind == "ci-pipeline")
        assert pipeline.payload["has_test_step"] is True

    def test_detects_ctest_bare_command(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        gh_dir = tmp_path / ".github" / "workflows"
        gh_dir.mkdir(parents=True)
        (gh_dir / "ci.yml").write_text(
            "name: CI\non: push\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - name: Run CTest\n        run: ctest --output-on-failure\n"
        )
        results = collector.collect(tmp_path, config=None)
        pipeline = next(e for e in results if e.kind == "ci-pipeline")
        assert pipeline.payload["has_test_step"] is True

    def test_detects_cmake_build_target_test(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        gh_dir = tmp_path / ".github" / "workflows"
        gh_dir.mkdir(parents=True)
        (gh_dir / "ci.yml").write_text(
            "name: CI\non: push\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - name: Build and test\n"
            "        run: cmake --build build --target test\n"
        )
        results = collector.collect(tmp_path, config=None)
        pipeline = next(e for e in results if e.kind == "ci-pipeline")
        assert pipeline.payload["has_test_step"] is True


class TestCMakeTestSignals:
    def test_detects_enable_testing(self, collector: CiArtifactCollector) -> None:
        results = collector.collect(CTEST_FIXTURES, config=None)
        cmake_ev = next((e for e in results if e.kind == "cmake-test-signals"), None)
        assert cmake_ev is not None
        assert cmake_ev.payload["has_test_framework"] is True
        files = cmake_ev.payload["files"]
        assert len(files) >= 1
        signals = files[0]["signals"]
        assert "enable_testing" in signals
        assert "add_test" in signals

    def test_detects_gtest_discover_tests(self, collector: CiArtifactCollector) -> None:
        results = collector.collect(CTEST_FIXTURES, config=None)
        cmake_ev = next(e for e in results if e.kind == "cmake-test-signals")
        signals = cmake_ev.payload["files"][0]["signals"]
        assert "gtest_discover_tests" in signals

    def test_no_cmake_signals_without_cmake(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        gh_dir = tmp_path / ".github" / "workflows"
        gh_dir.mkdir(parents=True)
        (gh_dir / "ci.yml").write_text(
            "name: CI\non: push\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - name: Test\n        run: npm test\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert not any(e.kind == "cmake-test-signals" for e in results)

    def test_cmake_signals_feed_summary(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        """CMakeLists.txt enable_testing feeds summary any_test_step."""
        gh_dir = tmp_path / ".github" / "workflows"
        gh_dir.mkdir(parents=True)
        (gh_dir / "ci.yml").write_text(
            "name: CI\non: push\njobs:\n  build:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - name: Build\n        run: cmake --build build\n"
        )
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(test_proj LANGUAGES CXX)\n"
            "enable_testing()\n"
            "add_test(NAME smoke COMMAND echo ok)\n"
        )
        results = collector.collect(tmp_path, config=None)
        summary = next(e for e in results if e.kind == "ci-summary")
        assert summary.payload["any_test_step"] is True

    def test_hidden_dirs_skipped(self, collector: CiArtifactCollector, tmp_path: Path) -> None:
        hidden = tmp_path / ".build" / "deps"
        hidden.mkdir(parents=True)
        (hidden / "CMakeLists.txt").write_text(
            "enable_testing()\nadd_test(NAME x COMMAND y)\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert not any(e.kind == "cmake-test-signals" for e in results)
