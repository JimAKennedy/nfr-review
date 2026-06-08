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

from nfr_review.config import (
    CATEGORY_ALIASES,
    DEFAULT_CATEGORY_WEIGHTS,
    DEFAULT_SEVERITY_DEDUCTIONS,
    ScoringConfig,
)
from nfr_review.models import Finding


# nfr-review:skip(python-dormant-classes) reason: returned by compute_maturity_score
class MaturityScore(BaseModel):
    """Design maturity score with category breakdown."""

    overall: int = Field(ge=0, le=100)
    grade: str  # A/B/C/D/F
    category_scores: dict[str, int]  # category -> score
    finding_counts: dict[str, int]  # severity -> count
    rules_coverage: float  # fraction of rules that ran vs total


# nfr-review:skip(python-dormant-classes) reason: returned by compute_trend
class ScoreTrend(BaseModel):
    """Trend comparison between current and baseline scores."""

    current_score: int
    baseline_score: int
    delta: int  # positive = improved
    direction: str  # "improved" / "regressed" / "stable"
    category_deltas: dict[str, int]  # category -> delta


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


_CATEGORY_KEYWORDS: dict[str, str] = {
    "security": "security",
    "secret": "security",  # nosec B105
    "auth": "security",
    "pii": "security",
    "iam": "security",
    "base-pinning": "security",
    "provider-pinning": "security",
    "fetchcontent-pinning": "security",
    "user-directive": "security",
    "otel": "OTEL",
    "logging": "observability",
    "log-statement": "observability",
    "correlation-id": "observability",
    "telem": "observability",
    "health": "observability",
    "probe": "observability",
    "timeout": "performance",
    "thread-pool": "performance",
    "goroutine": "performance",
    "defer-in-loop": "performance",
    "sync-fs": "performance",
    "async-void": "performance",
    "blocking-async": "performance",
    "configure-await": "performance",
    "async-fire": "performance",
    "promise-no-catch": "performance",
    "instability": "performance",
    "resource-limits": "ops",
    "ci-": "ops",
    "jacoco": "ops",
    "sanitizer-ci": "ops",
    "dockerfile": "ops",
    "k8s-": "ops",
    "helm-": "ops",
    "istio-": "ops",
    "skaffold": "ops",
    "terraform-state": "ops",
    "spring-profile": "ops",
    "cmake-": "ops",
    "dep-upgrade": "ops",
    "adr-": "ops",
    "architectural": "ops",
    "exception": "ops",
    "broad-except": "ops",
    "star-import": "ops",
    "mutable-default": "ops",
    "raw-memory": "ops",
    "include-guards": "ops",
    "disposable": "ops",
    "clang-format": "ops",
    "multistage": "ops",
    "resilience": "ops",
    "circuit-breaker": "ops",
    "rate-limit": "ops",
    "proto-service": "ops",
    "traffic-policy": "ops",
    "image-drift": "ops",
    "user-conflict": "ops",
    "chart-metadata": "ops",
    "values-validation": "ops",
    "build-config": "ops",
    "minimum-version": "ops",
    "coverage-actual": "ops",
    "profile-config": "ops",
    "dyn-latency": "performance",
    "dyn-n-plus-1": "performance",
    "dyn-correlation": "OTEL",
    "dyn-method-coverage": "OTEL",
    "dyn-call-sequence": "OTEL",
    "dyn-adr-drift": "OTEL",
}


def _extract_category(
    rule_id: str,
    aliases: dict[str, str] | None = None,
) -> str:
    """Map a rule_id to an ISO 25010 category.

    Handles two formats: prefix-based (``SEC-001``) preserves the prefix,
    descriptive (``dockerfile-secret-leakage``) uses keyword matching.
    After keyword lookup, applies *aliases* to normalise legacy names
    (e.g. ``observability`` → ``reliability``).
    """
    lower = rule_id.lower()
    raw = None
    for keyword, category in _CATEGORY_KEYWORDS.items():
        if keyword in lower:
            raw = category
            break
    if raw is None:
        parts = rule_id.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            raw = parts[0]
        else:
            raw = "ops"
    if aliases:
        raw = aliases.get(raw.lower(), raw)
    return raw


def compute_maturity_score(
    findings: list[Finding],
    rules_run: list[str],
    rules_skipped: Sequence[dict[str, Any] | str],
    scoring: ScoringConfig | None = None,
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
    scoring:
        Optional scoring configuration with weights, deductions, and aliases.
        Falls back to module-level defaults when ``None``.

    Returns
    -------
    MaturityScore
        The computed score with category breakdown.
    """
    weights = scoring.category_weights if scoring else DEFAULT_CATEGORY_WEIGHTS
    deductions = scoring.severity_deductions if scoring else DEFAULT_SEVERITY_DEDUCTIONS
    aliases = scoring.category_aliases if scoring else CATEGORY_ALIASES

    # Count severities
    severity_counts: dict[str, int] = {}
    for sev in ("critical", "high", "medium", "low", "info"):
        severity_counts[sev] = 0
    for f in findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

    # Category scores
    category_findings: dict[str, list[Finding]] = {}
    for f in findings:
        cat = _extract_category(f.rule_id, aliases)
        category_findings.setdefault(cat, []).append(f)

    category_scores: dict[str, int] = {}
    for cat, cat_findings in category_findings.items():
        cat_deduction = 0
        for f in cat_findings:
            cat_deduction += deductions.get(f.severity, 0)
        category_scores[cat] = max(0, 100 - cat_deduction)

    # Overall score: coverage-weighted average of category scores.
    # Categories with higher weight contribute more to the final score.
    # Categories with no findings default to 100 and are included if they
    # have a configured weight.
    all_categories = set(weights) | set(category_scores)
    total_weight = sum(weights.get(c, 1.0) for c in all_categories)
    if total_weight > 0:
        weighted_sum = sum(
            category_scores.get(c, 100) * weights.get(c, 1.0) for c in all_categories
        )
        overall = round(weighted_sum / total_weight)
    else:
        overall = 100
    overall = max(0, min(100, overall))

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
    scoring: ScoringConfig | None = None,
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
    scoring:
        Optional scoring configuration (same weights used for baseline).

    Returns
    -------
    ScoreTrend
        The trend comparison.
    """
    baseline_score = compute_maturity_score(
        baseline_findings, baseline_rules_run, baseline_rules_skipped, scoring
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
                # nfr-review:skip(bare-except-catch-all, python-broad-except-silent)
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
