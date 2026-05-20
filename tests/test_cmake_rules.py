"""Tests for CMake collector and CMAKE-* rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.cmake import CmakeCollector
from nfr_review.models import Evidence
from nfr_review.rules.cmake_build_config import CmakeBuildConfigRule
from nfr_review.rules.cmake_fetchcontent_pinning import CmakeFetchcontentPinningRule
from nfr_review.rules.cmake_minimum_version import CmakeMinimumVersionRule

GOOD_REPO = Path(__file__).parent / "fixtures" / "cmake-good-repo"
BAD_REPO = Path(__file__).parent / "fixtures" / "cmake-bad-repo"
MIXED_REPO = Path(__file__).parent / "fixtures" / "cmake-fetchcontent-repo"


@pytest.fixture()
def collector() -> CmakeCollector:
    return CmakeCollector()


@pytest.fixture()
def good_evidence(collector: CmakeCollector) -> list[Evidence]:
    return collector.collect(GOOD_REPO, config=None)


@pytest.fixture()
def bad_evidence(collector: CmakeCollector) -> list[Evidence]:
    return collector.collect(BAD_REPO, config=None)


@pytest.fixture()
def mixed_evidence(collector: CmakeCollector) -> list[Evidence]:
    return collector.collect(MIXED_REPO, config=None)


class TestCmakeCollector:
    def test_collects_from_good_repo(self, good_evidence: list[Evidence]) -> None:
        assert len(good_evidence) == 1
        assert good_evidence[0].kind == "cmake-config"

    def test_extracts_cmake_minimum_required(self, good_evidence: list[Evidence]) -> None:
        payload = good_evidence[0].payload
        assert payload["cmake_minimum_required"] == "3.21"

    def test_extracts_project_info(self, good_evidence: list[Evidence]) -> None:
        payload = good_evidence[0].payload
        assert payload["project_name"] == "GoodProject"
        assert payload["project_version"] == "1.0.0"

    def test_extracts_fetchcontent(self, good_evidence: list[Evidence]) -> None:
        payload = good_evidence[0].payload
        declares = payload["fetchcontent_declares"]
        assert len(declares) == 2
        names = {d["name"] for d in declares}
        assert "googletest" in names
        assert "fmt" in names

    def test_pinned_detection(self, good_evidence: list[Evidence]) -> None:
        payload = good_evidence[0].payload
        for dep in payload["fetchcontent_declares"]:
            assert dep["is_pinned"] is True

    def test_unpinned_detection(self, bad_evidence: list[Evidence]) -> None:
        payload = bad_evidence[0].payload
        for dep in payload["fetchcontent_declares"]:
            assert dep["is_pinned"] is False

    def test_target_features(self, good_evidence: list[Evidence]) -> None:
        payload = good_evidence[0].payload
        assert payload["has_target_compile_features"] is True
        assert payload["has_target_compile_options"] is True

    def test_global_flags_detection(self, bad_evidence: list[Evidence]) -> None:
        payload = bad_evidence[0].payload
        assert payload["has_global_cmake_flags"] is True

    def test_install_detection(self, good_evidence: list[Evidence]) -> None:
        payload = good_evidence[0].payload
        assert payload["has_install_targets"] is True

    def test_no_install_in_bad(self, bad_evidence: list[Evidence]) -> None:
        payload = bad_evidence[0].payload
        assert payload["has_install_targets"] is False

    def test_missing_cmake_minimum(self, bad_evidence: list[Evidence]) -> None:
        payload = bad_evidence[0].payload
        assert payload["cmake_minimum_required"] is None

    def test_mixed_pinning(self, mixed_evidence: list[Evidence]) -> None:
        payload = mixed_evidence[0].payload
        declares = payload["fetchcontent_declares"]
        pinned = [d for d in declares if d["is_pinned"]]
        unpinned = [d for d in declares if not d["is_pinned"]]
        assert len(pinned) >= 1
        assert len(unpinned) >= 1


class TestCmakeMinimumVersion:
    def test_good_repo_green(self, good_evidence: list[Evidence]) -> None:
        rule = CmakeMinimumVersionRule()
        result = rule.evaluate(good_evidence, context=None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_bad_repo_red(self, bad_evidence: list[Evidence]) -> None:
        rule = CmakeMinimumVersionRule()
        result = rule.evaluate(bad_evidence, context=None)
        assert not result.skipped
        red_findings = [f for f in result.findings if f.rag == "red"]
        assert len(red_findings) >= 1
        assert "missing" in red_findings[0].summary.lower()

    def test_no_evidence_skipped(self) -> None:
        rule = CmakeMinimumVersionRule()
        result = rule.evaluate([], context=None)
        assert result.skipped


class TestFetchcontentPinning:
    def test_good_repo_green(self, good_evidence: list[Evidence]) -> None:
        rule = CmakeFetchcontentPinningRule()
        result = rule.evaluate(good_evidence, context=None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_bad_repo_findings(self, bad_evidence: list[Evidence]) -> None:
        rule = CmakeFetchcontentPinningRule()
        result = rule.evaluate(bad_evidence, context=None)
        assert not result.skipped
        bad_findings = [f for f in result.findings if f.rag in ("red", "amber")]
        assert len(bad_findings) >= 2

    def test_mixed_repo_partial(self, mixed_evidence: list[Evidence]) -> None:
        rule = CmakeFetchcontentPinningRule()
        result = rule.evaluate(mixed_evidence, context=None)
        assert not result.skipped
        bad_findings = [f for f in result.findings if f.rag in ("red", "amber")]
        assert len(bad_findings) >= 1

    def test_no_evidence_skipped(self) -> None:
        rule = CmakeFetchcontentPinningRule()
        result = rule.evaluate([], context=None)
        assert result.skipped


class TestBuildConfig:
    def test_good_repo_green(self, good_evidence: list[Evidence]) -> None:
        rule = CmakeBuildConfigRule()
        result = rule.evaluate(good_evidence, context=None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_bad_repo_findings(self, bad_evidence: list[Evidence]) -> None:
        rule = CmakeBuildConfigRule()
        result = rule.evaluate(bad_evidence, context=None)
        assert not result.skipped
        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) >= 1

    def test_bad_repo_detects_global_flags(self, bad_evidence: list[Evidence]) -> None:
        rule = CmakeBuildConfigRule()
        result = rule.evaluate(bad_evidence, context=None)
        tags = {f.pattern_tag for f in result.findings}
        assert "cmake-global-flags" in tags

    def test_bad_repo_detects_missing_version(self, bad_evidence: list[Evidence]) -> None:
        rule = CmakeBuildConfigRule()
        result = rule.evaluate(bad_evidence, context=None)
        tags = {f.pattern_tag for f in result.findings}
        assert "cmake-no-project-version" in tags

    def test_no_evidence_skipped(self) -> None:
        rule = CmakeBuildConfigRule()
        result = rule.evaluate([], context=None)
        assert result.skipped
