# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for C++ tool detection in CI rules and collectors."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.ci_artifact import _has_security_in_text
from nfr_review.hygiene.rules.ci_has_lint import CiHasLintRule
from nfr_review.models import Evidence


def _make_ci_evidence(payload: dict[str, Any]) -> list[Evidence]:
    return [
        Evidence(
            collector_name="ci-automation",
            collector_version="0.1.0",
            locator=".",
            kind="ci-automation-analysis",
            payload=payload,
        )
    ]


def _ci_payload(steps: list[str], *, has_ci: bool = True) -> dict[str, Any]:
    return {
        "ci_systems": ["github-actions"],
        "configs": [
            {
                "path": ".github/workflows/ci.yml",
                "provider": "github-actions",
                "raw_content_length": 100,
                "jobs": ["build"],
                "steps": steps,
            }
        ],
        "has_ci": has_ci,
    }


class TestCppLintDetection:
    def test_clang_format_detected(self) -> None:
        ev = _make_ci_evidence(_ci_payload(["run clang-format --check src/"]))
        rule = CiHasLintRule()
        result = rule.evaluate(ev, context=None)
        assert result.findings[0].rag == "green"

    def test_clang_tidy_detected(self) -> None:
        ev = _make_ci_evidence(_ci_payload(["run-clang-tidy src/"]))
        rule = CiHasLintRule()
        result = rule.evaluate(ev, context=None)
        assert result.findings[0].rag == "green"

    def test_cppcheck_detected(self) -> None:
        ev = _make_ci_evidence(_ci_payload(["cppcheck --enable=all src/"]))
        rule = CiHasLintRule()
        result = rule.evaluate(ev, context=None)
        assert result.findings[0].rag == "green"

    def test_cpplint_detected(self) -> None:
        ev = _make_ci_evidence(_ci_payload(["cpplint src/*.cpp"]))
        rule = CiHasLintRule()
        result = rule.evaluate(ev, context=None)
        assert result.findings[0].rag == "green"

    def test_include_what_you_use_detected(self) -> None:
        ev = _make_ci_evidence(_ci_payload(["include-what-you-use main.cpp"]))
        rule = CiHasLintRule()
        result = rule.evaluate(ev, context=None)
        assert result.findings[0].rag == "green"

    def test_no_cpp_lint_still_amber(self) -> None:
        ev = _make_ci_evidence(_ci_payload(["cmake --build . --target all"]))
        rule = CiHasLintRule()
        result = rule.evaluate(ev, context=None)
        assert result.findings[0].rag == "amber"


class TestCppSecurityKeywords:
    def test_clang_tidy_detected(self) -> None:
        assert _has_security_in_text("run-clang-tidy -checks='*' src/")

    def test_fsanitize_address_detected(self) -> None:
        assert _has_security_in_text("g++ -fsanitize=address -o test main.cpp")

    def test_asan_detected(self) -> None:
        assert _has_security_in_text("ASAN_OPTIONS=detect_leaks=1 ./test")

    def test_tsan_detected(self) -> None:
        assert _has_security_in_text("TSAN_OPTIONS=halt_on_error=1 ./test")

    def test_ubsan_detected(self) -> None:
        assert _has_security_in_text("cmake -DCMAKE_CXX_FLAGS=-fsanitize=undefined ubsan")

    def test_addresssanitizer_detected(self) -> None:
        assert _has_security_in_text("AddressSanitizer: heap-buffer-overflow")

    def test_threadsanitizer_detected(self) -> None:
        assert _has_security_in_text("ThreadSanitizer: data race detected")

    def test_gitleaks_detected(self) -> None:
        assert _has_security_in_text("gitleaks detect --source .")

    def test_plain_cmake_build_not_detected(self) -> None:
        assert not _has_security_in_text("cmake --build . --target all")
