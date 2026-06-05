# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""End-to-end integration tests for baseline shift detection and suppression.

Uses C++ fixtures in tests/fixtures/cpp-baseline-shift/ that mimic the
DrumGenerator VSTGUI pattern — raw ``new`` expressions whose line numbers
shift when includes or comments are added above them.
"""

from __future__ import annotations

import json
from pathlib import Path

from nfr_review.baseline import (
    BaselineData,
    classify_findings,
    filter_new_findings,
    load_baseline,
)
from nfr_review.models import Finding, compute_content_hash
from nfr_review.suppression import apply_suppressions, is_finding_suppressed

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cpp-baseline-shift"

# Pre-computed content hashes for the expressions in the fixture files.
HASH_LABEL1 = compute_content_hash("new CTextLabel(CRect(10, 10, 100, 30))")
HASH_LABEL2 = compute_content_hash("new CTextLabel(CRect(10, 40, 100, 60))")
HASH_KNOB1 = compute_content_hash("new CKnob(CRect(120, 10, 160, 50))")
HASH_KNOB2 = compute_content_hash("new CKnob(CRect(120, 60, 160, 100))")
HASH_WINDOW_TITLE = compute_content_hash("new CTextLabel(CRect(0, 0, 200, 30))")


def _make_finding(
    evidence_locator: str,
    content_hash: str,
    pattern_tag: str = "cpp-raw-new",
    rule_id: str = "cpp-raw-memory",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rag="amber",
        severity="medium",
        summary="Raw new expression detected",
        recommendation="Use std::make_unique or std::make_shared instead.",
        evidence_locator=evidence_locator,
        collector_name="cpp-ast",
        collector_version="0.1.0",
        confidence=0.9,
        pattern_tag=pattern_tag,
        content_hash=content_hash,
    )


def _controller_findings() -> list[Finding]:
    """Findings matching controller.cpp (original line numbers)."""
    return [
        _make_finding("controller.cpp:7", HASH_LABEL1),
        _make_finding("controller.cpp:10", HASH_LABEL2),
        _make_finding("controller.cpp:13", HASH_KNOB1),
        _make_finding("controller.cpp:16", HASH_KNOB2),
    ]


def _controller_shifted_findings() -> list[Finding]:
    """Findings from controller.cpp after line shifts (+10 lines).

    Same file, same content hashes, but line numbers shifted — exactly
    what happens when includes or comments are added above existing code.
    Uses +10 offset to avoid overlap with original lines (7, 10, 13, 16).
    """
    return [
        _make_finding("controller.cpp:17", HASH_LABEL1),
        _make_finding("controller.cpp:20", HASH_LABEL2),
        _make_finding("controller.cpp:23", HASH_KNOB1),
        _make_finding("controller.cpp:26", HASH_KNOB2),
    ]


def _window_findings() -> list[Finding]:
    """Findings matching window.cpp."""
    return [_make_finding("window.cpp:6", HASH_WINDOW_TITLE)]


def _build_baseline(findings: list[Finding], tmp_path: Path) -> Path:
    """Write findings to a JSONL file and return the path."""
    jsonl_path = tmp_path / "baseline.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "record_type": "run_metadata",
                    "tool_version": "0.1.0",
                    "target_repo": "test-repo",
                    "timestamp": "2026-01-01 00:00:00 UTC",
                }
            )
            + "\n"
        )
        for f in findings:
            record = {"record_type": "finding", **f.model_dump()}
            fh.write(json.dumps(record) + "\n")
    return jsonl_path


# ---- S05-T02: End-to-end baseline shift regression tests --------------------


class TestBaselineShiftE2E:
    """Verify that line-shifted findings are NOT treated as new regressions."""

    def test_line_shift_zero_false_positives(self, tmp_path: Path) -> None:
        """Scanning shifted code with a baseline from the original produces
        zero new findings — all 4 should be classified as shifted.
        """
        baseline_path = _build_baseline(_controller_findings(), tmp_path)
        baseline = load_baseline(baseline_path)

        shifted = _controller_shifted_findings()
        new_only = filter_new_findings(shifted, baseline)
        assert len(new_only) == 0, f"Expected 0 new, got {len(new_only)}"

    def test_truly_new_finding_detected(self, tmp_path: Path) -> None:
        """A genuine new expression (not in baseline) is correctly flagged."""
        baseline_path = _build_baseline(_controller_findings(), tmp_path)
        baseline = load_baseline(baseline_path)

        current = _controller_shifted_findings()
        current.append(_make_finding("controller.cpp:25", "newexpr_hash"))

        new_only = filter_new_findings(current, baseline)
        assert len(new_only) == 1
        assert new_only[0].evidence_locator == "controller.cpp:25"

    def test_resolved_finding_detected(self, tmp_path: Path) -> None:
        """Removing an expression from the scan produces a resolved entry."""
        all_findings = _controller_findings() + _window_findings()
        baseline_path = _build_baseline(all_findings, tmp_path)
        baseline = load_baseline(baseline_path)

        # Current scan has only controller findings — window.cpp resolved
        current = _controller_findings()
        result = classify_findings(current, baseline)
        assert len(result.resolved) >= 1

        resolved_rules = {r[0] for r in result.resolved}
        assert "cpp-raw-memory" in resolved_rules

    def test_classification_output(self, tmp_path: Path) -> None:
        """Full classification: shifted + new + resolved in one call."""
        all_baseline = _controller_findings() + _window_findings()
        baseline_path = _build_baseline(all_baseline, tmp_path)
        baseline = load_baseline(baseline_path)

        # Current scan: controller shifted, window gone, one truly new
        current = _controller_shifted_findings()
        truly_new = _make_finding("extra.cpp:1", "brand_new_hash")
        current.append(truly_new)

        result = classify_findings(current, baseline)
        assert len(result.shifted) == 4, f"Expected 4 shifted, got {len(result.shifted)}"
        assert len(result.new) == 1
        assert result.new[0].evidence_locator == "extra.cpp:1"
        assert len(result.resolved) >= 1

    def test_shifted_preserves_baseline_locator(self, tmp_path: Path) -> None:
        """Shifted findings carry a baseline locator from the original file."""
        baseline_path = _build_baseline(_controller_findings(), tmp_path)
        baseline = load_baseline(baseline_path)

        result = classify_findings(_controller_shifted_findings(), baseline)
        original_lines = {
            "controller.cpp:7",
            "controller.cpp:10",
            "controller.cpp:13",
            "controller.cpp:16",
        }
        for sf in result.shifted:
            assert sf.baseline_locator in original_lines, (
                f"Expected baseline locator from original, got {sf.baseline_locator}"
            )

    def test_unchanged_findings_not_classified(self, tmp_path: Path) -> None:
        """Findings at the same line as baseline are neither new nor shifted."""
        baseline_path = _build_baseline(_controller_findings(), tmp_path)
        baseline = load_baseline(baseline_path)

        result = classify_findings(_controller_findings(), baseline)
        assert len(result.new) == 0
        assert len(result.shifted) == 0
        assert len(result.resolved) == 0


# ---- S05-T03: Suppression integration tests --------------------------------


class TestSuppressionIntegration:
    """Verify inline suppression markers work with real fixture files."""

    def test_suppression_marker_skips_finding(self) -> None:
        """Findings on lines with nfr-review:skip markers are suppressed."""
        # controller_suppressed.cpp has markers on:
        #   line 7: inline marker (label1)
        #   line 13: line-above marker (knob1 on line 14)
        findings = [
            _make_finding("controller_suppressed.cpp:7", HASH_LABEL1),  # suppressed (inline)
            _make_finding("controller_suppressed.cpp:10", HASH_LABEL2),  # NOT suppressed
            _make_finding(
                "controller_suppressed.cpp:14", HASH_KNOB1
            ),  # suppressed (line above)
            _make_finding("controller_suppressed.cpp:17", HASH_KNOB2),  # NOT suppressed
        ]

        active, suppressed = apply_suppressions(findings, target_root=FIXTURE_DIR)
        assert len(suppressed) == 2
        assert len(active) == 2

        suppressed_locators = {f.evidence_locator for f, _ in suppressed}
        assert "controller_suppressed.cpp:7" in suppressed_locators
        assert "controller_suppressed.cpp:14" in suppressed_locators

        active_locators = {f.evidence_locator for f in active}
        assert "controller_suppressed.cpp:10" in active_locators
        assert "controller_suppressed.cpp:17" in active_locators

    def test_suppressed_findings_not_in_new(self) -> None:
        """Suppressed findings that are then filtered against baseline don't
        appear as new (they're removed before baseline comparison).
        """
        # Simulate the CLI flow: suppress first, then baseline filter
        all_findings = [
            _make_finding("controller_suppressed.cpp:7", HASH_LABEL1),
            _make_finding("controller_suppressed.cpp:10", HASH_LABEL2),
            _make_finding("controller_suppressed.cpp:14", HASH_KNOB1),
            _make_finding("controller_suppressed.cpp:17", HASH_KNOB2),
        ]

        active, suppressed = apply_suppressions(all_findings, target_root=FIXTURE_DIR)

        # Baseline has label2 and knob2 (the two unsuppressed ones)
        baseline = BaselineData(
            legacy_keys={
                ("cpp-raw-memory", "controller_suppressed.cpp:10", "cpp-raw-new"),
                ("cpp-raw-memory", "controller_suppressed.cpp:17", "cpp-raw-new"),
            },
            stable_keys={
                ("cpp-raw-memory", "controller_suppressed.cpp", "cpp-raw-new", HASH_LABEL2),
                ("cpp-raw-memory", "controller_suppressed.cpp", "cpp-raw-new", HASH_KNOB2),
            },
            finding_count=2,
        )

        new_only = filter_new_findings(active, baseline)
        assert len(new_only) == 0

    def test_suppression_plus_baseline_classification(self, tmp_path: Path) -> None:
        """Suppressed findings excluded before classify_findings — only active
        findings appear in the classification.
        """
        baseline_path = _build_baseline(
            [
                _make_finding("controller_suppressed.cpp:10", HASH_LABEL2),
                _make_finding("controller_suppressed.cpp:17", HASH_KNOB2),
            ],
            tmp_path,
        )
        baseline = load_baseline(baseline_path)

        all_findings = [
            _make_finding("controller_suppressed.cpp:7", HASH_LABEL1),
            _make_finding("controller_suppressed.cpp:10", HASH_LABEL2),
            _make_finding("controller_suppressed.cpp:14", HASH_KNOB1),
            _make_finding("controller_suppressed.cpp:17", HASH_KNOB2),
        ]

        active, suppressed = apply_suppressions(all_findings, target_root=FIXTURE_DIR)
        result = classify_findings(active, baseline)

        assert len(result.new) == 0
        assert len(result.shifted) == 0

    def test_is_finding_suppressed_direct(self) -> None:
        """Direct test of is_finding_suppressed against fixture file."""
        cache: dict[str, list[str]] = {}
        suppressed_f = _make_finding("controller_suppressed.cpp:7", HASH_LABEL1)
        unsuppressed_f = _make_finding("controller_suppressed.cpp:10", HASH_LABEL2)

        assert is_finding_suppressed(suppressed_f, cache, target_root=FIXTURE_DIR) is not None
        assert is_finding_suppressed(unsuppressed_f, cache, target_root=FIXTURE_DIR) is None
