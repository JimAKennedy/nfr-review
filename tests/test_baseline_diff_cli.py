# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration tests for the ``nfr-review baseline diff`` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from nfr_review.cli import cli
from nfr_review.monitor.baseline import InteractionBaseline, save_baseline
from nfr_review.monitor.fingerprint import InteractionFingerprint

MULTI_SVC_TRACES = Path("tests/fixtures/otel-traces/traces-multi-service.ndjson")
TOPOLOGY_TRACES = Path("tests/fixtures/otel-traces/traces-multi-service-topology.json")


def _create_baseline_from_fixture(fixture: Path, out: Path) -> None:
    """Helper: create a baseline from a fixture trace file."""
    result = CliRunner().invoke(
        cli, ["baseline", "create", "--otel-traces", str(fixture), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output


def _make_partial_baseline(tmp_path: Path) -> Path:
    """Create a baseline with only a subset of interactions (simulates UAT gap)."""
    fp = InteractionFingerprint(
        caller_service="api-gateway",
        callee_service="greeting-service",
        operation="GET /api/greetings",
        span_kind=2,
        protocol="http",
    )
    bl = InteractionBaseline(
        source="partial-uat.ndjson",
        trace_count=1,
        span_count=5,
        fingerprints=[fp],
    )
    out = tmp_path / "partial.json"
    save_baseline(bl, out)
    return out


class TestBaselineDiffCLI:
    def test_diff_identical_no_findings(self, tmp_path: Path) -> None:
        bl = tmp_path / "bl.json"
        _create_baseline_from_fixture(MULTI_SVC_TRACES, bl)
        result = CliRunner().invoke(
            cli,
            [
                "baseline",
                "diff",
                "--baseline",
                str(bl),
                "--otel-traces",
                str(MULTI_SVC_TRACES),
            ],
        )
        assert result.exit_code == 0
        assert "No differences found" in result.output

    def test_diff_with_novel_interactions_md(self, tmp_path: Path) -> None:
        bl = _make_partial_baseline(tmp_path)
        result = CliRunner().invoke(
            cli,
            [
                "baseline",
                "diff",
                "--baseline",
                str(bl),
                "--otel-traces",
                str(MULTI_SVC_TRACES),
            ],
        )
        assert result.exit_code == 0
        assert "Novel Interactions" in result.output

    def test_diff_json_format(self, tmp_path: Path) -> None:
        bl = _make_partial_baseline(tmp_path)
        out = tmp_path / "diff.jsonl"
        result = CliRunner().invoke(
            cli,
            [
                "baseline",
                "diff",
                "--baseline",
                str(bl),
                "--otel-traces",
                str(MULTI_SVC_TRACES),
                "--format",
                "json",
                "-o",
                str(out),
            ],
        )
        assert result.exit_code == 0
        assert out.exists()
        lines = [ln for ln in out.read_text().strip().split("\n") if ln.strip()]
        assert len(lines) > 0
        for line in lines:
            data = json.loads(line)
            assert "rule_id" in data
            assert "severity" in data

    def test_diff_output_to_file(self, tmp_path: Path) -> None:
        bl = _make_partial_baseline(tmp_path)
        out = tmp_path / "diff.md"
        result = CliRunner().invoke(
            cli,
            [
                "baseline",
                "diff",
                "--baseline",
                str(bl),
                "--otel-traces",
                str(MULTI_SVC_TRACES),
                "-o",
                str(out),
            ],
        )
        assert result.exit_code == 0
        assert out.exists()
        content = out.read_text()
        assert "Novel Interactions" in content

    def test_diff_stats_to_stderr(self, tmp_path: Path) -> None:
        bl = _make_partial_baseline(tmp_path)
        result = CliRunner().invoke(
            cli,
            [
                "baseline",
                "diff",
                "--baseline",
                str(bl),
                "--otel-traces",
                str(MULTI_SVC_TRACES),
            ],
        )
        assert result.exit_code == 0
        assert "novel" in result.stderr
        assert "disappeared" in result.stderr

    def test_diff_missing_baseline(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "baseline",
                "diff",
                "--baseline",
                str(tmp_path / "nope.json"),
                "--otel-traces",
                str(MULTI_SVC_TRACES),
            ],
        )
        assert result.exit_code != 0

    def test_diff_empty_traces(self, tmp_path: Path) -> None:
        bl = _make_partial_baseline(tmp_path)
        empty = tmp_path / "empty.json"
        empty.write_text("{}")
        result = CliRunner().invoke(
            cli,
            ["baseline", "diff", "--baseline", str(bl), "--otel-traces", str(empty)],
        )
        assert result.exit_code != 0
        assert "no spans" in result.output.lower()

    def test_diff_cross_fixture(self, tmp_path: Path) -> None:
        """Diff topology traces against multi-service baseline."""
        bl = tmp_path / "bl.json"
        _create_baseline_from_fixture(MULTI_SVC_TRACES, bl)
        result = CliRunner().invoke(
            cli,
            ["baseline", "diff", "--baseline", str(bl), "--otel-traces", str(TOPOLOGY_TRACES)],
        )
        assert result.exit_code == 0
        assert (
            "Novel Interactions" in result.output
            or "Disappeared Interactions" in result.output
        )
