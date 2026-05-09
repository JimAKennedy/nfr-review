"""Tests for path-based finding classification (M008 S01)."""

from __future__ import annotations

import pytest

from nfr_review.models import Finding
from nfr_review.output.classify import classify_region, partition_findings


def _make_finding(evidence_locator: str) -> Finding:
    return Finding(
        rule_id="test-rule",
        rag="amber",
        severity="medium",
        summary="Test finding",
        recommendation="Fix it",
        evidence_locator=evidence_locator,
        collector_name="test-collector",
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
