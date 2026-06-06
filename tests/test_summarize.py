"""Tests for LLM executive summary generation."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from nfr_review.engine import RunResult
from nfr_review.models import Finding, RunMetadata
from nfr_review.output.summarize import generate_executive_summary
from nfr_review.output.summary_models import ExecSummary


def _make_finding(
    rule_id: str = "TEST-001",
    severity: str = "medium",
    rag: str = "amber",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rag=rag,
        severity=severity,
        summary=f"Test finding for {rule_id}",
        recommendation="Fix it",
        evidence_locator="src/foo.py:10",
        collector_name="test-collector",
        collector_version="1.0",
        confidence=0.8,
        pattern_tag="test",
    )


def _make_run_result(findings: list[Finding] | None = None) -> RunResult:
    return RunResult(
        findings=findings or [_make_finding()],
        rule_results=[],
        run_metadata=RunMetadata(
            tool_version="0.1.0",
            target_repo="/tmp/test-repo",
            timestamp="2026-05-20T10:00:00Z",
            rules_run=["TEST-001"],
        ),
    )


_VALID_LLM_RESPONSE = json.dumps(
    {
        "verdict": "conditional",
        "verdict_explanation": (
            "The project has moderate issues that need attention before open-sourcing."
        ),
        "risk_highlights": [
            "3 high-severity findings in dependency management",
            "Missing license headers in 12 source files",
        ],
        "remediation_priorities": [
            {
                "title": "Update vulnerable dependencies",
                "urgency": "immediate",
                "description": "Dependencies with known CVEs need immediate update.",
            },
            {
                "title": "Add license headers",
                "urgency": "short-term",
                "description": "All source files need Apache-2.0 headers.",
            },
        ],
        "production_risks": (
            "The main production risk is outdated dependencies with known vulnerabilities."
        ),
        "open_source_readiness": (
            "The project is close to ready but needs license headers and dependency updates."
        ),
        "overall_score": 62,
    }
)


class TestGenerateExecSummary:
    def test_returns_none_when_no_api_key(self) -> None:
        import nfr_review.llm_client as _lc

        with (
            patch.dict(
                os.environ,
                {"ANTHROPIC_API_KEY": "", "NFR_LLM_BACKEND": "api"},
                clear=False,
            ),
            patch.object(_lc, "_ENV_LOADED", True),
        ):
            result = generate_executive_summary(_make_run_result())
        assert result is None

    def test_returns_exec_summary_on_valid_response(self) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = _VALID_LLM_RESPONSE

        with patch("nfr_review.output.summarize.create_llm_client", return_value=mock_client):
            result = generate_executive_summary(_make_run_result())

        assert result is not None
        assert isinstance(result, ExecSummary)
        assert result.verdict == "conditional"
        assert result.overall_score == 62
        assert len(result.remediation_priorities) == 2
        assert result.remediation_priorities[0].urgency == "immediate"

    def test_handles_code_fenced_response(self) -> None:
        fenced = f"```json\n{_VALID_LLM_RESPONSE}\n```"
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = fenced

        with patch("nfr_review.output.summarize.create_llm_client", return_value=mock_client):
            result = generate_executive_summary(_make_run_result())

        assert result is not None
        assert result.verdict == "conditional"

    def test_handles_prose_wrapped_response(self) -> None:
        wrapped = (
            "Here is my analysis of the project:\n\n"
            f"{_VALID_LLM_RESPONSE}\n\n"
            "Let me know if you need further details."
        )
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = wrapped

        with patch("nfr_review.output.summarize.create_llm_client", return_value=mock_client):
            result = generate_executive_summary(_make_run_result())

        assert result is not None
        assert result.verdict == "conditional"
        assert result.overall_score == 62

    def test_returns_none_on_invalid_json(self) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = "This is not JSON at all"

        with patch("nfr_review.output.summarize.create_llm_client", return_value=mock_client):
            result = generate_executive_summary(_make_run_result())

        assert result is None

    def test_returns_none_on_schema_violation(self) -> None:
        bad_response = json.dumps({"verdict": "maybe", "foo": "bar"})
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = bad_response

        with patch("nfr_review.output.summarize.create_llm_client", return_value=mock_client):
            result = generate_executive_summary(_make_run_result())

        assert result is None

    def test_returns_none_on_llm_exception(self) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.side_effect = RuntimeError("API down")

        with patch("nfr_review.output.summarize.create_llm_client", return_value=mock_client):
            result = generate_executive_summary(_make_run_result())

        assert result is None

    def test_includes_multiple_finding_severities(self) -> None:
        findings = [
            _make_finding("SEC-001", "critical", "red"),
            _make_finding("DEP-002", "high", "red"),
            _make_finding("DOC-003", "low", "green"),
        ]
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = _VALID_LLM_RESPONSE

        with patch("nfr_review.output.summarize.create_llm_client", return_value=mock_client):
            result = generate_executive_summary(_make_run_result(findings))

        assert result is not None
        call_args = mock_client.analyze.call_args
        prompt_data = json.loads(call_args.kwargs["evidence_bundle"])
        assert prompt_data["findings_summary"]["total_findings"] == 3
        assert "critical" in prompt_data["findings_summary"]["severity_distribution"]
