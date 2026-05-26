# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for architecture test coverage mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.arch_models import Component, ComponentBoundary, TechStackEntry
from nfr_review.arch_test_coverage import (
    assess_test_coverage,
    assess_test_coverage_multi_repo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_component(
    name: str = "my-svc",
    component_type: str = "service",
    boundary_path: str = ".",
    boundary_type: str = "repo",
    repo: str = "test-repo",
    tech_stack: list[TechStackEntry] | None = None,
) -> Component:
    return Component(
        id=f"comp-{name}",
        name=name,
        description=f"Test component {name}",
        component_type=component_type,  # type: ignore[arg-type]
        boundaries=[
            ComponentBoundary(
                boundary_type=boundary_type,  # type: ignore[arg-type]
                path=boundary_path,
                repo=repo,
            )
        ],
        tech_stack=tech_stack or [],
        repo=repo,
    )


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Python project tests
# ---------------------------------------------------------------------------


class TestPythonProject:
    def test_discovers_test_dir_and_files(self, tmp_path: Path) -> None:
        """Standard Python layout with tests/ and test_*.py files."""
        _touch(tmp_path / "src" / "app.py", "# app code")
        _touch(tmp_path / "src" / "models.py", "# models")
        _touch(tmp_path / "tests" / "test_app.py", "# test app")
        _touch(tmp_path / "tests" / "test_models.py", "# test models")
        _touch(tmp_path / "tests" / "conftest.py", "# fixtures")

        comp = _make_component(boundary_path=".", boundary_type="repo")
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")

        assert len(results) == 1
        cov = results[0]
        assert cov.component_id == "comp-my-svc"
        assert cov.functional_coverage != "none"
        assert "unit" in cov.test_types_present
        assert len(cov.evidence_locators) > 0

    def test_underscore_test_suffix(self, tmp_path: Path) -> None:
        """Python *_test.py convention."""
        _touch(tmp_path / "src" / "handler.py")
        _touch(tmp_path / "tests" / "handler_test.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"


# ---------------------------------------------------------------------------
# Java project tests
# ---------------------------------------------------------------------------


class TestJavaProject:
    def test_discovers_src_test_dir(self, tmp_path: Path) -> None:
        """Java project with src/test/ and *Test.java files."""
        _touch(tmp_path / "src" / "main" / "java" / "App.java")
        _touch(tmp_path / "src" / "main" / "java" / "Service.java")
        _touch(tmp_path / "src" / "test" / "java" / "AppTest.java")
        _touch(tmp_path / "src" / "test" / "java" / "ServiceTests.java")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"
        assert "unit" in cov.test_types_present

    def test_integration_test_java(self, tmp_path: Path) -> None:
        """Java *IT.java files are classified as integration tests."""
        _touch(tmp_path / "src" / "main" / "java" / "Api.java")
        _touch(tmp_path / "src" / "test" / "java" / "ApiIT.java")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert "integration" in cov.test_types_present

    def test_spec_files(self, tmp_path: Path) -> None:
        """Java *Spec.java files are discovered."""
        _touch(tmp_path / "src" / "main" / "java" / "Order.java")
        _touch(tmp_path / "src" / "test" / "java" / "OrderSpec.java")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"


# ---------------------------------------------------------------------------
# Node.js / TypeScript project tests
# ---------------------------------------------------------------------------


class TestNodeProject:
    def test_discovers_tests_dir(self, tmp_path: Path) -> None:
        """JS/TS project with __tests__/ and *.test.js files."""
        _touch(tmp_path / "src" / "index.js")
        _touch(tmp_path / "src" / "utils.js")
        _touch(tmp_path / "__tests__" / "index.test.js")
        _touch(tmp_path / "__tests__" / "utils.test.js")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"
        assert len(cov.evidence_locators) >= 2

    def test_spec_ts_files(self, tmp_path: Path) -> None:
        """TypeScript *.spec.ts files are discovered."""
        _touch(tmp_path / "src" / "service.ts")
        _touch(tmp_path / "src" / "service.spec.ts")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"

    def test_jest_config_in_evidence(self, tmp_path: Path) -> None:
        """jest.config.js appears in evidence_locators."""
        _touch(tmp_path / "src" / "app.ts")
        _touch(tmp_path / "jest.config.js", "module.exports = {};")
        _touch(tmp_path / "__tests__" / "app.test.ts")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert any("jest.config.js" in e for e in cov.evidence_locators)

    def test_vitest_config(self, tmp_path: Path) -> None:
        """vitest.config.ts appears in evidence_locators."""
        _touch(tmp_path / "src" / "main.ts")
        _touch(tmp_path / "vitest.config.ts", "export default {};")
        _touch(tmp_path / "src" / "main.test.ts")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert any("vitest.config.ts" in e for e in cov.evidence_locators)


# ---------------------------------------------------------------------------
# Go project tests
# ---------------------------------------------------------------------------


class TestGoProject:
    def test_discovers_test_go_files(self, tmp_path: Path) -> None:
        """Go project with *_test.go files."""
        _touch(tmp_path / "main.go", "package main")
        _touch(tmp_path / "handler.go", "package main")
        _touch(tmp_path / "handler_test.go", "package main")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"
        assert "unit" in cov.test_types_present


# ---------------------------------------------------------------------------
# C# project tests
# ---------------------------------------------------------------------------


class TestCSharpProject:
    def test_discovers_test_cs_files(self, tmp_path: Path) -> None:
        """C# project with *Test.cs and *.Tests.csproj files."""
        _touch(tmp_path / "src" / "Service.cs")
        _touch(tmp_path / "tests" / "ServiceTest.cs")
        _touch(tmp_path / "tests" / "MyApp.Tests.csproj")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"


# ---------------------------------------------------------------------------
# Mixed test type classification
# ---------------------------------------------------------------------------


class TestMixedTestTypes:
    def test_unit_and_integration(self, tmp_path: Path) -> None:
        """Both unit and integration tests are classified."""
        _touch(tmp_path / "src" / "api.py")
        _touch(tmp_path / "tests" / "unit" / "test_api.py")
        _touch(tmp_path / "tests" / "integration" / "test_api_integration.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert "unit" in cov.test_types_present
        assert "integration" in cov.test_types_present

    def test_performance_tests(self, tmp_path: Path) -> None:
        """Performance/benchmark files classified correctly."""
        _touch(tmp_path / "src" / "engine.py")
        _touch(tmp_path / "tests" / "test_engine.py")
        _touch(tmp_path / "tests" / "perf" / "test_benchmark.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert "performance" in cov.test_types_present
        assert cov.nonfunctional_coverage != "none"

    def test_security_tests(self, tmp_path: Path) -> None:
        """Security test files classified correctly."""
        _touch(tmp_path / "src" / "auth.py")
        _touch(tmp_path / "tests" / "test_auth.py")
        _touch(tmp_path / "tests" / "security" / "test_security_scan.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert "security" in cov.test_types_present
        assert cov.nonfunctional_coverage != "none"

    def test_contract_tests(self, tmp_path: Path) -> None:
        """Contract/pact test files classified correctly."""
        _touch(tmp_path / "src" / "client.py")
        _touch(tmp_path / "tests" / "test_client.py")
        _touch(tmp_path / "tests" / "contract" / "test_pact_consumer.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert "contract" in cov.test_types_present

    def test_e2e_tests(self, tmp_path: Path) -> None:
        """End-to-end test directory classified as integration."""
        _touch(tmp_path / "src" / "app.py")
        _touch(tmp_path / "e2e" / "test_full_flow.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        # e2e directory triggers integration classification
        assert "integration" in cov.test_types_present

    def test_resilience_tests(self, tmp_path: Path) -> None:
        """Resilience/chaos test files boost NFR coverage."""
        _touch(tmp_path / "src" / "service.py")
        _touch(tmp_path / "tests" / "test_service.py")
        _touch(tmp_path / "tests" / "chaos" / "test_fault_injection.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert "resilience" in cov.test_types_present
        assert cov.nonfunctional_coverage != "none"

    def test_comprehensive_nfr_coverage(self, tmp_path: Path) -> None:
        """Multiple NFR test types yield higher NFR coverage."""
        _touch(tmp_path / "src" / "core.py")
        _touch(tmp_path / "tests" / "test_core.py")
        _touch(tmp_path / "tests" / "perf" / "test_load.py")
        _touch(tmp_path / "tests" / "security" / "test_auth_vuln.py")
        _touch(tmp_path / "tests" / "contract" / "test_pact.py")
        _touch(tmp_path / "tests" / "chaos" / "test_resilience.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.nonfunctional_coverage == "comprehensive"


# ---------------------------------------------------------------------------
# Coverage level thresholds
# ---------------------------------------------------------------------------


class TestCoverageLevels:
    def test_none_coverage(self, tmp_path: Path) -> None:
        """No test files -> 'none' coverage."""
        _touch(tmp_path / "src" / "app.py")
        _touch(tmp_path / "src" / "models.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage == "none"
        assert cov.nonfunctional_coverage == "none"

    def test_minimal_coverage(self, tmp_path: Path) -> None:
        """Very low test ratio or single type -> 'minimal'."""
        # 20 source files, 1 test file = 5% ratio => minimal
        for i in range(20):
            _touch(tmp_path / "src" / f"mod{i}.py")
        _touch(tmp_path / "tests" / "test_mod0.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage == "minimal"

    def test_partial_coverage(self, tmp_path: Path) -> None:
        """10-30% ratio with 1-2 test types -> 'partial'."""
        # 10 source files, 2 test files = 20% with 2 types
        for i in range(10):
            _touch(tmp_path / "src" / f"mod{i}.py")
        _touch(tmp_path / "tests" / "unit" / "test_mod0.py")
        _touch(tmp_path / "tests" / "integration" / "test_mod1_integration.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage == "partial"

    def test_adequate_coverage(self, tmp_path: Path) -> None:
        """30-60% ratio with 2+ test types -> 'adequate'."""
        # 10 source files, 4 test files = 40% with 3 types
        for i in range(10):
            _touch(tmp_path / "src" / f"mod{i}.py")
        _touch(tmp_path / "tests" / "unit" / "test_mod0.py")
        _touch(tmp_path / "tests" / "unit" / "test_mod1.py")
        _touch(tmp_path / "tests" / "integration" / "test_mod2_integration.py")
        _touch(tmp_path / "tests" / "perf" / "test_benchmark.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage == "adequate"

    def test_comprehensive_coverage(self, tmp_path: Path) -> None:
        """60%+ ratio with 3+ test types -> 'comprehensive'."""
        # 5 source files, 5 test files = 100% with 3+ types
        for i in range(5):
            _touch(tmp_path / "src" / f"mod{i}.py")
        _touch(tmp_path / "tests" / "unit" / "test_mod0.py")
        _touch(tmp_path / "tests" / "unit" / "test_mod1.py")
        _touch(tmp_path / "tests" / "integration" / "test_mod2_integration.py")
        _touch(tmp_path / "tests" / "perf" / "test_benchmark.py")
        _touch(tmp_path / "tests" / "security" / "test_auth_security.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage == "comprehensive"


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------


class TestGapDetection:
    def test_no_unit_tests_gap(self, tmp_path: Path) -> None:
        """Reports gap when only integration tests exist."""
        _touch(tmp_path / "src" / "api.py")
        _touch(tmp_path / "tests" / "integration" / "test_api_integration.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert any("unit" in g.lower() for g in cov.gaps)

    def test_no_integration_tests_gap(self, tmp_path: Path) -> None:
        """Reports gap when only unit tests exist."""
        _touch(tmp_path / "src" / "api.py")
        _touch(tmp_path / "tests" / "test_api.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert any("integration" in g.lower() for g in cov.gaps)

    def test_no_performance_tests_gap(self, tmp_path: Path) -> None:
        """Reports gap when no performance tests found."""
        _touch(tmp_path / "src" / "engine.py")
        _touch(tmp_path / "tests" / "test_engine.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert any("performance" in g.lower() or "load" in g.lower() for g in cov.gaps)

    def test_no_security_tests_gap(self, tmp_path: Path) -> None:
        """Reports gap when no security tests found."""
        _touch(tmp_path / "src" / "handler.py")
        _touch(tmp_path / "tests" / "test_handler.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert any("security" in g.lower() for g in cov.gaps)

    def test_ui_missing_accessibility(self, tmp_path: Path) -> None:
        """UI components get a gap for missing accessibility tests."""
        _touch(tmp_path / "src" / "App.tsx")
        _touch(tmp_path / "__tests__" / "App.test.tsx")

        comp = _make_component(component_type="ui")
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert any("accessibility" in g.lower() for g in cov.gaps)

    def test_no_gaps_false_positive_when_tests_exist(self, tmp_path: Path) -> None:
        """Components with comprehensive tests have fewer gaps."""
        _touch(tmp_path / "src" / "core.py")
        _touch(tmp_path / "tests" / "unit" / "test_core.py")
        _touch(tmp_path / "tests" / "integration" / "test_core_integration.py")
        _touch(tmp_path / "tests" / "perf" / "test_benchmark.py")
        _touch(tmp_path / "tests" / "security" / "test_security.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        # Should not report unit, integration, perf, or security as gaps
        assert not any("No unit tests" in g for g in cov.gaps)
        assert not any("No integration tests" in g for g in cov.gaps)
        assert not any("No performance" in g for g in cov.gaps)
        assert not any("No security" in g for g in cov.gaps)


# ---------------------------------------------------------------------------
# NFR coverage assessment
# ---------------------------------------------------------------------------


class TestNfrCoverage:
    def test_no_nfr_tests(self, tmp_path: Path) -> None:
        """Only unit tests -> NFR coverage is 'none'."""
        _touch(tmp_path / "src" / "app.py")
        _touch(tmp_path / "tests" / "test_app.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        assert results[0].nonfunctional_coverage == "none"

    def test_one_nfr_type_minimal(self, tmp_path: Path) -> None:
        """One NFR test type -> 'minimal'."""
        _touch(tmp_path / "src" / "app.py")
        _touch(tmp_path / "tests" / "test_app.py")
        _touch(tmp_path / "tests" / "perf" / "test_load.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        assert results[0].nonfunctional_coverage == "minimal"

    def test_two_nfr_types_partial(self, tmp_path: Path) -> None:
        """Two NFR test types -> 'partial'."""
        _touch(tmp_path / "src" / "app.py")
        _touch(tmp_path / "tests" / "test_app.py")
        _touch(tmp_path / "tests" / "perf" / "test_load.py")
        _touch(tmp_path / "tests" / "security" / "test_vuln.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        assert results[0].nonfunctional_coverage == "partial"

    def test_three_nfr_types_adequate(self, tmp_path: Path) -> None:
        """Three NFR test types -> 'adequate'."""
        _touch(tmp_path / "src" / "app.py")
        _touch(tmp_path / "tests" / "test_app.py")
        _touch(tmp_path / "tests" / "perf" / "test_load.py")
        _touch(tmp_path / "tests" / "security" / "test_vuln.py")
        _touch(tmp_path / "tests" / "contract" / "test_pact.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        assert results[0].nonfunctional_coverage == "adequate"


# ---------------------------------------------------------------------------
# Build-target (K8s / compose) components
# ---------------------------------------------------------------------------


class TestBuildTargetComponents:
    def test_k8s_component_gets_none(self, tmp_path: Path) -> None:
        """Build-target boundaries produce 'none' coverage with gap note."""
        _touch(tmp_path / "k8s" / "deploy.yaml", "apiVersion: apps/v1")

        comp = _make_component(
            name="k8s-api",
            boundary_path="k8s/deploy.yaml",
            boundary_type="build_target",
        )
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage == "none"
        assert len(cov.gaps) > 0

    def test_compose_component_gets_none(self, tmp_path: Path) -> None:
        """Compose build_target boundaries produce 'none' coverage."""
        _touch(tmp_path / "docker-compose.yml", "services: {}")

        comp = _make_component(
            name="compose-svc",
            boundary_path="docker-compose.yml",
            boundary_type="build_target",
        )
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage == "none"


# ---------------------------------------------------------------------------
# Root component scanning
# ---------------------------------------------------------------------------


class TestRootComponent:
    def test_root_boundary_scans_repo(self, tmp_path: Path) -> None:
        """Component with path='.' scans from repo root."""
        _touch(tmp_path / "main.py")
        _touch(tmp_path / "tests" / "test_main.py")

        comp = _make_component(boundary_path=".", boundary_type="repo")
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"
        assert len(cov.evidence_locators) > 0


# ---------------------------------------------------------------------------
# Multi-repo coverage
# ---------------------------------------------------------------------------


class TestMultiRepo:
    def test_covers_components_from_multiple_repos(self, tmp_path: Path) -> None:
        """Components from different repos are each assessed against their repo."""
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"

        _touch(repo_a / "src" / "svc.py")
        _touch(repo_a / "tests" / "test_svc.py")

        _touch(repo_b / "src" / "lib.go")
        _touch(repo_b / "src" / "lib_test.go")

        comp_a = _make_component(name="svc-a", repo="alpha")
        comp_b = _make_component(name="lib-b", repo="beta")

        results = assess_test_coverage_multi_repo(
            [repo_a, repo_b],
            [comp_a, comp_b],
            repo_names=["alpha", "beta"],
        )
        assert len(results) == 2
        ids = {r.component_id for r in results}
        assert "comp-svc-a" in ids
        assert "comp-lib-b" in ids

    def test_mismatched_names_raises(self, tmp_path: Path) -> None:
        """Mismatched repo_names length raises ValueError."""
        with pytest.raises(ValueError, match="repo_names must match"):
            assess_test_coverage_multi_repo([tmp_path], [], repo_names=["a", "b"])

    def test_unknown_repo_yields_gap(self, tmp_path: Path) -> None:
        """Component with repo name not in paths gets a gap note."""
        comp = _make_component(name="orphan", repo="nonexistent")
        results = assess_test_coverage_multi_repo(
            [tmp_path],
            [comp],
            repo_names=["real-repo"],
        )
        assert len(results) == 1
        assert any("not available" in g.lower() for g in results[0].gaps)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty component directory -> 'none' coverage."""
        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage == "none"

    def test_no_source_files(self, tmp_path: Path) -> None:
        """Only test files, no source -> still records coverage."""
        _touch(tmp_path / "tests" / "test_something.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        # Test file found but no source => ratio is high
        assert cov.functional_coverage != "none"

    def test_nonexistent_boundary_path(self, tmp_path: Path) -> None:
        """Component pointing to missing directory -> graceful handling."""
        comp = _make_component(boundary_path="does/not/exist", boundary_type="directory")
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage == "none"
        assert len(cov.gaps) > 0

    def test_hidden_dirs_skipped(self, tmp_path: Path) -> None:
        """Files in .git, node_modules, etc. are not counted."""
        _touch(tmp_path / "src" / "app.py")
        _touch(tmp_path / "node_modules" / "pkg" / "test_pkg.py")
        _touch(tmp_path / ".git" / "hooks" / "test_hook.py")

        comp = _make_component()
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        # Only the src/app.py source file counted, no tests
        assert cov.functional_coverage == "none"
        assert len(cov.evidence_locators) == 0

    def test_multiple_boundaries(self, tmp_path: Path) -> None:
        """Component with multiple boundaries merges results."""
        _touch(tmp_path / "pkg-a" / "src" / "a.py")
        _touch(tmp_path / "pkg-a" / "tests" / "test_a.py")
        _touch(tmp_path / "pkg-b" / "src" / "b.py")
        _touch(tmp_path / "pkg-b" / "tests" / "test_b.py")

        comp = Component(
            id="comp-multi",
            name="multi",
            description="Multi-boundary component",
            component_type="library",
            boundaries=[
                ComponentBoundary(boundary_type="directory", path="pkg-a", repo="test-repo"),
                ComponentBoundary(boundary_type="directory", path="pkg-b", repo="test-repo"),
            ],
            tech_stack=[],
            repo="test-repo",
        )
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"
        assert len(cov.evidence_locators) >= 2

    def test_boundary_for_different_repo_skipped(self, tmp_path: Path) -> None:
        """Boundary belonging to a different repo is not scanned."""
        _touch(tmp_path / "src" / "app.py")
        _touch(tmp_path / "tests" / "test_app.py")

        comp = Component(
            id="comp-other",
            name="other",
            description="Other repo component",
            component_type="service",
            boundaries=[
                ComponentBoundary(
                    boundary_type="directory",
                    path=".",
                    repo="other-repo",
                )
            ],
            tech_stack=[],
            repo="other-repo",
        )
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        # Boundary repo doesn't match effective name, so nothing scanned
        assert cov.functional_coverage == "none"

    def test_subdirectory_boundary(self, tmp_path: Path) -> None:
        """Component scoped to a subdirectory only counts files there."""
        _touch(tmp_path / "services" / "api" / "handler.py")
        _touch(tmp_path / "services" / "api" / "tests" / "test_handler.py")
        _touch(tmp_path / "services" / "worker" / "task.py")  # Not counted

        comp = _make_component(boundary_path="services/api", boundary_type="directory")
        results = assess_test_coverage(tmp_path, [comp], repo_name="test-repo")
        cov = results[0]
        assert cov.functional_coverage != "none"
        # Evidence should only reference files under services/api
        for e in cov.evidence_locators:
            assert e.startswith("services/api")

    def test_multiple_components(self, tmp_path: Path) -> None:
        """Multiple components each get their own coverage result."""
        _touch(tmp_path / "svc-a" / "main.py")
        _touch(tmp_path / "svc-a" / "tests" / "test_main.py")
        _touch(tmp_path / "svc-b" / "app.py")
        # svc-b has no tests

        comp_a = _make_component(
            name="svc-a", boundary_path="svc-a", boundary_type="directory"
        )
        comp_b = _make_component(
            name="svc-b", boundary_path="svc-b", boundary_type="directory"
        )
        results = assess_test_coverage(tmp_path, [comp_a, comp_b], repo_name="test-repo")
        assert len(results) == 2
        cov_a = next(r for r in results if r.component_id == "comp-svc-a")
        cov_b = next(r for r in results if r.component_id == "comp-svc-b")
        assert cov_a.functional_coverage != "none"
        assert cov_b.functional_coverage == "none"
