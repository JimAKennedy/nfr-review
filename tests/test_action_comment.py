# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/action_comment.py — PR comment generation."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
action_comment = importlib.import_module("action_comment")
sys.path.pop(0)

COMMENT_MARKER = action_comment.COMMENT_MARKER


def _write_jsonl(tmp_path: Path, records: list[dict]) -> Path:
    """Helper: write records as JSONL and return the path."""
    p = tmp_path / "output.jsonl"
    with p.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return p


# -- fixtures ----------------------------------------------------------------

_METADATA = {
    "record_type": "run_metadata",
    "tool_version": "0.1.0",
    "target_repo": "demo",
    "timestamp": "2026-05-23T12:00:00Z",
    "collector_versions": {},
    "rules_run": ["R001"],
    "rules_skipped": [],
}

_RED_FINDING = {
    "record_type": "finding",
    "rule_id": "R001",
    "rag": "red",
    "severity": "high",
    "summary": "No circuit breaker configured",
    "recommendation": "Add resilience4j or equivalent",
    "evidence_locator": "src/main/java/App.java:42",
    "collector_name": "java_ast",
    "collector_version": "0.1.0",
    "confidence": 0.9,
    "pattern_tag": "resilience",
}

_AMBER_FINDING = {
    "record_type": "finding",
    "rule_id": "R002",
    "rag": "amber",
    "severity": "medium",
    "summary": "Thread pool size not explicitly set",
    "recommendation": "Set explicit thread pool bounds",
    "evidence_locator": "src/main/resources/application.yaml",
    "collector_name": "spring_config",
    "collector_version": "0.1.0",
    "confidence": 0.7,
    "pattern_tag": "concurrency",
}

_GREEN_FINDING = {
    "record_type": "finding",
    "rule_id": "R003",
    "rag": "green",
    "severity": "info",
    "summary": "Health endpoint present",
    "recommendation": "",
    "evidence_locator": "src/main/java/Health.java",
    "collector_name": "java_ast",
    "collector_version": "0.1.0",
    "confidence": 1.0,
    "pattern_tag": "observability",
}


# -- tests --------------------------------------------------------------------


class TestMixedFindings:
    """Test comment generation with a mix of red, amber, and green findings."""

    def test_contains_marker(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, _AMBER_FINDING, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        assert COMMENT_MARKER in md

    def test_header_present(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, _AMBER_FINDING, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        assert "## NFR Review Results" in md

    def test_rag_counts(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, _AMBER_FINDING, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        # Table should contain the correct counts.
        assert "| 1 |" in md  # red=1, amber=1, green=1
        assert "| **3** |" in md  # total

    def test_red_status_line(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, _AMBER_FINDING, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        assert "Red findings detected" in md

    def test_top_findings_table(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, _AMBER_FINDING, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        assert "### Top Findings" in md
        assert "R001" in md
        assert "R002" in md

    def test_full_details_present(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, _AMBER_FINDING, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        assert "<details>" in md
        assert "Full finding details (3 findings)" in md

    def test_footer_version(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, _AMBER_FINDING, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        assert "nfr-review v0.1.0" in md


class TestNoFindings:
    """Test comment generation when there are no findings (all green scenario)."""

    def test_all_clear_message(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA])
        md = action_comment.generate_comment(p)
        assert "All clear" in md

    def test_zero_counts(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA])
        md = action_comment.generate_comment(p)
        assert "| **0** |" in md

    def test_no_top_findings_section(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA])
        md = action_comment.generate_comment(p)
        assert "### Top Findings" not in md

    def test_no_details_section(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA])
        md = action_comment.generate_comment(p)
        assert "<details>" not in md

    def test_header_still_present(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA])
        md = action_comment.generate_comment(p)
        assert "## NFR Review Results" in md


class TestOnlyRedFindings:
    """Test comment generation with only red findings."""

    def test_red_status(self, tmp_path: Path) -> None:
        red2 = {**_RED_FINDING, "rule_id": "R010", "summary": "Missing retry policy"}
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, red2])
        md = action_comment.generate_comment(p)
        assert "Red findings detected" in md

    def test_counts_correct(self, tmp_path: Path) -> None:
        red2 = {**_RED_FINDING, "rule_id": "R010", "summary": "Missing retry policy"}
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, red2])
        counts = action_comment._count_by_rag(action_comment._load_records(p))
        assert counts["red"] == 2
        assert counts["amber"] == 0
        assert counts["green"] == 0

    def test_all_reds_in_top(self, tmp_path: Path) -> None:
        red2 = {**_RED_FINDING, "rule_id": "R010", "summary": "Missing retry policy"}
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING, red2])
        md = action_comment.generate_comment(p)
        assert "R001" in md
        assert "R010" in md


class TestMarkdownStructure:
    """Test the overall markdown structure of the generated comment."""

    def test_starts_with_marker(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        assert md.startswith(COMMENT_MARKER)

    def test_ends_with_newline(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        assert md.endswith("\n")

    def test_rag_summary_table_format(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _GREEN_FINDING])
        md = action_comment.generate_comment(p)
        assert "### RAG Summary" in md
        assert "| Status | Count |" in md
        assert "|--------|-------|" in md

    def test_skipped_records_excluded_from_total(self, tmp_path: Path) -> None:
        skipped = {
            "record_type": "finding",
            "rule_id": "R099",
            "rag": "skipped",
            "severity": None,
            "summary": "rule skipped: no java detected",
            "recommendation": None,
            "evidence_locator": None,
            "collector_name": None,
            "collector_version": None,
            "confidence": None,
            "pattern_tag": None,
        }
        p = _write_jsonl(tmp_path, [_METADATA, _GREEN_FINDING, skipped])
        md = action_comment.generate_comment(p)
        # Total should be 1 (green), not 2 (skipped is excluded from total).
        assert "| **1** |" in md

    def test_details_section_closable(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_FINDING])
        md = action_comment.generate_comment(p)
        assert "<details>" in md
        assert "</details>" in md

    def test_long_summary_truncated_in_table(self, tmp_path: Path) -> None:
        long_finding = {
            **_RED_FINDING,
            "summary": "A" * 200,
        }
        p = _write_jsonl(tmp_path, [_METADATA, long_finding])
        md = action_comment.generate_comment(p)
        # The table row should contain a truncated version.
        assert "..." in md


class TestCountByRag:
    """Unit tests for the _count_by_rag helper."""

    def test_empty(self) -> None:
        assert action_comment._count_by_rag([]) == {
            "red": 0,
            "amber": 0,
            "green": 0,
            "skipped": 0,
        }

    def test_ignores_metadata(self) -> None:
        assert action_comment._count_by_rag([_METADATA]) == {
            "red": 0,
            "amber": 0,
            "green": 0,
            "skipped": 0,
        }

    def test_counts_all_rag_types(self) -> None:
        counts = action_comment._count_by_rag([_RED_FINDING, _AMBER_FINDING, _GREEN_FINDING])
        assert counts == {"red": 1, "amber": 1, "green": 1, "skipped": 0}
