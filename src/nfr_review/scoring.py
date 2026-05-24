# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Design maturity scoring and trend tracking.

Computes a 0-100 maturity score from findings, with per-category breakdown
and optional trend comparison against a baseline.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nfr_review.models import Finding, Severity


class MaturityScore(BaseModel):
    """Design maturity score with category breakdown."""

    overall: int = Field(ge=0, le=100)
    grade: str  # A/B/C/D/F
    category_scores: dict[str, int]  # category -> score
    finding_counts: dict[str, int]  # severity -> count
    rules_coverage: float  # fraction of rules that ran vs total


class ScoreTrend(BaseModel):
    """Trend comparison between current and baseline scores."""

    current_score: int
    baseline_score: int
    delta: int  # positive = improved
    direction: str  # "improved" / "regressed" / "stable"
    category_deltas: dict[str, int]  # category -> delta


_SEVERITY_WEIGHTS: dict[Severity, int] = {
    "critical": -15,
    "high": -8,
    "medium": -3,
    "low": -1,
    "info": 0,
}


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


def _extract_category(rule_id: str) -> str:
    """Extract category prefix from a rule_id (e.g. 'SEC-001' -> 'SEC')."""
    parts = rule_id.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return rule_id


def compute_maturity_score(
    findings: list[Finding],
    rules_run: list[str],
    rules_skipped: Sequence[dict[str, Any] | str],
) -> MaturityScore:
    """Compute a design maturity score from findings and rule coverage.

    Parameters
    ----------
    findings:
        The list of findings from the scan.
    rules_run:
        List of rule IDs that were executed.
    rules_skipped:
        List of skipped rule entries (dicts with ``rule_id`` key, or plain strings).

    Returns
    -------
    MaturityScore
        The computed score with category breakdown.
    """
    # Count severities
    severity_counts: dict[str, int] = {}
    for sev in ("critical", "high", "medium", "low", "info"):
        severity_counts[sev] = 0
    for f in findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

    # Overall score
    total_deduction = 0
    for f in findings:
        total_deduction += abs(_SEVERITY_WEIGHTS.get(f.severity, 0))
    overall = max(0, min(100, 100 - total_deduction))

    # Category scores
    category_findings: dict[str, list[Finding]] = {}
    for f in findings:
        cat = _extract_category(f.rule_id)
        category_findings.setdefault(cat, []).append(f)

    category_scores: dict[str, int] = {}
    for cat, cat_findings in category_findings.items():
        cat_deduction = 0
        for f in cat_findings:
            cat_deduction += abs(_SEVERITY_WEIGHTS.get(f.severity, 0))
        category_scores[cat] = max(0, 100 - cat_deduction)

    # Rules coverage
    total_rules = len(rules_run) + len(rules_skipped)
    if total_rules > 0:
        rules_coverage = len(rules_run) / total_rules
    else:
        rules_coverage = 1.0

    return MaturityScore(
        overall=overall,
        grade=_grade(overall),
        category_scores=category_scores,
        finding_counts=severity_counts,
        rules_coverage=rules_coverage,
    )


def compute_trend(
    current_score: MaturityScore,
    baseline_findings: list[Finding],
    baseline_rules_run: list[str],
    baseline_rules_skipped: Sequence[dict[str, Any] | str],
) -> ScoreTrend:
    """Compute trend between current score and baseline findings.

    Parameters
    ----------
    current_score:
        The current MaturityScore.
    baseline_findings:
        Findings from the baseline scan.
    baseline_rules_run:
        Rule IDs that ran in the baseline scan.
    baseline_rules_skipped:
        Skipped rule entries from the baseline scan.

    Returns
    -------
    ScoreTrend
        The trend comparison.
    """
    baseline_score = compute_maturity_score(
        baseline_findings, baseline_rules_run, baseline_rules_skipped
    )

    delta = current_score.overall - baseline_score.overall
    if delta > 0:
        direction = "improved"
    elif delta < 0:
        direction = "regressed"
    else:
        direction = "stable"

    # Category deltas
    all_categories = set(current_score.category_scores) | set(baseline_score.category_scores)
    category_deltas: dict[str, int] = {}
    for cat in all_categories:
        cur = current_score.category_scores.get(cat, 100)
        bl = baseline_score.category_scores.get(cat, 100)
        category_deltas[cat] = cur - bl

    return ScoreTrend(
        current_score=current_score.overall,
        baseline_score=baseline_score.overall,
        delta=delta,
        direction=direction,
        category_deltas=category_deltas,
    )


def load_baseline_score(
    baseline_path: Path,
) -> tuple[list[Finding], list[str], list[dict[str, Any]]]:
    """Load findings, rules_run, and rules_skipped from a baseline JSONL for scoring.

    Parameters
    ----------
    baseline_path:
        Path to a JSONL baseline file.

    Returns
    -------
    tuple
        (findings, rules_run, rules_skipped) extracted from the baseline.
    """
    findings: list[Finding] = []
    rules_run: list[str] = []
    rules_skipped: list[dict[str, Any]] = []

    with baseline_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record_type = record.get("record_type")
            if record_type == "run_metadata":
                rules_run = record.get("rules_run", [])
                rules_skipped = record.get("rules_skipped", [])
            elif record_type == "finding" and record.get("rag") != "skipped":
                try:
                    findings.append(
                        Finding(
                            **{
                                k: v
                                for k, v in record.items()
                                if k != "record_type" and v is not None
                            }
                        )
                    )
                except Exception:  # noqa: BLE001  # nosec B112
                    continue

    return findings, rules_run, rules_skipped


__all__ = [
    "MaturityScore",
    "ScoreTrend",
    "compute_maturity_score",
    "compute_trend",
    "load_baseline_score",
]
