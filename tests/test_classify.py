"""Tests for path-based finding classification (M008 S01, M058 S01)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.config import DEFAULT_DEPENDENCY_PATHS
from nfr_review.models import Finding
from nfr_review.output.classify import (
    apply_origin_classification,
    classify_origin,
    classify_region,
    filter_findings_by_origin,
    partition_findings,
    partition_findings_by_origin,
)
from nfr_review.path_filter import compile_exclude_patterns


def _make_finding(
    evidence_locator: str,
    *,
    collector_name: str = "test-collector",
) -> Finding:
    return Finding(
        rule_id="test-rule",
        rag="amber",
        severity="medium",
        summary="Test finding",
        recommendation="Fix it",
        evidence_locator=evidence_locator,
        collector_name=collector_name,
        collector_version="0.1.0",
        confidence=0.8,
        pattern_tag="test-pattern",
    )


class TestClassifyRegion:
    """Tests for classify_region covering Python, Go, Java, C#, JS/TS."""

    # --- Python conventions ---

    @pytest.mark.parametrize(
        "path",
        [
            "tests/test_engine.py",
            "tests/conftest.py",
            "tests/unit/test_models.py",
            "src/tests/test_utils.py",
            "test_cli.py",
            "src/nfr_review/test_config.py",
            "utils_test.py",
            "src/nfr_review/engine_test.py",
            "tests/fixtures/sample.py",
            "conftest.py",
        ],
    )
    def test_python_test_paths(self, path: str) -> None:
        assert classify_region(path) == "test"

    @pytest.mark.parametrize(
        "path",
        [
            "src/nfr_review/engine.py",
            "src/nfr_review/models.py",
            "src/nfr_review/collectors/helm.py",
            "pyproject.toml",
            "contest.py",
            "src/testing_utils.py",
        ],
    )
    def test_python_source_paths(self, path: str) -> None:
        assert classify_region(path) == "source"

    # --- Go conventions ---

    @pytest.mark.parametrize(
        "path",
        [
            "pkg/engine/engine_test.go",
            "cmd/cli/main_test.go",
            "internal/parser/parser_test.go",
        ],
    )
    def test_go_test_paths(self, path: str) -> None:
        assert classify_region(path) == "test"

    @pytest.mark.parametrize(
        "path",
        [
            "pkg/engine/engine.go",
            "cmd/cli/main.go",
            "go.mod",
            "internal/parser/testdata/input.go",
        ],
    )
    def test_go_source_paths(self, path: str) -> None:
        assert classify_region(path) == "source"

    # --- Java conventions ---

    @pytest.mark.parametrize(
        "path",
        [
            "src/test/java/com/example/AppTest.java",
            "src/test/java/com/example/AppTests.java",
            "test/com/example/ServiceTest.java",
        ],
    )
    def test_java_test_paths(self, path: str) -> None:
        assert classify_region(path) == "test"

    @pytest.mark.parametrize(
        "path",
        [
            "src/main/java/com/example/App.java",
            "src/main/java/com/example/TestHelper.java",
        ],
    )
    def test_java_source_paths(self, path: str) -> None:
        assert classify_region(path) == "source"

    # --- C# conventions ---

    @pytest.mark.parametrize(
        "path",
        [
            "Tests/UnitTests/ServiceTest.cs",
            "test/IntegrationTests/ApiTests.cs",
            "MyProject.Tests/ControllerTest.cs",
        ],
    )
    def test_csharp_test_paths(self, path: str) -> None:
        assert classify_region(path) == "test"

    @pytest.mark.parametrize(
        "path",
        [
            "src/MyProject/Service.cs",
            "src/MyProject/TestHelper.cs",
        ],
    )
    def test_csharp_source_paths(self, path: str) -> None:
        assert classify_region(path) == "source"

    # --- JavaScript/TypeScript conventions ---

    @pytest.mark.parametrize(
        "path",
        [
            "src/components/Button.test.tsx",
            "src/utils/helpers.test.ts",
            "lib/parser.spec.js",
            "__tests__/integration.js",
            "spec/api.spec.tsx",
        ],
    )
    def test_js_ts_test_paths(self, path: str) -> None:
        assert classify_region(path) == "test"

    @pytest.mark.parametrize(
        "path",
        [
            "src/components/Button.tsx",
            "src/utils/helpers.ts",
            "lib/parser.js",
            "index.jsx",
        ],
    )
    def test_js_ts_source_paths(self, path: str) -> None:
        assert classify_region(path) == "source"

    # --- Windows path normalization ---

    def test_windows_backslash_paths(self) -> None:
        assert classify_region("tests\\test_engine.py") == "test"
        assert classify_region("src\\nfr_review\\engine.py") == "source"

    # --- Edge cases ---

    def test_empty_path(self) -> None:
        assert classify_region("") == "source"

    def test_non_code_files_in_test_dirs(self) -> None:
        assert classify_region("tests/fixtures/sample.yaml") == "test"

    def test_testdata_not_matched_without_test_dir(self) -> None:
        assert classify_region("internal/parser/testdata/input.go") == "source"


class TestPartitionFindings:
    """Tests for partition_findings splitting by evidence_locator."""

    def test_empty_list(self) -> None:
        source, test = partition_findings([])
        assert source == []
        assert test == []

    def test_all_source(self) -> None:
        findings = [
            _make_finding("src/engine.py"),
            _make_finding("lib/utils.go"),
        ]
        source, test = partition_findings(findings)
        assert len(source) == 2
        assert len(test) == 0

    def test_all_test(self) -> None:
        findings = [
            _make_finding("tests/test_engine.py"),
            _make_finding("pkg/parser/parser_test.go"),
        ]
        source, test = partition_findings(findings)
        assert len(source) == 0
        assert len(test) == 2

    def test_mixed_partition(self) -> None:
        findings = [
            _make_finding("src/nfr_review/engine.py"),
            _make_finding("tests/test_engine.py"),
            _make_finding("src/nfr_review/models.py"),
            _make_finding("tests/test_models.py"),
            _make_finding("src/App.test.tsx"),
        ]
        source, test = partition_findings(findings)
        assert len(source) == 2
        assert len(test) == 3
        assert all(classify_region(f.evidence_locator) == "source" for f in source)
        assert all(classify_region(f.evidence_locator) == "test" for f in test)

    def test_preserves_finding_content(self) -> None:
        finding = _make_finding("tests/test_engine.py")
        _, test = partition_findings([finding])
        assert test[0] is finding


class TestClassifyOrigin:
    """Tests for classify_origin: first_party vs dependency."""

    def test_dep_locator_prefix(self) -> None:
        f = _make_finding("dep:python-deps:requests", collector_name="python-deps")
        assert classify_origin(f) == "dependency"

    def test_dep_locator_prefix_any_collector(self) -> None:
        f = _make_finding("dep:java-deps:spring-core", collector_name="java-deps")
        assert classify_origin(f) == "dependency"

    def test_first_party_source_file(self) -> None:
        f = _make_finding("src/nfr_review/engine.py:42")
        assert classify_origin(f) == "first_party"

    def test_first_party_config_file(self) -> None:
        f = _make_finding("Dockerfile:10")
        assert classify_origin(f) == "first_party"

    def test_vendor_path_with_patterns(self) -> None:
        dep_pats = compile_exclude_patterns(DEFAULT_DEPENDENCY_PATHS)
        f = _make_finding("vendor/github.com/lib/pq/conn.go:55")
        assert classify_origin(f, dep_pats) == "dependency"

    def test_vendored_path_with_patterns(self) -> None:
        dep_pats = compile_exclude_patterns(DEFAULT_DEPENDENCY_PATHS)
        f = _make_finding("vendored/lib/utils.py:10")
        assert classify_origin(f, dep_pats) == "dependency"

    def test_third_party_path_with_patterns(self) -> None:
        dep_pats = compile_exclude_patterns(DEFAULT_DEPENDENCY_PATHS)
        f = _make_finding("third_party/protobuf/message.cc:100")
        assert classify_origin(f, dep_pats) == "dependency"

    def test_third_party_hyphen_path(self) -> None:
        dep_pats = compile_exclude_patterns(DEFAULT_DEPENDENCY_PATHS)
        f = _make_finding("third-party/lib/foo.js:1")
        assert classify_origin(f, dep_pats) == "dependency"

    def test_min_js_with_patterns(self) -> None:
        dep_pats = compile_exclude_patterns(DEFAULT_DEPENDENCY_PATHS)
        f = _make_finding("src/nfr_review/data/mermaid.min.js:445")
        assert classify_origin(f, dep_pats) == "dependency"

    def test_min_css_with_patterns(self) -> None:
        dep_pats = compile_exclude_patterns(DEFAULT_DEPENDENCY_PATHS)
        f = _make_finding("static/bootstrap.min.css:1")
        assert classify_origin(f, dep_pats) == "dependency"

    def test_first_party_without_patterns(self) -> None:
        f = _make_finding("vendor/lib/foo.go:1")
        assert classify_origin(f) == "first_party"

    def test_non_dep_collector_with_dep_like_name(self) -> None:
        f = _make_finding("src/main.py:10", collector_name="python-ast")
        assert classify_origin(f) == "first_party"

    def test_jdepend_locator_is_first_party(self) -> None:
        f = _make_finding("jdepend:com.example.api", collector_name="jdepend")
        assert classify_origin(f) == "first_party"

    def test_k8s_locator_is_first_party(self) -> None:
        f = _make_finding("deploy/k8s/app.yaml:my-app:web")
        assert classify_origin(f) == "first_party"

    def test_windows_backslash_vendor(self) -> None:
        dep_pats = compile_exclude_patterns(DEFAULT_DEPENDENCY_PATHS)
        f = _make_finding("vendor\\lib\\foo.go:1")
        assert classify_origin(f, dep_pats) == "dependency"


class TestApplyOriginClassification:
    """Tests for apply_origin_classification bulk annotation."""

    def test_annotates_mixed_findings(self) -> None:
        findings = [
            _make_finding("src/engine.py:10"),
            _make_finding("dep:python-deps:flask", collector_name="python-deps"),
            _make_finding("src/data/chart.min.js:1"),
        ]
        apply_origin_classification(findings, DEFAULT_DEPENDENCY_PATHS)
        assert findings[0].origin == "first_party"
        assert findings[1].origin == "dependency"
        assert findings[2].origin == "dependency"

    def test_empty_list(self) -> None:
        result = apply_origin_classification([], DEFAULT_DEPENDENCY_PATHS)
        assert result == []

    def test_no_patterns_still_detects_dep_prefix(self) -> None:
        findings = [_make_finding("dep:go-deps:gin", collector_name="go-deps")]
        apply_origin_classification(findings, dependency_paths=None)
        assert findings[0].origin == "dependency"

    def test_returns_same_list(self) -> None:
        findings = [_make_finding("src/main.py:1")]
        result = apply_origin_classification(findings, DEFAULT_DEPENDENCY_PATHS)
        assert result is findings


class TestFilterFindingsByOrigin:
    """Tests for filter_findings_by_origin."""

    def test_filter_first_party(self) -> None:
        findings = [
            _make_finding("src/engine.py:10"),
            _make_finding("dep:python-deps:flask", collector_name="python-deps"),
        ]
        apply_origin_classification(findings, DEFAULT_DEPENDENCY_PATHS)
        result = filter_findings_by_origin(findings, "first_party")
        assert len(result) == 1
        assert result[0].evidence_locator == "src/engine.py:10"

    def test_filter_dependency(self) -> None:
        findings = [
            _make_finding("src/engine.py:10"),
            _make_finding("dep:python-deps:flask", collector_name="python-deps"),
        ]
        apply_origin_classification(findings, DEFAULT_DEPENDENCY_PATHS)
        result = filter_findings_by_origin(findings, "dependency")
        assert len(result) == 1
        assert result[0].evidence_locator == "dep:python-deps:flask"


class TestPartitionFindingsByOrigin:
    """Tests for partition_findings_by_origin."""

    def test_empty_list(self) -> None:
        fp, dep = partition_findings_by_origin([])
        assert fp == []
        assert dep == []

    def test_mixed_partition(self) -> None:
        findings = [
            _make_finding("src/engine.py:10"),
            _make_finding("dep:python-deps:flask", collector_name="python-deps"),
            _make_finding("src/models.py:20"),
            _make_finding("vendor/lib/foo.go:1"),
        ]
        apply_origin_classification(findings, DEFAULT_DEPENDENCY_PATHS)
        fp, dep = partition_findings_by_origin(findings)
        assert len(fp) == 2
        assert len(dep) == 2


class TestOriginCLIOption:
    """Integration test for --origin CLI flag."""

    def test_run_with_origin_first_party(self, tmp_path: Path) -> None:
        from nfr_review.cli import cli

        target = tmp_path / "repo"
        target.mkdir()
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(target), "--origin", "first_party", "-q"],
        )
        assert result.exit_code == 0

    def test_run_with_origin_dependency(self, tmp_path: Path) -> None:
        from nfr_review.cli import cli

        target = tmp_path / "repo"
        target.mkdir()
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(target), "--origin", "dependency", "-q"],
        )
        assert result.exit_code == 0

    def test_run_rejects_invalid_origin(self, tmp_path: Path) -> None:
        from nfr_review.cli import cli

        target = tmp_path / "repo"
        target.mkdir()
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(target), "--origin", "unknown"],
        )
        assert result.exit_code != 0
