# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for design maturity scoring and trend tracking."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.models import Finding
from nfr_review.output.markdown import render_score_section
from nfr_review.scoring import (
    MaturityScore,
    ScoreTrend,
    compute_maturity_score,
    compute_trend,
)


def _finding(
    rule_id: str = "TEST-001",
    severity: str = "medium",
    rag: str = "amber",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rag=rag,
        severity=severity,
        summary="test",
        recommendation="fix it",
        evidence_locator="file://test.py:1",
        collector_name="test",
        collector_version="1.0",
        confidence=0.9,
        pattern_tag="test-tag",
    )


# ---------------------------------------------------------------------------
# Score computation tests
# ---------------------------------------------------------------------------


def test_no_findings_perfect_score() -> None:
    score = compute_maturity_score([], ["R001", "R002"], [])
    assert score.overall == 100
    assert score.grade == "A"
    assert score.category_scores == {}
    assert score.rules_coverage == 1.0


def test_critical_finding_heavy_deduction() -> None:
    findings = [_finding(severity="critical")]
    score = compute_maturity_score(findings, ["R001"], [])
    assert score.overall == 85
    assert score.grade == "B"


def test_multiple_severities() -> None:
    findings = [
        _finding(severity="critical"),  # -15
        _finding(severity="high"),  # -8
        _finding(severity="medium"),  # -3
        _finding(severity="low"),  # -1
        _finding(severity="info"),  # -0
    ]
    score = compute_maturity_score(findings, ["R001"], [])
    # 100 - 15 - 8 - 3 - 1 - 0 = 73
    assert score.overall == 73
    assert score.grade == "C"


def test_score_floor_at_zero() -> None:
    # 10 critical findings: 10 * 15 = 150 deduction -> floor at 0
    findings = [_finding(severity="critical") for _ in range(10)]
    score = compute_maturity_score(findings, ["R001"], [])
    assert score.overall == 0
    assert score.grade == "F"


def test_grade_thresholds() -> None:
    # A >= 90
    score_a = compute_maturity_score([], ["R001"], [])
    assert score_a.grade == "A"
    assert score_a.overall >= 90

    # B: score 75-89 -> one critical = 85
    score_b = compute_maturity_score([_finding(severity="critical")], ["R001"], [])
    assert score_b.overall == 85
    assert score_b.grade == "B"

    # C: score 60-74 -> one critical + one high = 77... that's B.
    # Let's do critical + high + medium = 100 - 15 - 8 - 3 = 74
    score_c = compute_maturity_score(
        [
            _finding(severity="critical"),
            _finding(severity="high"),
            _finding(severity="medium"),
        ],
        ["R001"],
        [],
    )
    assert score_c.overall == 74
    assert score_c.grade == "C"

    # D: score 45-59 -> need bigger deduction
    # 3 critical + 1 high = 100 - 45 - 8 = 47
    score_d = compute_maturity_score(
        [
            _finding(severity="critical"),
            _finding(severity="critical"),
            _finding(severity="critical"),
            _finding(severity="high"),
        ],
        ["R001"],
        [],
    )
    assert score_d.overall == 47
    assert score_d.grade == "D"

    # F: < 45
    score_f = compute_maturity_score(
        [_finding(severity="critical") for _ in range(5)],
        ["R001"],
        [],
    )
    # 100 - 75 = 25
    assert score_f.overall == 25
    assert score_f.grade == "F"


def test_category_breakdown() -> None:
    findings = [
        _finding(rule_id="SEC-001", severity="high"),  # SEC: 100 - 8 = 92
        _finding(rule_id="SEC-002", severity="medium"),  # SEC: 92 - 3 = 89
        _finding(rule_id="PATCH-002", severity="low"),  # PATCH: 100 - 1 = 99
    ]
    score = compute_maturity_score(findings, ["R001"], [])
    assert "SEC" in score.category_scores
    assert "PATCH" in score.category_scores
    assert score.category_scores["SEC"] == 89
    assert score.category_scores["PATCH"] == 99
    # Overall is the mean of category scores: (89 + 99) / 2 = 94
    assert score.overall == 94


def test_overall_is_category_average_across_many_categories() -> None:
    findings = [
        _finding(rule_id="SEC-001", severity="critical"),  # SEC: 85
        _finding(rule_id="OBS-001", severity="high"),  # OBS: 92
        _finding(rule_id="PERF-001", severity="medium"),  # PERF: 97
        _finding(rule_id="OPS-001", severity="low"),  # OPS: 99
    ]
    score = compute_maturity_score(findings, ["R001"], [])
    assert score.category_scores == {"SEC": 85, "OBS": 92, "PERF": 97, "OPS": 99}
    # (85 + 92 + 97 + 99) / 4 = 93.25 → 93
    assert score.overall == 93
    assert score.grade == "A"


def test_rules_coverage() -> None:
    score = compute_maturity_score(
        [],
        ["R001", "R002", "R003", "R004", "R005", "R006", "R007", "R008"],
        [{"rule_id": "R009", "reason": "n/a"}, {"rule_id": "R010", "reason": "n/a"}],
    )
    assert score.rules_coverage == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Trend tests
# ---------------------------------------------------------------------------


def test_trend_improved() -> None:
    current = compute_maturity_score(
        [_finding(severity="low")],  # 100 - 1 = 99
        ["R001"],
        [],
    )
    baseline_findings = [
        _finding(severity="critical"),  # baseline: 100 - 15 = 85
    ]
    trend = compute_trend(current, baseline_findings, ["R001"], [])
    assert trend.direction == "improved"
    assert trend.delta > 0
    assert trend.current_score == 99
    assert trend.baseline_score == 85
    assert trend.delta == 14


def test_trend_regressed() -> None:
    current = compute_maturity_score(
        [_finding(severity="critical"), _finding(severity="critical")],  # 100 - 30 = 70
        ["R001"],
        [],
    )
    baseline_findings = [
        _finding(severity="low"),  # baseline: 100 - 1 = 99
    ]
    trend = compute_trend(current, baseline_findings, ["R001"], [])
    assert trend.direction == "regressed"
    assert trend.delta < 0
    assert trend.delta == -29


def test_trend_stable() -> None:
    findings = [_finding(severity="medium")]  # 100 - 3 = 97
    current = compute_maturity_score(findings, ["R001"], [])
    trend = compute_trend(current, findings, ["R001"], [])
    assert trend.direction == "stable"
    assert trend.delta == 0


def test_category_deltas_in_trend() -> None:
    current = compute_maturity_score(
        [_finding(rule_id="SEC-001", severity="low")],  # SEC: 99
        ["R001"],
        [],
    )
    baseline_findings = [
        _finding(rule_id="SEC-001", severity="high"),  # SEC: 92
    ]
    trend = compute_trend(current, baseline_findings, ["R001"], [])
    assert "SEC" in trend.category_deltas
    assert trend.category_deltas["SEC"] == 7  # 99 - 92


# ---------------------------------------------------------------------------
# Markdown rendering tests
# ---------------------------------------------------------------------------


def test_score_section_markdown() -> None:
    score = MaturityScore(
        overall=82,
        grade="B",
        category_scores={"SEC": 85, "PATCH": 92},
        finding_counts={"critical": 0, "high": 1, "medium": 2, "low": 1, "info": 0},
        rules_coverage=0.95,
    )
    md = render_score_section(score)
    assert "## Design Maturity Score" in md
    assert "82/100" in md
    assert "Grade: B" in md
    assert "95%" in md
    assert "SEC" in md
    assert "PATCH" in md


def test_score_section_with_trend() -> None:
    score = MaturityScore(
        overall=82,
        grade="B",
        category_scores={"SEC": 85},
        finding_counts={"critical": 0, "high": 1, "medium": 0, "low": 0, "info": 0},
        rules_coverage=1.0,
    )
    trend = ScoreTrend(
        current_score=82,
        baseline_score=77,
        delta=5,
        direction="improved",
        category_deltas={"SEC": 15},
    )
    md = render_score_section(score, trend)
    assert "Trend" in md
    assert "+5" in md
    assert "77" in md
    assert "Improved" in md


# ---------------------------------------------------------------------------
# CLI integration test
# ---------------------------------------------------------------------------


def test_cli_score_flag(tmp_path: Path) -> None:
    """The --score flag should display the maturity score on stderr."""
    from nfr_review.cli import cli

    # Use the ci-sample-repo fixture which has minimal files
    fixture = Path(__file__).parent / "fixtures" / "ci-sample-repo"
    if not fixture.exists():
        pytest.skip("ci-sample-repo fixture not found")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            str(fixture),
            "--score",
            "-q",
            "--csv",
            str(tmp_path / "out.csv"),
            "--jsonl",
            str(tmp_path / "out.jsonl"),
        ],
    )
    # The command should succeed (exit 0) or exit 2 if threshold exceeded
    assert result.exit_code in (0, 2), (
        f"Unexpected exit code: {result.exit_code}\n{result.output}"
    )
    # Score should appear in stderr output
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    # With -q, score output still goes to stderr. In CliRunner without
    # mix_stderr separation, it all ends up in output.
    # The score is always displayed when --score is given.
    # Since -q suppresses phase output but not score output, we check
    # for the score text in the combined output.
    assert "Design Maturity Score:" in combined or "Design Maturity Score:" in (
        result.stderr if hasattr(result, "stderr") else ""
    ), f"Score not found in output:\n{combined}"
