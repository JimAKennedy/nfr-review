# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""LLM-powered executive summary generation for NFR review reports."""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import TYPE_CHECKING

import pydantic

from nfr_review.llm_client import LlmUnavailableError, create_llm_client, extract_json
from nfr_review.output.summary_models import ExecSummary

if TYPE_CHECKING:
    from nfr_review.engine import RunResult
    from nfr_review.models import Finding
    from nfr_review.output.pytest_runner import PytestResult

logger = logging.getLogger(__name__)

_SEVERITY_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low", "info")

_SYSTEM_PROMPT = """\
You are an expert software quality assessor producing an executive summary of a \
non-functional requirements review. Your audience is engineering management who \
need to make a go/no-go decision about open-sourcing or reusing this project.

You will receive a structured summary of scan findings. Respond with ONLY a JSON \
object matching this exact schema — no markdown, no commentary, no code fences:

{
  "verdict": "fit" | "conditional" | "unfit",
  "verdict_explanation": "2-3 sentence explanation of the verdict",
  "risk_highlights": ["risk 1", "risk 2", ...],
  "remediation_priorities": [
    {"title": "...", "urgency": "immediate"|"short-term"|"medium-term", "description": "..."},
    ...
  ],
  "production_risks": "paragraph on production deployment risks",
  "open_source_readiness": "paragraph on open-source readiness",
  "overall_score": 0-100
}

Verdict criteria:
- "fit": No critical/high findings, adequate test coverage, dependencies managed
- "conditional": Some high findings but all have clear remediation paths
- "unfit": Critical security/licensing issues or fundamental architectural problems

Focus on actionable specifics, not generic advice. Reference actual rule IDs and \
finding counts from the data provided."""


def _build_findings_summary(findings: list[Finding]) -> dict:
    """Compress findings into a structured summary for the LLM prompt."""
    severity_counts: Counter[str] = Counter()
    rag_counts: Counter[str] = Counter()
    by_category: dict[str, list[dict]] = {}

    for f in findings:
        severity_counts[f.severity] += 1
        rag_counts[f.rag] += 1

        cat = f.rule_id.rsplit("-", 1)[0] if "-" in f.rule_id else f.rule_id
        by_category.setdefault(cat, []).append(
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "rag": f.rag,
                "summary": f.summary,
                "recommendation": f.recommendation,
            }
        )

    top_findings = []
    for sev in ("critical", "high"):
        for f in findings:
            if f.severity == sev:
                top_findings.append(
                    {
                        "rule_id": f.rule_id,
                        "severity": f.severity,
                        "rag": f.rag,
                        "summary": f.summary,
                        "recommendation": f.recommendation,
                        "location": f.evidence_locator,
                    }
                )

    return {
        "total_findings": len(findings),
        "severity_distribution": dict(severity_counts),
        "rag_distribution": dict(rag_counts),
        "categories": {k: len(v) for k, v in by_category.items()},
        "critical_and_high_findings": top_findings[:20],
    }


def _build_prompt_data(
    nfr_result: RunResult,
    hygiene_result: RunResult | None = None,
    pytest_result: PytestResult | None = None,
    deps_summary: str = "",
) -> str:
    """Build the data portion of the LLM prompt."""
    all_findings: list[Finding] = list(nfr_result.findings)
    if hygiene_result:
        all_findings.extend(hygiene_result.findings)

    data: dict = {
        "findings_summary": _build_findings_summary(all_findings),
    }

    if nfr_result.run_metadata:
        data["provenance"] = {
            "target": nfr_result.run_metadata.target_repo,
            "tool_version": nfr_result.run_metadata.tool_version,
            "rules_run": len(nfr_result.run_metadata.rules_run),
            "rules_skipped": len(nfr_result.run_metadata.rules_skipped),
        }

    if pytest_result is not None:
        data["test_results"] = {
            "passed": pytest_result.passed,
            "failed": pytest_result.failed,
            "skipped": pytest_result.skipped,
            "errors": pytest_result.errors,
            "duration_seconds": pytest_result.duration_seconds,
        }

    if deps_summary:
        data["dependency_analysis"] = deps_summary

    return json.dumps(data, indent=2)


def generate_executive_summary(
    nfr_result: RunResult,
    hygiene_result: RunResult | None = None,
    pytest_result: PytestResult | None = None,
    deps_summary: str = "",
) -> ExecSummary | None:
    """Generate an LLM-powered executive summary of scan results.

    Returns ``None`` when no LLM backend is configured or available.
    """
    client = create_llm_client()
    if not client.available:
        logger.info(
            "LLM not configured or unavailable — skipping executive summary generation"
        )
        return None

    prompt_data = _build_prompt_data(nfr_result, hygiene_result, pytest_result, deps_summary)

    try:
        raw = client.analyze(
            prompt=_SYSTEM_PROMPT,
            evidence_bundle=prompt_data,
            max_tokens=2048,
        )
    except LlmUnavailableError:
        return None
    except Exception:  # noqa: BLE001
        logger.exception("LLM call failed during executive summary generation")
        return None

    parsed = extract_json(raw, expect="object")
    if parsed is None:
        logger.warning("LLM returned non-JSON response for executive summary")
        return None

    try:
        return ExecSummary.model_validate(parsed)
    except pydantic.ValidationError:
        logger.warning("LLM response failed ExecSummary validation", exc_info=True)
        return None


__all__ = ["generate_executive_summary"]
