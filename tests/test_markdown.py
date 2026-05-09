"""Tests for markdown report renderer (M008 S02)."""

from __future__ import annotations

from dataclasses import dataclass, field

from nfr_review.models import Finding, RuleResult, RunMetadata
from nfr_review.output.markdown import render_markdown_report
from nfr_review.output.pytest_runner import PytestResult


def _finding(
    *,
    rule_id: str = "test-rule",
    rag: str = "amber",
    severity: str = "medium",
    evidence_locator: str = "src/app.py",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rag=rag,
        severity=severity,
        summary=f"Finding in {evidence_locator}",
        recommendation="Fix it",
        evidence_locator=evidence_locator,
        collector_name="test-collector",
        collector_version="0.1.0",
        confidence=0.8,
        pattern_tag="test-pattern",
    )


def _metadata() -> RunMetadata:
    return RunMetadata(
        tool_version="1.0.0",
        target_repo="/home/user/project",
        git_sha="abc1234",
        git_branch="main",
        git_dirty=False,
        timestamp="2026-05-09T12:00:00Z",
        collector_versions={"repo_structure": "0.1.0"},
        rules_run=["test-rule"],
        rules_skipped=[],
    )


@dataclass
class FakeRunResult:
    findings: list[Finding] = field(default_factory=list)
    rule_results: list[RuleResult] = field(default_factory=list)
    run_metadata: RunMetadata | None = None
    warnings: list[str] = field(default_factory=list)


class TestRenderMarkdownReport:
    """Tests for render_markdown_report output structure."""

    def test_empty_report_has_header(self) -> None:
        result = FakeRunResult(run_metadata=_metadata())
        md = render_markdown_report(nfr_result=result)  # type: ignore[arg-type]
        assert md.startswith("# NFR Review Report")
        assert "## Provenance" in md
        assert "1.0.0" in md
        assert "abc1234" in md

    def test_custom_title(self) -> None:
        result = FakeRunResult(run_metadata=_metadata())
        md = render_markdown_report(nfr_result=result, title="Custom Report")  # type: ignore[arg-type]
        assert md.startswith("# Custom Report")

    def test_provenance_includes_git_info(self) -> None:
        result = FakeRunResult(run_metadata=_metadata())
        md = render_markdown_report(nfr_result=result)  # type: ignore[arg-type]
        assert "**Git SHA:** `abc1234`" in md
        assert "**Branch:** main" in md
        assert "**Target:** `/home/user/project`" in md

    def test_dirty_repo_noted(self) -> None:
        meta = _metadata()
        meta = RunMetadata(
            **{**meta.model_dump(), "git_dirty": True},
        )
        result = FakeRunResult(run_metadata=meta)
        md = render_markdown_report(nfr_result=result)  # type: ignore[arg-type]
        assert "(dirty)" in md

    def test_findings_partitioned_correctly(self) -> None:
        findings = [
            _finding(evidence_locator="src/engine.py", rag="red", severity="high"),
            _finding(evidence_locator="tests/test_engine.py", rag="amber", severity="medium"),
        ]
        result = FakeRunResult(findings=findings, run_metadata=_metadata())
        md = render_markdown_report(nfr_result=result)  # type: ignore[arg-type]
        assert "## Source Code Findings" in md
        assert "## Test Code Findings" in md
        source_section = md.split("## Source Code Findings")[1]
        source_section = source_section.split("## Test Code Findings")[0]
        assert "src/engine.py" in source_section
        test_section = md.split("## Test Code Findings")[1]
        assert "tests/test_engine.py" in test_section

    def test_summary_tables_present(self) -> None:
        findings = [
            _finding(rag="red", severity="high"),
            _finding(rag="amber", severity="medium"),
        ]
        result = FakeRunResult(findings=findings, run_metadata=_metadata())
        md = render_markdown_report(nfr_result=result)  # type: ignore[arg-type]
        assert "### Overall Summary" in md
        assert "### Source Code Summary" in md
        assert "### Test Code Summary" in md
        assert "| RAG | Critical | High | Medium | Low | Info | Total |" in md

    def test_test_results_passed(self) -> None:
        result = FakeRunResult(run_metadata=_metadata())
        pytest_result = PytestResult(passed=10, failed=0, duration_seconds=1.5)
        md = render_markdown_report(nfr_result=result, pytest_result=pytest_result)  # type: ignore[arg-type]
        assert "PASSED" in md
        assert "| Passed | 10 |" in md
        assert "| Duration | 1.50s |" in md

    def test_test_results_failed(self) -> None:
        result = FakeRunResult(run_metadata=_metadata())
        pytest_result = PytestResult(passed=8, failed=2, duration_seconds=2.0)
        md = render_markdown_report(nfr_result=result, pytest_result=pytest_result)  # type: ignore[arg-type]
        assert "FAILED" in md
        assert "| Failed | 2 |" in md

    def test_test_results_not_performed(self) -> None:
        result = FakeRunResult(run_metadata=_metadata())
        md = render_markdown_report(nfr_result=result, pytest_result=None)  # type: ignore[arg-type]
        assert "Test execution was not performed" in md

    def test_test_results_error(self) -> None:
        result = FakeRunResult(run_metadata=_metadata())
        pytest_result = PytestResult(raw_output="pytest not found", exit_code=-1)
        md = render_markdown_report(nfr_result=result, pytest_result=pytest_result)  # type: ignore[arg-type]
        assert "pytest not found" in md

    def test_skipped_rules_rendered(self) -> None:
        meta = RunMetadata(
            **{
                **_metadata().model_dump(),
                "rules_skipped": [{"rule_id": "helm-probes", "reason": "no helm detected"}],
            },
        )
        result = FakeRunResult(run_metadata=meta)
        md = render_markdown_report(nfr_result=result)  # type: ignore[arg-type]
        assert "## Skipped Rules" in md
        assert "helm-probes" in md
        assert "no helm detected" in md

    def test_no_skipped_rules_section_when_empty(self) -> None:
        result = FakeRunResult(run_metadata=_metadata())
        md = render_markdown_report(nfr_result=result)  # type: ignore[arg-type]
        assert "## Skipped Rules" not in md

    def test_hygiene_findings_merged(self) -> None:
        nfr = FakeRunResult(
            findings=[_finding(evidence_locator="src/app.py")],
            run_metadata=_metadata(),
        )
        hygiene = FakeRunResult(
            findings=[_finding(rule_id="hygiene-rule", evidence_locator="README.md")],
            run_metadata=_metadata(),
        )
        md = render_markdown_report(nfr_result=nfr, hygiene_result=hygiene)  # type: ignore[arg-type]
        assert "hygiene-rule" in md
        assert "test-rule" in md

    def test_findings_grouped_by_rag(self) -> None:
        findings = [
            _finding(rag="red", severity="high", evidence_locator="src/a.py"),
            _finding(rag="amber", severity="medium", evidence_locator="src/b.py"),
            _finding(rag="red", severity="critical", evidence_locator="src/c.py"),
        ]
        result = FakeRunResult(findings=findings, run_metadata=_metadata())
        md = render_markdown_report(nfr_result=result)  # type: ignore[arg-type]
        source_section = md.split("## Source Code Findings")[1]
        source_section = source_section.split("## Test Code Findings")[0]
        red_pos = source_section.find("### RED")
        amber_pos = source_section.find("### AMBER")
        assert red_pos < amber_pos
