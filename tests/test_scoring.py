# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for design maturity scoring and trend tracking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from nfr_review.config import ScoringConfig
from nfr_review.models import Finding
from nfr_review.output.markdown import render_score_section
from nfr_review.scoring import (
    MaturityScore,
    ScoreTrend,
    _extract_category,
    compute_maturity_score,
    compute_trend,
    load_baseline_score,
)

_UNWEIGHTED = ScoringConfig(category_weights={}, category_aliases={})


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
    score = compute_maturity_score([], ["R001", "R002"], [], _UNWEIGHTED)
    assert score.overall == 100
    assert score.grade == "A"
    assert score.category_scores == {}
    assert score.rules_coverage == 1.0


def test_critical_finding_heavy_deduction() -> None:
    findings = [_finding(severity="critical")]
    score = compute_maturity_score(findings, ["R001"], [], _UNWEIGHTED)
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
    score = compute_maturity_score(findings, ["R001"], [], _UNWEIGHTED)
    # 100 - 15 - 8 - 3 - 1 - 0 = 73
    assert score.overall == 73
    assert score.grade == "C"


def test_score_floor_at_zero() -> None:
    # 10 critical findings: 10 * 15 = 150 deduction -> floor at 0
    findings = [_finding(severity="critical") for _ in range(10)]
    score = compute_maturity_score(findings, ["R001"], [], _UNWEIGHTED)
    assert score.overall == 0
    assert score.grade == "F"


def test_grade_thresholds() -> None:
    # A >= 90
    score_a = compute_maturity_score([], ["R001"], [], _UNWEIGHTED)
    assert score_a.grade == "A"
    assert score_a.overall >= 90

    # B: score 75-89 -> one critical = 85
    score_b = compute_maturity_score(
        [_finding(severity="critical")], ["R001"], [], _UNWEIGHTED
    )
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
        _UNWEIGHTED,
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
        _UNWEIGHTED,
    )
    assert score_d.overall == 47
    assert score_d.grade == "D"

    # F: < 45
    score_f = compute_maturity_score(
        [_finding(severity="critical") for _ in range(5)],
        ["R001"],
        [],
        _UNWEIGHTED,
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
    score = compute_maturity_score(findings, ["R001"], [], _UNWEIGHTED)
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
    score = compute_maturity_score(findings, ["R001"], [], _UNWEIGHTED)
    assert score.category_scores == {"SEC": 85, "OBS": 92, "PERF": 97, "OPS": 99}
    # (85 + 92 + 97 + 99) / 4 = 93.25 → 93
    assert score.overall == 93
    assert score.grade == "A"


def test_rules_coverage() -> None:
    score = compute_maturity_score(
        [],
        ["R001", "R002", "R003", "R004", "R005", "R006", "R007", "R008"],
        [{"rule_id": "R009", "reason": "n/a"}, {"rule_id": "R010", "reason": "n/a"}],
        _UNWEIGHTED,
    )
    assert score.rules_coverage == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Weighted / ISO 25010 scoring tests
# ---------------------------------------------------------------------------


def test_default_scoring_includes_all_iso_categories() -> None:
    """With default ScoringConfig, all 4 ISO categories contribute even without findings."""
    score = compute_maturity_score([], ["R001"], [])
    assert score.overall == 100
    assert score.grade == "A"


def test_weighted_score_dilutes_single_category_findings() -> None:
    """A critical finding in one category is diluted by clean categories."""
    findings = [_finding(rule_id="security-check", severity="critical")]
    score = compute_maturity_score(findings, ["R001"], [])
    # security: 85, all others: 100
    # (85 + 100*5) / 6 = 97.5 → 98
    assert score.category_scores["security"] == 85
    assert score.overall == 98
    assert score.grade == "A"


def test_custom_weights_shift_overall() -> None:
    """Higher weight on a bad category pulls overall score down more."""
    findings = [_finding(rule_id="security-check", severity="critical")]
    heavy_security = ScoringConfig(
        category_weights={
            "security": 3.0,
            "reliability": 1.0,
            "performance": 1.0,
            "maintainability": 1.0,
        },
    )
    score = compute_maturity_score(findings, ["R001"], [], heavy_security)
    # security: 85×3 + reliability/performance/maintainability: 100×1 each
    # (255 + 300) / 6 = 92.5 → 92
    assert score.overall == 92


def test_category_aliases_normalize_legacy_names() -> None:
    """OTel rules get their own category; ops findings are aliased to maintainability."""
    findings = [
        _finding(
            rule_id="otel-missing", severity="high"
        ),  # keyword: otel → OTEL (own category)
        _finding(
            rule_id="resource-limits-missing", severity="medium"
        ),  # keyword: resource-limits → ops → maintainability
    ]
    score = compute_maturity_score(findings, ["R001"], [])
    assert "OTEL" in score.category_scores
    assert "maintainability" in score.category_scores
    assert "observability" not in score.category_scores
    assert "ops" not in score.category_scores


def test_custom_severity_deductions() -> None:
    """Custom deductions override defaults."""
    findings = [_finding(severity="critical")]
    lenient = ScoringConfig(
        category_weights={},
        category_aliases={},
        severity_deductions={"critical": 5, "high": 3, "medium": 1, "low": 0, "info": 0},
    )
    score = compute_maturity_score(findings, ["R001"], [], lenient)
    # TEST: 100 - 5 = 95
    assert score.overall == 95


# ---------------------------------------------------------------------------
# Trend tests
# ---------------------------------------------------------------------------


def test_trend_improved() -> None:
    current = compute_maturity_score(
        [_finding(severity="low")],  # 100 - 1 = 99
        ["R001"],
        [],
        _UNWEIGHTED,
    )
    baseline_findings = [
        _finding(severity="critical"),  # baseline: 100 - 15 = 85
    ]
    trend = compute_trend(current, baseline_findings, ["R001"], [], _UNWEIGHTED)
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
        _UNWEIGHTED,
    )
    baseline_findings = [
        _finding(severity="low"),  # baseline: 100 - 1 = 99
    ]
    trend = compute_trend(current, baseline_findings, ["R001"], [], _UNWEIGHTED)
    assert trend.direction == "regressed"
    assert trend.delta < 0
    assert trend.delta == -29


def test_trend_stable() -> None:
    findings = [_finding(severity="medium")]  # 100 - 3 = 97
    current = compute_maturity_score(findings, ["R001"], [], _UNWEIGHTED)
    trend = compute_trend(current, findings, ["R001"], [], _UNWEIGHTED)
    assert trend.direction == "stable"
    assert trend.delta == 0


def test_category_deltas_in_trend() -> None:
    current = compute_maturity_score(
        [_finding(rule_id="SEC-001", severity="low")],  # SEC: 99
        ["R001"],
        [],
        _UNWEIGHTED,
    )
    baseline_findings = [
        _finding(rule_id="SEC-001", severity="high"),  # SEC: 92
    ]
    trend = compute_trend(current, baseline_findings, ["R001"], [], _UNWEIGHTED)
    assert "SEC" in trend.category_deltas
    assert trend.category_deltas["SEC"] == 7  # 99 - 92


def test_trend_with_weighted_scoring() -> None:
    """Trend uses the same scoring config for both current and baseline."""
    current = compute_maturity_score(
        [_finding(rule_id="security-check", severity="low")],
        ["R001"],
        [],
    )
    baseline_findings = [
        _finding(rule_id="security-check", severity="critical"),
    ]
    trend = compute_trend(current, baseline_findings, ["R001"], [])
    assert trend.direction == "improved"
    assert trend.delta > 0


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


def test_cli_score_with_custom_yaml_config(tmp_path: Path) -> None:
    """Custom scoring config from YAML flows through to compute_maturity_score."""
    from nfr_review.cli import cli

    fixture = Path(__file__).parent / "fixtures" / "ci-sample-repo"
    if not fixture.exists():
        pytest.skip("ci-sample-repo fixture not found")

    config_path = tmp_path / "nfr-review.yaml"
    config_path.write_text(
        "scoring:\n"
        "  category_weights:\n"
        "    security: 3.0\n"
        "    reliability: 1.0\n"
        "    performance: 1.0\n"
        "    maintainability: 1.0\n"
        "  severity_deductions:\n"
        "    critical: 20\n"
        "    high: 10\n"
        "    medium: 5\n"
        "    low: 2\n"
        "    info: 0\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            str(fixture),
            "--config",
            str(config_path),
            "--score",
            "-q",
            "--csv",
            str(tmp_path / "out.csv"),
            "--jsonl",
            str(tmp_path / "out.jsonl"),
        ],
    )
    assert result.exit_code in (0, 2), (
        f"Unexpected exit code: {result.exit_code}\n{result.output}"
    )
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "Design Maturity Score:" in combined


def test_config_to_score_integration() -> None:
    """End-to-end: ScoringConfig from YAML dict → compute_maturity_score honours weights."""
    import tempfile

    from nfr_review.config import load_config

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(
            "scoring:\n"
            "  category_weights:\n"
            "    security: 4.0\n"
            "    reliability: 1.0\n"
            "    performance: 1.0\n"
            "    maintainability: 1.0\n"
        )
        f.flush()
        cfg = load_config(Path(f.name))

    findings = [_finding(rule_id="security-check", severity="critical")]
    score = compute_maturity_score(findings, ["R001"], [], cfg.scoring)

    # security: 100 - 15 = 85, others: 100
    # weighted: (85×4 + 100×3) / 7 = 640/7 ≈ 91
    assert score.category_scores["security"] == 85
    assert score.overall == 91


# ---------------------------------------------------------------------------
# _extract_category tests
# ---------------------------------------------------------------------------


def test_extract_category_keyword_match() -> None:
    assert _extract_category("dockerfile-secret-leakage") == "security"
    assert _extract_category("otel-missing-exporter") == "OTEL"
    assert _extract_category("timeout-not-configured") == "performance"
    assert _extract_category("resource-limits-missing") == "ops"


def test_extract_category_prefix_based() -> None:
    assert _extract_category("SEC-001") == "SEC"
    assert _extract_category("PATCH-003") == "PATCH"
    assert _extract_category("OBS-042") == "OBS"


def test_extract_category_fallback_to_ops() -> None:
    assert _extract_category("unknown-rule-name") == "ops"
    assert _extract_category("something-entirely-novel") == "ops"


def test_extract_category_with_aliases() -> None:
    aliases = {"ops": "maintainability", "observability": "reliability"}
    assert _extract_category("resource-limits-missing", aliases) == "maintainability"
    assert _extract_category("logging-missing", aliases) == "reliability"


def test_extract_category_alias_no_match_passes_through() -> None:
    aliases = {"ops": "maintainability"}
    assert _extract_category("otel-check", aliases) == "OTEL"


# ---------------------------------------------------------------------------
# load_baseline_score tests
# ---------------------------------------------------------------------------


def _valid_finding_record() -> dict[str, Any]:
    return {
        "record_type": "finding",
        "rule_id": "SEC-001",
        "rag": "amber",
        "severity": "high",
        "summary": "test finding",
        "recommendation": "fix it",
        "evidence_locator": "file://test.py:1",
        "collector_name": "test",
        "collector_version": "1.0",
        "confidence": 0.9,
        "pattern_tag": "test-tag",
    }


def test_load_baseline_score_valid(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    metadata = {
        "record_type": "run_metadata",
        "rules_run": ["SEC-001", "OBS-001"],
        "rules_skipped": [{"rule_id": "SKIP-001", "reason": "n/a"}],
    }
    finding = _valid_finding_record()
    baseline.write_text(
        json.dumps(metadata) + "\n" + json.dumps(finding) + "\n",
        encoding="utf-8",
    )
    findings, rules_run, rules_skipped = load_baseline_score(baseline)
    assert len(findings) == 1
    assert findings[0].rule_id == "SEC-001"
    assert rules_run == ["SEC-001", "OBS-001"]
    assert len(rules_skipped) == 1


def test_load_baseline_score_empty_file(tmp_path: Path) -> None:
    baseline = tmp_path / "empty.jsonl"
    baseline.write_text("", encoding="utf-8")
    findings, rules_run, rules_skipped = load_baseline_score(baseline)
    assert findings == []
    assert rules_run == []
    assert rules_skipped == []


def test_load_baseline_score_blank_lines(tmp_path: Path) -> None:
    baseline = tmp_path / "blanks.jsonl"
    metadata = {
        "record_type": "run_metadata",
        "rules_run": ["R001"],
        "rules_skipped": [],
    }
    baseline.write_text(
        "\n" + json.dumps(metadata) + "\n\n\n",
        encoding="utf-8",
    )
    findings, rules_run, rules_skipped = load_baseline_score(baseline)
    assert rules_run == ["R001"]
    assert findings == []


def test_load_baseline_score_skips_skipped_findings(tmp_path: Path) -> None:
    baseline = tmp_path / "skipped.jsonl"
    skipped_finding = _valid_finding_record()
    skipped_finding["rag"] = "skipped"
    baseline.write_text(json.dumps(skipped_finding) + "\n", encoding="utf-8")
    findings, _, _ = load_baseline_score(baseline)
    assert findings == []


def test_load_baseline_score_malformed_finding_skipped(tmp_path: Path) -> None:
    baseline = tmp_path / "malformed.jsonl"
    bad_finding = {"record_type": "finding", "rag": "amber"}
    baseline.write_text(json.dumps(bad_finding) + "\n", encoding="utf-8")
    findings, _, _ = load_baseline_score(baseline)
    assert findings == []


def test_load_baseline_score_ignores_null_fields(tmp_path: Path) -> None:
    baseline = tmp_path / "nulls.jsonl"
    finding = _valid_finding_record()
    finding["content_hash"] = None
    baseline.write_text(json.dumps(finding) + "\n", encoding="utf-8")
    findings, _, _ = load_baseline_score(baseline)
    assert len(findings) == 1
    assert findings[0].content_hash == ""


def test_load_baseline_score_metadata_without_optional_keys(tmp_path: Path) -> None:
    baseline = tmp_path / "minimal_meta.jsonl"
    metadata = {"record_type": "run_metadata"}
    baseline.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    _, rules_run, rules_skipped = load_baseline_score(baseline)
    assert rules_run == []
    assert rules_skipped == []


# ---------------------------------------------------------------------------
# Edge case: rules_skipped as plain strings
# ---------------------------------------------------------------------------


def test_rules_coverage_with_string_skipped() -> None:
    score = compute_maturity_score(
        [],
        ["R001"],
        ["R002", "R003"],
        _UNWEIGHTED,
    )
    assert score.rules_coverage == pytest.approx(1 / 3)


def test_no_rules_run_or_skipped() -> None:
    score = compute_maturity_score([], [], [], _UNWEIGHTED)
    assert score.rules_coverage == 1.0
    assert score.overall == 100


# ---------------------------------------------------------------------------
# Origin partitioning: scoring uses first-party only
# ---------------------------------------------------------------------------


def test_partition_before_scoring_excludes_deps() -> None:
    """Dependency findings should not affect the maturity score."""
    from nfr_review.output.classify import partition_findings_by_origin

    fp = Finding(
        rule_id="security-leak",
        rag="red",
        severity="critical",
        summary="fp issue",
        recommendation="fix",
        evidence_locator="src/main.py",
        collector_name="c",
        collector_version="1",
        confidence=0.9,
        pattern_tag="t",
        origin="first_party",
    )
    dep = Finding(
        rule_id="security-leak",
        rag="red",
        severity="critical",
        summary="dep issue",
        recommendation="fix",
        evidence_locator="dep:lodash@4.17.20",
        collector_name="c",
        collector_version="1",
        confidence=0.9,
        pattern_tag="t",
        origin="dependency",
    )
    all_findings = [fp, dep]
    first_party, dependency = partition_findings_by_origin(all_findings)
    assert len(first_party) == 1
    assert len(dependency) == 1

    score_all = compute_maturity_score(all_findings, ["R001"], [], _UNWEIGHTED)
    score_fp = compute_maturity_score(first_party, ["R001"], [], _UNWEIGHTED)
    assert score_fp.overall > score_all.overall
