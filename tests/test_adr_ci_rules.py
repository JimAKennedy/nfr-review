"""Tests for ADR and CI Band 1 rules — positive, negative, and no-evidence cases."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.adr_lifecycle import AdrLifecycleGapRule
from nfr_review.rules.ci_security_scan import CiSecurityScanMissingRule
from nfr_review.rules.ci_test_stage import CiTestStageMissingRule


def _adr_evidence(status: str | None, file_path: str = "docs/adr/0001.md") -> Evidence:
    return Evidence(
        collector_name="adr",
        collector_version="0.1.0",
        locator=file_path,
        kind="adr-document",
        payload={
            "file_path": file_path,
            "title": "Test ADR",
            "status": status,
            "date": "2024-01-01",
            "superseded_by": None,
            "has_frontmatter": True,
        },
    )


def _ci_evidence(
    has_test: bool, has_security: bool, file_path: str = ".github/workflows/ci.yml"
) -> Evidence:
    return Evidence(
        collector_name="ci-artifact",
        collector_version="0.1.0",
        locator=file_path,
        kind="ci-pipeline",
        payload={
            "file_path": file_path,
            "ci_system": "github-actions",
            "has_test_step": has_test,
            "has_security_scan": has_security,
            "job_names": ["build"],
            "step_names": ["Build"],
        },
    )


class TestAdrLifecycleGapRule:
    def setup_method(self) -> None:
        self.rule = AdrLifecycleGapRule()

    def test_green_when_all_have_status(self) -> None:
        evidence = [
            _adr_evidence("accepted", "docs/adr/0001.md"),
            _adr_evidence("superseded", "docs/adr/0002.md"),
        ]
        result = self.rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_amber_when_some_lack_status(self) -> None:
        evidence = [
            _adr_evidence("accepted", "docs/adr/0001.md"),
            _adr_evidence(None, "docs/adr/0002.md"),
        ]
        result = self.rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"

    def test_red_when_none_have_status(self) -> None:
        evidence = [
            _adr_evidence(None, "docs/adr/0001.md"),
            _adr_evidence(None, "docs/adr/0002.md"),
        ]
        result = self.rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings[0].rag == "red"

    def test_skipped_when_no_evidence(self) -> None:
        result = self.rule.evaluate([], context=None)
        assert result.skipped
        assert "no ADR evidence" in (result.skip_reason or "")


class TestCiSecurityScanMissingRule:
    def setup_method(self) -> None:
        self.rule = CiSecurityScanMissingRule()

    def test_green_when_security_scan_present(self) -> None:
        evidence = [_ci_evidence(has_test=True, has_security=True)]
        result = self.rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_red_when_no_security_scan(self) -> None:
        evidence = [
            _ci_evidence(has_test=True, has_security=False),
            _ci_evidence(
                has_test=False,
                has_security=False,
                file_path=".github/workflows/deploy.yml",
            ),
        ]
        result = self.rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings[0].rag == "red"

    def test_skipped_when_no_evidence(self) -> None:
        result = self.rule.evaluate([], context=None)
        assert result.skipped
        assert "no CI pipeline evidence" in (result.skip_reason or "")


class TestCiTestStageMissingRule:
    def setup_method(self) -> None:
        self.rule = CiTestStageMissingRule()

    def test_green_when_test_step_present(self) -> None:
        evidence = [_ci_evidence(has_test=True, has_security=False)]
        result = self.rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_red_when_no_test_step(self) -> None:
        evidence = [
            _ci_evidence(has_test=False, has_security=True),
            _ci_evidence(
                has_test=False,
                has_security=False,
                file_path=".github/workflows/deploy.yml",
            ),
        ]
        result = self.rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings[0].rag == "red"

    def test_green_when_cmake_test_signals_only(self) -> None:
        ci_ev = _ci_evidence(has_test=False, has_security=False)
        cmake_ev = Evidence(
            collector_name="ci-artifact",
            collector_version="0.1.0",
            locator="cmake-test-signals",
            kind="cmake-test-signals",
            payload={
                "has_test_framework": True,
                "files": [
                    {
                        "file_path": "CMakeLists.txt",
                        "signals": ["enable_testing", "add_test"],
                    }
                ],
            },
        )
        result = self.rule.evaluate([ci_ev, cmake_ev], context=None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert result.findings[0].evidence_locator == "CMakeLists.txt"

    def test_skipped_when_no_ci_evidence(self) -> None:
        result = self.rule.evaluate([], context=None)
        assert result.skipped
        assert "no CI pipeline evidence" in (result.skip_reason or "")
