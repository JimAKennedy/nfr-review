"""Tests for the shared path_filter module (M012 S01)."""

from __future__ import annotations

import logging
import re
from unittest.mock import patch

import pytest

from nfr_review.path_filter import (
    compile_exclude_patterns,
    is_test_path,
    should_exclude_path,
)

# -- is_test_path: Python dirs --


class TestIsTestPath:
    @pytest.mark.parametrize(
        "path",
        [
            "tests/test_engine.py",
            "test/test_engine.py",
            "src/tests/test_utils.py",
            "project/test/helpers.py",
        ],
    )
    def test_python_dirs(self, path: str) -> None:
        assert is_test_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "test_engine.py",
            "src/test_config.py",
            "engine_test.py",
            "src/nfr_review/engine_test.py",
            "conftest.py",
            "tests/conftest.py",
        ],
    )
    def test_python_files(self, path: str) -> None:
        assert is_test_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "pkg/engine/engine_test.go",
            "cmd/cli/main_test.go",
        ],
    )
    def test_go_files(self, path: str) -> None:
        assert is_test_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "src/test/java/com/example/EngineTest.java",
            "src/test/java/com/example/EngineTests.java",
        ],
    )
    def test_java_files(self, path: str) -> None:
        assert is_test_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "Tests/Unit/EngineTest.cs",
            "Tests/Unit/EngineTests.cs",
        ],
    )
    def test_csharp_files(self, path: str) -> None:
        assert is_test_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "src/components/Button.test.tsx",
            "src/utils/api.spec.ts",
            "lib/parser.test.js",
            "lib/parser.spec.jsx",
        ],
    )
    def test_js_ts_files(self, path: str) -> None:
        assert is_test_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "src/engine.py",
            "lib/main.go",
            "src/main/java/com/example/App.java",
            "src/MyProject/Service.cs",
            "src/components/Button.tsx",
        ],
    )
    def test_source_files_not_matched(self, path: str) -> None:
        assert is_test_path(path) is False

    def test_backslash_normalization(self) -> None:
        assert is_test_path("tests\\test_engine.py") is True
        assert is_test_path("src\\engine.py") is False


# -- should_exclude_path --


class TestShouldExcludePath:
    def test_default_excludes_tests(self) -> None:
        assert should_exclude_path("tests/test_engine.py") is True
        assert should_exclude_path("src/engine.py") is False

    def test_include_tests(self) -> None:
        assert should_exclude_path("tests/test_engine.py", exclude_test_paths=False) is False

    def test_custom_patterns(self) -> None:
        patterns = [re.compile(r"vendor/")]
        assert (
            should_exclude_path(
                "vendor/lib.py",
                exclude_test_paths=False,
                exclude_patterns=patterns,
            )
            is True
        )
        assert (
            should_exclude_path(
                "src/lib.py",
                exclude_test_paths=False,
                exclude_patterns=patterns,
            )
            is False
        )

    def test_custom_patterns_plus_tests(self) -> None:
        patterns = [re.compile(r"vendor/")]
        assert (
            should_exclude_path(
                "tests/test_engine.py",
                exclude_test_paths=True,
                exclude_patterns=patterns,
            )
            is True
        )
        assert (
            should_exclude_path(
                "vendor/lib.py",
                exclude_test_paths=True,
                exclude_patterns=patterns,
            )
            is True
        )
        assert (
            should_exclude_path(
                "src/engine.py",
                exclude_test_paths=True,
                exclude_patterns=patterns,
            )
            is False
        )


# -- compile_exclude_patterns --


class TestCompileExcludePatterns:
    def test_valid_globs(self) -> None:
        patterns = compile_exclude_patterns(["*.pyc", "vendor/*", "build/**"])
        assert len(patterns) == 3
        assert all(isinstance(p, re.Pattern) for p in patterns)
        assert patterns[0].match("foo.pyc")
        assert patterns[1].match("vendor/lib.py")

    def test_invalid_patterns_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        def _bad_compile(pattern: str, flags: int = 0) -> re.Pattern[str]:
            raise re.error("mock error")

        with (
            caplog.at_level(logging.WARNING, logger="nfr_review.path_filter"),
            patch("nfr_review.path_filter.re.compile", side_effect=_bad_compile),
        ):
            patterns = compile_exclude_patterns(["*.pyc"])
        assert len(patterns) == 0
        assert "Skipping invalid exclude pattern" in caplog.text
