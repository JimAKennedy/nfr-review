"""C++ integration tests — full pipeline through Engine with all C++ collectors and rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.ci_artifact import CiArtifactCollector
from nfr_review.collectors.cmake import CmakeCollector
from nfr_review.collectors.cpp_ast import CppAstCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.cmake_build_config import CmakeBuildConfigRule
from nfr_review.rules.cmake_fetchcontent_pinning import CmakeFetchcontentPinningRule
from nfr_review.rules.cmake_minimum_version import CmakeMinimumVersionRule
from nfr_review.rules.cpp_clang_format import CppClangFormatRule
from nfr_review.rules.cpp_clang_tidy import CppClangTidyRule
from nfr_review.rules.cpp_exception_safety import CppExceptionSafetyRule
from nfr_review.rules.cpp_include_guards import CppIncludeGuardsRule
from nfr_review.rules.cpp_raw_memory import CppRawMemoryRule
from nfr_review.rules.cpp_sanitizer_ci import CppSanitizerCiRule
from nfr_review.rules.sample import ReadmeExistsRule

FIXTURE = Path(__file__).parent / "fixtures" / "cpp-integration-repo"

CMAKE_RULE_IDS = {
    "cmake-minimum-version",
    "cmake-fetchcontent-pinning",
    "cmake-build-config",
}

CPP_RULE_IDS = {
    "cpp-raw-memory",
    "cpp-include-guards",
    "cpp-exception-safety",
}

TOOL_RULE_IDS = {
    "cpp-clang-format",
    "cpp-clang-tidy",
    "cpp-sanitizer-ci",
}

ALL_CPP_RULE_IDS = CMAKE_RULE_IDS | CPP_RULE_IDS | TOOL_RULE_IDS


def _cpp_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("cmake", CmakeCollector())
    cregistry.register("cpp-ast", CppAstCollector())
    cregistry.register("ci-artifact", CiArtifactCollector())
    cregistry.register("repo-structure", RepoStructureCollector())

    for rule_id, rule_cls in [
        ("cmake-minimum-version", CmakeMinimumVersionRule),
        ("cmake-fetchcontent-pinning", CmakeFetchcontentPinningRule),
        ("cmake-build-config", CmakeBuildConfigRule),
        ("cpp-raw-memory", CppRawMemoryRule),
        ("cpp-include-guards", CppIncludeGuardsRule),
        ("cpp-exception-safety", CppExceptionSafetyRule),
        ("cpp-clang-format", CppClangFormatRule),
        ("cpp-clang-tidy", CppClangTidyRule),
        ("cpp-sanitizer-ci", CppSanitizerCiRule),
        ("sample-readme-exists", ReadmeExistsRule),
    ]:
        rregistry.register(rule_id, rule_cls())

    return cregistry, rregistry


class TestCppPipelineEndToEnd:
    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _cpp_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"cpp": True})
        return engine.run(target=FIXTURE, config=cfg)

    def test_all_cpp_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert ALL_CPP_RULE_IDS <= run_set

    def test_no_rules_skipped_unexpectedly(self, result: RunResult) -> None:
        skipped = {rr.rule_id for rr in result.rule_results if rr.skipped}
        assert not (ALL_CPP_RULE_IDS & skipped), (
            f"Unexpected skips: {ALL_CPP_RULE_IDS & skipped}"
        )

    def test_cmake_minimum_version_green(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "cmake-minimum-version"]
        assert any(f.rag == "green" for f in findings)

    def test_fetchcontent_unpinned_detected(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "cmake-fetchcontent-pinning"]
        assert any(f.rag in ("amber", "red") for f in findings)
        assert any(
            "spdlog" in f.summary.lower() or "unpinned" in f.summary.lower() for f in findings
        )

    def test_raw_memory_detected(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "cpp-raw-memory"]
        tags = {f.pattern_tag for f in findings}
        assert "cpp-raw-new" in tags
        assert "cpp-raw-delete" in tags
        assert "cpp-malloc-usage" in tags

    def test_include_guard_missing(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "cpp-include-guards"]
        missing = [f for f in findings if f.pattern_tag == "cpp-missing-include-guard"]
        assert len(missing) >= 1
        assert any("legacy" in f.evidence_locator.lower() for f in missing)

    def test_exception_safety_catch_all(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "cpp-exception-safety"]
        assert any(f.pattern_tag == "cpp-catch-all-silent" for f in findings)

    def test_clang_format_green(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "cpp-clang-format"]
        assert any(f.rag == "green" for f in findings)

    def test_clang_tidy_green(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "cpp-clang-tidy"]
        assert any(f.rag == "green" for f in findings)

    def test_sanitizer_ci_green(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "cpp-sanitizer-ci"]
        assert any(f.rag == "green" for f in findings)

    def test_readme_exists_green(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "sample-readme-exists"]
        assert any(f.rag == "green" for f in findings)

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert len(result.warnings) == 0, f"Engine warnings: {result.warnings}"

    def test_findings_have_valid_pattern_tags(self, result: RunResult) -> None:
        for f in result.findings:
            assert f.pattern_tag, f"Finding {f.rule_id} missing pattern_tag"
            assert f.confidence > 0, f"Finding {f.rule_id} has zero confidence"
