"""Tests for Mermaid diagram integration in markdown reports."""

from __future__ import annotations

from nfr_review.engine import RunResult
from nfr_review.models import Finding, RuleResult, RunMetadata
from nfr_review.output.markdown import render_markdown_report


def _make_finding(severity: str = "medium", **overrides: object) -> Finding:
    defaults: dict[str, object] = {
        "rule_id": "TEST-001",
        "rag": "amber",
        "severity": severity,
        "summary": "test finding",
        "recommendation": "fix it",
        "evidence_locator": "test.py:1",
        "collector_name": "test",
        "collector_version": "1.0",
        "confidence": 0.9,
        "pattern_tag": "test-tag",
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


def _make_metadata() -> RunMetadata:
    return RunMetadata(
        tool_version="0.1.0",
        target_repo="/repos/sample",
        timestamp="2026-01-01T00:00:00Z",
        git_sha="abc1234",
        git_branch="main",
        git_dirty=False,
    )


def _make_result(
    findings: list[Finding] | None = None,
) -> RunResult:
    findings = findings or []
    return RunResult(
        findings=findings,
        rule_results=[
            RuleResult(rule_id="TEST-001", findings=findings),
        ],
        run_metadata=_make_metadata(),
        warnings=[],
    )


class TestDiagramsInReport:
    def test_diagrams_embedded_as_mermaid_blocks(self) -> None:
        result = _make_result([_make_finding(severity="high")])
        diagrams = {
            "Severity Distribution": 'pie title Severity Distribution\n    "High" : 1\n',
        }
        md = render_markdown_report(
            nfr_result=result,
            diagrams=diagrams,
        )
        assert "## Diagrams" in md
        assert "### Severity Distribution" in md
        assert "```mermaid" in md
        assert "pie title Severity Distribution" in md
        assert "```" in md

    def test_multiple_diagrams(self) -> None:
        result = _make_result([_make_finding()])
        diagrams = {
            "Severity Distribution": "pie title Test\n",
            "Technology Overview": "flowchart LR\n    scan[Scan]\n",
        }
        md = render_markdown_report(
            nfr_result=result,
            diagrams=diagrams,
        )
        assert "### Severity Distribution" in md
        assert "### Technology Overview" in md
        assert md.count("```mermaid") == 2

    def test_no_diagrams_when_none(self) -> None:
        result = _make_result([_make_finding()])
        md = render_markdown_report(
            nfr_result=result,
            diagrams=None,
        )
        assert "## Diagrams" not in md
        assert "```mermaid" not in md

    def test_no_diagrams_when_empty_dict(self) -> None:
        result = _make_result([_make_finding()])
        md = render_markdown_report(
            nfr_result=result,
            diagrams={},
        )
        assert "## Diagrams" not in md

    def test_empty_diagram_content_skipped(self) -> None:
        result = _make_result([_make_finding()])
        diagrams = {
            "Severity Distribution": "pie title Test\n",
            "Empty Section": "",
        }
        md = render_markdown_report(
            nfr_result=result,
            diagrams=diagrams,
        )
        assert "### Severity Distribution" in md
        assert "### Empty Section" not in md
        assert md.count("```mermaid") == 1

    def test_whitespace_only_diagram_skipped(self) -> None:
        result = _make_result([_make_finding()])
        diagrams = {"Blank": "   \n  \n  "}
        md = render_markdown_report(
            nfr_result=result,
            diagrams=diagrams,
        )
        assert "### Blank" not in md
        assert "```mermaid" not in md

    def test_diagrams_appear_after_summary_before_findings(self) -> None:
        result = _make_result([_make_finding(severity="high")])
        diagrams = {"Test Diagram": "pie title Test\n"}
        md = render_markdown_report(
            nfr_result=result,
            diagrams=diagrams,
        )
        summary_pos = md.index("Overall Summary")
        diagram_pos = md.index("## Diagrams")
        findings_pos = md.index("Source Code Findings")
        assert summary_pos < diagram_pos < findings_pos

    def test_backward_compatible_without_diagrams_kwarg(self) -> None:
        result = _make_result([_make_finding()])
        md = render_markdown_report(nfr_result=result)
        assert "## Diagrams" not in md
        assert "```mermaid" not in md
        assert "Overall Summary" in md
