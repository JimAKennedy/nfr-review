"""Tests for CPP-* and CPP-TOOL-* rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.cpp_ast import CppAstCollector
from nfr_review.models import Evidence
from nfr_review.rules.cpp_clang_format import CppClangFormatRule
from nfr_review.rules.cpp_clang_tidy import CppClangTidyRule
from nfr_review.rules.cpp_exception_safety import CppExceptionSafetyRule
from nfr_review.rules.cpp_include_guards import CppIncludeGuardsRule
from nfr_review.rules.cpp_raw_memory import CppRawMemoryRule
from nfr_review.rules.cpp_sanitizer_ci import CppSanitizerCiRule

AST_FIXTURES = Path(__file__).parent / "fixtures" / "cpp-ast-sample-repo"
TOOLCHAIN_GOOD = Path(__file__).parent / "fixtures" / "cpp-toolchain-good-repo"
TOOLCHAIN_BAD = Path(__file__).parent / "fixtures" / "cpp-toolchain-bad-repo"


@pytest.fixture()
def collector() -> CppAstCollector:
    return CppAstCollector()


@pytest.fixture()
def ast_evidence(collector: CppAstCollector) -> list[Evidence]:
    return collector.collect(AST_FIXTURES, config=None)


def _make_evidence(kind: str, payload: dict, *, collector_name: str = "test") -> Evidence:
    return Evidence(
        kind=kind,
        locator="test",
        payload=payload,
        collector_name=collector_name,
        collector_version="0.0.0",
    )


# ---------------------------------------------------------------------------
# CPP-001: Raw Memory
# ---------------------------------------------------------------------------
class TestCppRawMemory:
    def test_detects_raw_new(self, ast_evidence: list[Evidence]) -> None:
        rule = CppRawMemoryRule()
        result = rule.evaluate(ast_evidence, context=None)
        assert not result.skipped
        tags = [f.pattern_tag for f in result.findings]
        assert "cpp-raw-new" in tags

    def test_detects_raw_delete(self, ast_evidence: list[Evidence]) -> None:
        rule = CppRawMemoryRule()
        result = rule.evaluate(ast_evidence, context=None)
        tags = [f.pattern_tag for f in result.findings]
        assert "cpp-raw-delete" in tags

    def test_detects_malloc(self, ast_evidence: list[Evidence]) -> None:
        rule = CppRawMemoryRule()
        result = rule.evaluate(ast_evidence, context=None)
        tags = [f.pattern_tag for f in result.findings]
        assert "cpp-malloc-usage" in tags

    def test_green_when_clean(self) -> None:
        rule = CppRawMemoryRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "clean.cpp",
                "functions": [],
                "classes": [],
                "namespaces": [],
                "includes": [],
                "new_expressions": [],
                "delete_expressions": [],
                "smart_pointers": [{"kind": "unique_ptr", "line": 1, "file": "clean.cpp"}],
                "raw_pointers": [],
                "malloc_calls": [],
                "catch_blocks": [],
                "has_pragma_once": False,
                "has_include_guard": False,
                "log_statements": [],
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-raii-only"

    def test_skips_without_evidence(self) -> None:
        rule = CppRawMemoryRule()
        result = rule.evaluate([], context=None)
        assert result.skipped


# ---------------------------------------------------------------------------
# CPP-002: Include Guards
# ---------------------------------------------------------------------------
class TestCppIncludeGuards:
    def test_detects_missing_guard(self, ast_evidence: list[Evidence]) -> None:
        rule = CppIncludeGuardsRule()
        result = rule.evaluate(ast_evidence, context=None)
        assert not result.skipped
        missing = [f for f in result.findings if f.pattern_tag == "cpp-missing-include-guard"]
        assert len(missing) >= 1

    def test_green_when_all_guarded(self) -> None:
        rule = CppIncludeGuardsRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "guarded.h",
                "has_pragma_once": True,
                "has_include_guard": False,
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-include-guards-ok"

    def test_skips_without_headers(self) -> None:
        rule = CppIncludeGuardsRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "main.cpp",
                "has_pragma_once": False,
                "has_include_guard": False,
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.skipped
        assert "no C++ header files" in result.skip_reason

    def test_skips_without_evidence(self) -> None:
        rule = CppIncludeGuardsRule()
        result = rule.evaluate([], context=None)
        assert result.skipped


# ---------------------------------------------------------------------------
# CPP-003: Exception Safety
# ---------------------------------------------------------------------------
class TestCppExceptionSafety:
    def test_detects_catch_all_silent(self) -> None:
        rule = CppExceptionSafetyRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "bad.cpp",
                "catch_blocks": [
                    {"caught_type": "...", "rethrows": False, "line": 42, "file": "bad.cpp"},
                ],
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].pattern_tag == "cpp-catch-all-silent"
        assert result.findings[0].rag == "amber"

    def test_allows_catch_all_with_rethrow(self) -> None:
        rule = CppExceptionSafetyRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "ok.cpp",
                "catch_blocks": [
                    {"caught_type": "...", "rethrows": True, "line": 10, "file": "ok.cpp"},
                ],
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-exception-safety-ok"

    def test_green_no_catch_blocks(self) -> None:
        rule = CppExceptionSafetyRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {"file_path": "clean.cpp", "catch_blocks": []},
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"

    def test_skips_without_evidence(self) -> None:
        rule = CppExceptionSafetyRule()
        result = rule.evaluate([], context=None)
        assert result.skipped


# ---------------------------------------------------------------------------
# CPP-TOOL-001: clang-format
# ---------------------------------------------------------------------------
class TestCppClangFormat:
    def test_green_when_present(self) -> None:
        rule = CppClangFormatRule()
        ev = _make_evidence(
            "repo-structure-summary",
            {"files": [".clang-format", "src/main.cpp"]},
            collector_name="repo-structure",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-clang-format-present"

    def test_amber_when_missing(self) -> None:
        rule = CppClangFormatRule()
        ev = _make_evidence(
            "repo-structure-summary",
            {"files": ["src/main.cpp", "CMakeLists.txt"]},
            collector_name="repo-structure",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].pattern_tag == "cpp-clang-format-missing"

    def test_recognises_underscore_variant(self) -> None:
        rule = CppClangFormatRule()
        ev = _make_evidence(
            "repo-structure-summary",
            {"files": ["_clang-format"]},
            collector_name="repo-structure",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"

    def test_green_with_top_level_files(self) -> None:
        rule = CppClangFormatRule()
        ev = _make_evidence(
            "repo-structure-summary",
            {"top_level_files": [".clang-format", "CMakeLists.txt"]},
            collector_name="repo-structure",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"

    def test_skips_without_evidence(self) -> None:
        rule = CppClangFormatRule()
        result = rule.evaluate([], context=None)
        assert result.skipped


# ---------------------------------------------------------------------------
# CPP-TOOL-002: clang-tidy
# ---------------------------------------------------------------------------
class TestCppClangTidy:
    def test_green_when_present(self) -> None:
        rule = CppClangTidyRule()
        ev = _make_evidence(
            "repo-structure-summary",
            {"files": [".clang-tidy", "src/main.cpp"]},
            collector_name="repo-structure",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-clang-tidy-present"

    def test_amber_when_missing(self) -> None:
        rule = CppClangTidyRule()
        ev = _make_evidence(
            "repo-structure-summary",
            {"files": ["src/main.cpp"]},
            collector_name="repo-structure",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].pattern_tag == "cpp-clang-tidy-missing"

    def test_skips_without_evidence(self) -> None:
        rule = CppClangTidyRule()
        result = rule.evaluate([], context=None)
        assert result.skipped


# ---------------------------------------------------------------------------
# CPP-TOOL-003: Sanitizer CI
# ---------------------------------------------------------------------------
class TestCppSanitizerCi:
    def test_green_with_asan_step(self) -> None:
        rule = CppSanitizerCiRule()
        ev = _make_evidence(
            "ci-pipeline",
            {
                "step_names": ["Build with ASAN", "Build with UBSAN"],
                "job_names": ["sanitizers"],
            },
            collector_name="ci-artifact",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-sanitizer-ci-present"

    def test_green_with_ubsan_job(self) -> None:
        rule = CppSanitizerCiRule()
        ev = _make_evidence(
            "ci-pipeline",
            {"step_names": [], "job_names": ["ubsan-tests"]},
            collector_name="ci-artifact",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"

    def test_amber_when_missing(self) -> None:
        rule = CppSanitizerCiRule()
        ev = _make_evidence(
            "ci-pipeline",
            {"step_names": ["Build", "Test"], "job_names": ["build", "test"]},
            collector_name="ci-artifact",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].pattern_tag == "cpp-sanitizer-ci-missing"

    def test_skips_without_evidence(self) -> None:
        rule = CppSanitizerCiRule()
        result = rule.evaluate([], context=None)
        assert result.skipped

    def test_green_with_tsan_step(self) -> None:
        rule = CppSanitizerCiRule()
        ev = _make_evidence(
            "ci-pipeline",
            {"step_names": ["Run TSAN checks"], "job_names": ["ci"]},
            collector_name="ci-artifact",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
