"""Tests for the shared path_filter module (M012 S01)."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nfr_review.path_filter import (
    compile_exclude_patterns,
    get_git_tracked_files,
    is_test_path,
    iter_repo_files,
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


# -- get_git_tracked_files --


class TestGetGitTrackedFiles:
    def test_returns_tracked_files_in_git_repo(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        (tmp_path / "tracked.py").write_text("x = 1\n")
        (tmp_path / ".gitignore").write_text("ignored/\n")
        (tmp_path / "ignored").mkdir()
        (tmp_path / "ignored" / "junk.py").write_text("y = 2\n")
        subprocess.run(
            ["git", "add", "tracked.py", ".gitignore"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        result = get_git_tracked_files(tmp_path)
        assert result is not None
        assert "tracked.py" in result
        assert ".gitignore" in result
        assert "ignored/junk.py" not in result

    def test_includes_untracked_non_ignored_files(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        (tmp_path / "new_file.py").write_text("z = 3\n")

        result = get_git_tracked_files(tmp_path)
        assert result is not None
        assert "new_file.py" in result

    def test_returns_none_for_non_git_dir(self, tmp_path: Path) -> None:
        (tmp_path / "file.py").write_text("x = 1\n")
        result = get_git_tracked_files(tmp_path)
        assert result is None

    def test_returns_none_when_git_unavailable(self, tmp_path: Path) -> None:
        with patch(
            "nfr_review.path_filter.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            result = get_git_tracked_files(tmp_path)
        assert result is None

    def test_returns_none_on_timeout(self, tmp_path: Path) -> None:
        with patch(
            "nfr_review.path_filter.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 30),
        ):
            result = get_git_tracked_files(tmp_path)
        assert result is None


# -- iter_repo_files --


class TestIterRepoFiles:
    def test_git_repo_excludes_gitignored(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1\n")
        (tmp_path / ".gitignore").write_text("node_modules/\n.venv/\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg.js").write_text("// vendored\n")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("# venv\n")
        subprocess.run(
            ["git", "add", "src/main.py", ".gitignore"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        files = iter_repo_files(tmp_path)
        rel_paths = {str(f.relative_to(tmp_path)) for f in files}
        assert "src/main.py" in rel_paths
        assert ".gitignore" in rel_paths
        assert "node_modules/pkg.js" not in rel_paths
        assert ".venv/lib.py" not in rel_paths

    def test_non_git_dir_uses_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg.js").write_text("// vendored\n")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "mod.pyc").write_bytes(b"\x00")

        files = iter_repo_files(tmp_path)
        rel_paths = {str(f.relative_to(tmp_path)) for f in files}
        assert "src/main.py" in rel_paths
        assert "node_modules/pkg.js" not in rel_paths
        assert "__pycache__/mod.pyc" not in rel_paths

    def test_returns_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "b.txt").write_text("b\n")
        (tmp_path / "a.txt").write_text("a\n")
        files = iter_repo_files(tmp_path)
        assert files == sorted(files)
