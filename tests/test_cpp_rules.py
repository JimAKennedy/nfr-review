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

    def test_suppresses_ownership_transfer_call(self) -> None:
        rule = CppRawMemoryRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "ui.cpp",
                "new_expressions": [
                    {
                        "line": 10,
                        "file": "ui.cpp",
                        "expression": 'new CTextLabel(CRect(), "Hi")',
                        "parent_call": "addView",
                        "line_comment": "",
                    },
                ],
                "delete_expressions": [],
                "smart_pointers": [],
                "malloc_calls": [],
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-raw-new-suppressed"

    def test_suppresses_refcount_safe_comment(self) -> None:
        rule = CppRawMemoryRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "ui.cpp",
                "new_expressions": [
                    {
                        "line": 20,
                        "file": "ui.cpp",
                        "expression": "new CView()",
                        "parent_call": "",
                        "line_comment": "REFCOUNT-SAFE: transferred to framework",
                    },
                ],
                "delete_expressions": [],
                "smart_pointers": [],
                "malloc_calls": [],
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-raw-new-suppressed"

    def test_suppresses_nolint_comment(self) -> None:
        rule = CppRawMemoryRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "ui.cpp",
                "new_expressions": [
                    {
                        "line": 30,
                        "file": "ui.cpp",
                        "expression": "new Foo()",
                        "parent_call": "",
                        "line_comment": "NOLINT",
                    },
                ],
                "delete_expressions": [],
                "smart_pointers": [],
                "malloc_calls": [],
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-raw-new-suppressed"

    def test_does_not_suppress_unknown_call(self) -> None:
        rule = CppRawMemoryRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "ui.cpp",
                "new_expressions": [
                    {
                        "line": 40,
                        "file": "ui.cpp",
                        "expression": "new int(42)",
                        "parent_call": "doSomething",
                        "line_comment": "",
                    },
                ],
                "delete_expressions": [],
                "smart_pointers": [],
                "malloc_calls": [],
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].pattern_tag == "cpp-raw-new"

    def test_suppresses_qualified_call_name(self) -> None:
        """Qualified names like FObject::createInstance are stripped to bare name."""
        rule = CppRawMemoryRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "ui.cpp",
                "new_expressions": [
                    {
                        "line": 10,
                        "file": "ui.cpp",
                        "expression": "new FObject()",
                        "parent_call": "createInstance",
                        "line_comment": "",
                    },
                ],
                "delete_expressions": [],
                "smart_pointers": [],
                "malloc_calls": [],
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-raw-new-suppressed"

    def test_backward_compat_no_new_fields(self) -> None:
        """Evidence from older collector versions without parent_call/line_comment."""
        rule = CppRawMemoryRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {
                "file_path": "old.cpp",
                "new_expressions": [
                    {"line": 5, "file": "old.cpp", "expression": "new int(1)"},
                ],
                "delete_expressions": [],
                "smart_pointers": [],
                "malloc_calls": [],
            },
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].pattern_tag == "cpp-raw-new"


# ---------------------------------------------------------------------------
# CPP-001: Raw Memory — live fixture (vstgui_refcount.cpp via collector)
# ---------------------------------------------------------------------------
class TestCppRawMemoryRefcount:
    @pytest.fixture()
    def refcount_evidence(self, collector: CppAstCollector) -> list[Evidence]:
        return collector.collect(AST_FIXTURES, config=None)

    def test_fixture_has_suppressed_and_unsuppressed(
        self, refcount_evidence: list[Evidence]
    ) -> None:
        rule = CppRawMemoryRule()
        result = rule.evaluate(refcount_evidence, context=None)
        tags = [f.pattern_tag for f in result.findings]
        assert "cpp-raw-new-suppressed" in tags, (
            "ownership-transfer patterns should be suppressed"
        )
        assert "cpp-raw-new" in tags, "plain raw new should still fire"

    def test_scope_analysis_sets_parent_call(self, collector: CppAstCollector) -> None:
        """Declare-then-pass populates parent_call via scope analysis."""
        evidence = collector.collect(AST_FIXTURES, config=None)
        vstgui_ev = [
            e
            for e in evidence
            if e.payload.get("file_path", "").endswith("vstgui_refcount.cpp")
        ]
        assert vstgui_ev
        new_exprs = vstgui_ev[0].payload["new_expressions"]
        scope_hits = [
            n
            for n in new_exprs
            if n.get("parent_call") in ("addView", "replaceView") and not n.get("line_comment")
        ]
        assert len(scope_hits) >= 2, (
            f"expected >=2 scope-resolved parent_calls, got {len(scope_hits)}: "
            f"{[(n['line'], n['parent_call']) for n in scope_hits]}"
        )

    def test_addview_new_is_suppressed(self, refcount_evidence: list[Evidence]) -> None:
        vstgui_ev = [
            e
            for e in refcount_evidence
            if e.payload.get("file_path", "").endswith("vstgui_refcount.cpp")
        ]
        assert vstgui_ev, "vstgui_refcount.cpp fixture should produce evidence"
        rule = CppRawMemoryRule()
        result = rule.evaluate(vstgui_ev, context=None)
        suppressed = [f for f in result.findings if f.pattern_tag == "cpp-raw-new-suppressed"]
        unsuppressed = [f for f in result.findings if f.pattern_tag == "cpp-raw-new"]
        assert len(suppressed) >= 11, f"expected >=11 suppressed, got {len(suppressed)}"
        assert len(unsuppressed) >= 2, f"expected >=2 unsuppressed, got {len(unsuppressed)}"

    def test_member_assignment_then_addview(self, collector: CppAstCollector) -> None:
        """Sub-pattern 1: member_ = new T(...); addView(member_);"""
        evidence = collector.collect(AST_FIXTURES, config=None)
        vstgui_ev = [
            e
            for e in evidence
            if e.payload.get("file_path", "").endswith("vstgui_refcount.cpp")
        ]
        new_exprs = vstgui_ev[0].payload["new_expressions"]
        member_hits = [
            n
            for n in new_exprs
            if n["expression"].startswith("new CTextLabel")
            and n["parent_call"] == "addView"
            and n["line"] >= 55
        ]
        assert len(member_hits) >= 1, (
            "member assignment → addView should set parent_call='addView'"
        )

    def test_return_from_factory_method(self, collector: CppAstCollector) -> None:
        """Sub-pattern 2: auto* e = new T(...); return e; in createView()."""
        evidence = collector.collect(AST_FIXTURES, config=None)
        vstgui_ev = [
            e
            for e in evidence
            if e.payload.get("file_path", "").endswith("vstgui_refcount.cpp")
        ]
        new_exprs = vstgui_ev[0].payload["new_expressions"]
        factory_hit = [n for n in new_exprs if n["parent_call"] == "createView"]
        assert len(factory_hit) == 1, (
            "new in return-from-factory should set parent_call='createView'"
        )

    def test_static_cast_in_create_instance(self, collector: CppAstCollector) -> None:
        """Sub-pattern 3: return static_cast<T*>(new U()) in createInstance()."""
        evidence = collector.collect(AST_FIXTURES, config=None)
        vstgui_ev = [
            e
            for e in evidence
            if e.payload.get("file_path", "").endswith("vstgui_refcount.cpp")
        ]
        new_exprs = vstgui_ev[0].payload["new_expressions"]
        cast_hit = [n for n in new_exprs if n["parent_call"] == "createInstance"]
        assert len(cast_hit) == 1, (
            "new inside static_cast in createInstance should set parent_call='createInstance'"
        )


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
            collector_name="cpp-ast",
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
            collector_name="cpp-ast",
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
            collector_name="cpp-ast",
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
            collector_name="cpp-ast",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-exception-safety-ok"

    def test_green_no_catch_blocks(self) -> None:
        rule = CppExceptionSafetyRule()
        ev = _make_evidence(
            "cpp-ast-file",
            {"file_path": "clean.cpp", "catch_blocks": []},
            collector_name="cpp-ast",
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
            {
                "top_level_files": [".clang-format", "src/main.cpp"],
                "top_level_dirs": [],
                "has_readme": False,
                "has_git_dir": False,
                "has_pyproject": False,
            },
            collector_name="repo-structure",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-clang-format-present"

    def test_amber_when_missing(self) -> None:
        rule = CppClangFormatRule()
        ev = _make_evidence(
            "repo-structure-summary",
            {
                "top_level_files": ["src/main.cpp", "CMakeLists.txt"],
                "top_level_dirs": [],
                "has_readme": False,
                "has_git_dir": False,
                "has_pyproject": False,
            },
            collector_name="repo-structure",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].pattern_tag == "cpp-clang-format-missing"

    def test_recognises_underscore_variant(self) -> None:
        rule = CppClangFormatRule()
        ev = _make_evidence(
            "repo-structure-summary",
            {
                "top_level_files": ["_clang-format"],
                "top_level_dirs": [],
                "has_readme": False,
                "has_git_dir": False,
                "has_pyproject": False,
            },
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
            {
                "top_level_files": [".clang-tidy", "src/main.cpp"],
                "top_level_dirs": [],
                "has_readme": False,
                "has_git_dir": False,
                "has_pyproject": False,
            },
            collector_name="repo-structure",
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-clang-tidy-present"

    def test_amber_when_missing(self) -> None:
        rule = CppClangTidyRule()
        ev = _make_evidence(
            "repo-structure-summary",
            {
                "top_level_files": ["src/main.cpp"],
                "top_level_dirs": [],
                "has_readme": False,
                "has_git_dir": False,
                "has_pyproject": False,
            },
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
