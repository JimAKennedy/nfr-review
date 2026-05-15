"""End-to-end integration tests for exclude_paths config key.

Verifies that exclude_paths patterns in Config propagate through both the
engine post-collection filter and per-collector pre-filters, excluding matched
paths from all analysis with real collectors (no mocks of path logic).
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nfr_review.collectors.java_ast import JavaAstCollector
from nfr_review.collectors.python_deps import PythonDepsCollector
from nfr_review.config import Config
from nfr_review.engine import Engine
from nfr_review.registry import Registry
from nfr_review.rules.ast_bare_except import BareExceptCatchAllRule

_JAVA_SRC = """\
package com.example;

public class App {
    public void doWork() {
        try {
            int x = 1 / 0;
        } catch (Exception e) {
            // swallowed
        }
    }
}
"""

_REQUIREMENTS_TXT = """\
requests>=2.28
flask>=2.0
"""


def _create_fixture_project(tmp_path: Path) -> None:
    """Create a temp project with files at both included and excluded paths."""
    # Main source
    src_dir = tmp_path / "src" / "main" / "java" / "com" / "example"
    src_dir.mkdir(parents=True)
    (src_dir / "App.java").write_text(_JAVA_SRC, encoding="utf-8")

    # Vendor dir (to be excluded)
    vendor_dir = tmp_path / "vendor" / "third_party" / "java" / "com" / "lib"
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "Util.java").write_text(_JAVA_SRC, encoding="utf-8")

    # Generated dir (to be excluded)
    gen_dir = tmp_path / "generated" / "models" / "java" / "com" / "gen"
    gen_dir.mkdir(parents=True)
    (gen_dir / "Model.java").write_text(_JAVA_SRC, encoding="utf-8")

    # Root requirements.txt (included)
    (tmp_path / "requirements.txt").write_text(_REQUIREMENTS_TXT, encoding="utf-8")

    # Vendor requirements.txt (excluded)
    vendor_py = tmp_path / "vendor" / "deps"
    vendor_py.mkdir(parents=True, exist_ok=True)
    (vendor_py / "requirements.txt").write_text("old-lib==1.0\n", encoding="utf-8")

    # Generated requirements.txt (excluded)
    gen_py = tmp_path / "generated"
    gen_py.mkdir(parents=True, exist_ok=True)
    (gen_py / "requirements.txt").write_text("codegen-lib==0.1\n", encoding="utf-8")


def _mock_deps_dev_client():
    """Patch DepsDevClient to avoid network calls."""
    import nfr_review.collectors.python_deps as pdm

    original = pdm.DepsDevClient
    mock_client = MagicMock()
    mock_client.prefetch_package_versions = MagicMock()
    mock_client.get_package_version.return_value = None
    pdm.DepsDevClient = lambda: mock_client  # type: ignore[assignment,misc]
    return original


def _restore_deps_dev_client(original):
    import nfr_review.collectors.python_deps as pdm

    pdm.DepsDevClient = original  # type: ignore[misc]


class TestSingleGlobPattern:
    """Single exclude_paths pattern excludes matching files from collectors."""

    def test_java_ast_collector_excludes_vendor(self, tmp_path: Path) -> None:
        _create_fixture_project(tmp_path)

        collector = JavaAstCollector()
        config = Config(exclude_paths=["vendor/*"], exclude_test_paths=False)

        evidence = collector.collect(tmp_path, config)
        locators = [e.locator for e in evidence]

        assert any("src/" in loc for loc in locators), (
            f"Expected evidence from src/, got: {locators}"
        )
        assert not any("vendor/" in loc for loc in locators), (
            f"vendor/ should have been excluded, got: {locators}"
        )

    def test_python_deps_collector_excludes_vendor(self, tmp_path: Path) -> None:
        _create_fixture_project(tmp_path)

        collector = PythonDepsCollector()
        config = Config(exclude_paths=["vendor/*"], exclude_test_paths=False)

        original = _mock_deps_dev_client()
        try:
            evidence = collector.collect(tmp_path, config)
        finally:
            _restore_deps_dev_client(original)

        assert len(evidence) >= 1
        manifest_files = evidence[0].payload["manifest_files_found"]
        assert not any("vendor/" in m for m in manifest_files), (
            f"vendor/ manifests should have been excluded, got: {manifest_files}"
        )
        assert "requirements.txt" in manifest_files


class TestMultiplePatterns:
    """Multiple exclude_paths patterns exclude all matching paths."""

    def test_java_ast_excludes_vendor_and_generated(self, tmp_path: Path) -> None:
        _create_fixture_project(tmp_path)

        collector = JavaAstCollector()
        config = Config(exclude_paths=["vendor/*", "generated/*"], exclude_test_paths=False)

        evidence = collector.collect(tmp_path, config)
        locators = [e.locator for e in evidence]

        assert any("src/" in loc for loc in locators), (
            f"Expected evidence from src/, got: {locators}"
        )
        assert not any("vendor/" in loc for loc in locators), (
            f"vendor/ should have been excluded, got: {locators}"
        )
        assert not any("generated/" in loc for loc in locators), (
            f"generated/ should have been excluded, got: {locators}"
        )

    def test_python_deps_excludes_vendor_and_generated(self, tmp_path: Path) -> None:
        _create_fixture_project(tmp_path)

        collector = PythonDepsCollector()
        config = Config(exclude_paths=["vendor/*", "generated/*"], exclude_test_paths=False)

        original = _mock_deps_dev_client()
        try:
            evidence = collector.collect(tmp_path, config)
        finally:
            _restore_deps_dev_client(original)

        assert len(evidence) >= 1
        manifest_files = evidence[0].payload["manifest_files_found"]
        assert not any("vendor/" in m for m in manifest_files), (
            f"vendor/ manifests should be excluded, got: {manifest_files}"
        )
        assert not any("generated/" in m for m in manifest_files), (
            f"generated/ manifests should be excluded, got: {manifest_files}"
        )
        assert "requirements.txt" in manifest_files


class TestEnginePostFilter:
    """Engine post-collection filter applies exclude_paths to all evidence."""

    def test_engine_excludes_vendor_from_findings(self, tmp_path: Path) -> None:
        _create_fixture_project(tmp_path)

        collectors: Registry = Registry("collector")
        collectors.register("java-ast", JavaAstCollector())

        rules: Registry = Registry("rule")
        rules.register("bare-except-catch-all", BareExceptCatchAllRule())

        engine = Engine(collectors=collectors, rules=rules)
        config = Config(exclude_paths=["vendor/*"], exclude_test_paths=False)
        result = engine.run(tmp_path, config)

        for finding in result.findings:
            assert "vendor/" not in finding.evidence_locator, (
                f"vendor/ finding should have been excluded: {finding.evidence_locator}"
            )
        non_green = [f for f in result.findings if f.rag != "green"]
        assert len(non_green) > 0, "Expected at least one finding from src/"


class TestEmptyExcludePaths:
    """Empty exclude_paths list filters nothing extra."""

    def test_empty_list_includes_all_paths(self, tmp_path: Path) -> None:
        _create_fixture_project(tmp_path)

        collector = JavaAstCollector()
        config = Config(exclude_paths=[], exclude_test_paths=False)

        evidence = collector.collect(tmp_path, config)
        locators = [e.locator for e in evidence]

        assert any("src/" in loc for loc in locators)
        assert any("vendor/" in loc for loc in locators)
        assert any("generated/" in loc for loc in locators)


class TestPatternMatchingNothing:
    """A pattern that matches no files does not cause errors."""

    def test_nonmatching_pattern_no_error(self, tmp_path: Path) -> None:
        _create_fixture_project(tmp_path)

        collector = JavaAstCollector()
        config = Config(exclude_paths=["nonexistent_directory/*"], exclude_test_paths=False)

        evidence = collector.collect(tmp_path, config)
        locators = [e.locator for e in evidence]

        assert any("src/" in loc for loc in locators)
        assert any("vendor/" in loc for loc in locators)
        assert any("generated/" in loc for loc in locators)


class TestInvalidPatternGracefulHandling:
    """Invalid regex pattern is gracefully skipped (logged, not fatal)."""

    def test_compile_exclude_patterns_logs_invalid(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """compile_exclude_patterns logs a warning and skips bad patterns."""
        import re

        from nfr_review.path_filter import compile_exclude_patterns

        # Monkeypatch re.compile to simulate a regex error on a specific pattern
        original_compile = re.compile

        def _fake_compile(pattern, *args, **kwargs):
            if "FORCE_FAIL" in pattern:
                raise re.error("simulated bad pattern")
            return original_compile(pattern, *args, **kwargs)

        monkeypatch.setattr(re, "compile", _fake_compile)

        with caplog.at_level(logging.WARNING):
            result = compile_exclude_patterns(["FORCE_FAIL", "vendor/*"])

        assert len(result) == 1, "Only valid pattern should survive"
        assert any("Skipping invalid exclude pattern" in r.message for r in caplog.records)

    def test_unusual_patterns_do_not_crash_collector(self, tmp_path: Path) -> None:
        """Unusual glob patterns handled by fnmatch don't crash the collector."""
        _create_fixture_project(tmp_path)

        collector = JavaAstCollector()
        config = Config(exclude_paths=["[invalid-regex", "vendor/*"], exclude_test_paths=False)

        evidence = collector.collect(tmp_path, config)
        locators = [e.locator for e in evidence]

        assert any("src/" in loc for loc in locators), "Valid files still collected"
        assert not any("vendor/" in loc for loc in locators), (
            "Valid pattern still applied alongside unusual pattern"
        )
