# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration tests for the ``nfr-review baseline create`` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from nfr_review.cli import cli
from nfr_review.monitor.baseline import BASELINE_FORMAT_VERSION

MULTI_SVC_TRACES = Path("tests/fixtures/otel-traces/traces-multi-service.ndjson")
TOPOLOGY_TRACES = Path("tests/fixtures/otel-traces/traces-multi-service-topology.json")


class TestBaselineCreateCLI:
    def test_creates_valid_baseline(self, tmp_path: Path) -> None:
        out = tmp_path / "baseline.json"
        result = CliRunner().invoke(
            cli, ["baseline", "create", "--otel-traces", str(MULTI_SVC_TRACES), "-o", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert out.exists()

        data = json.loads(out.read_text())
        assert data["version"] == BASELINE_FORMAT_VERSION
        assert len(data["fingerprints"]) > 0
        assert data["trace_count"] > 0
        assert data["span_count"] > 0

    def test_prints_summary_to_stderr(self, tmp_path: Path) -> None:
        out = tmp_path / "bl.json"
        result = CliRunner().invoke(
            cli, ["baseline", "create", "--otel-traces", str(MULTI_SVC_TRACES), "-o", str(out)]
        )
        assert result.exit_code == 0
        assert "fingerprints" in result.stderr
        assert "traces" in result.stderr
        assert "services" in result.stderr

    def test_prints_output_path_to_stdout(self, tmp_path: Path) -> None:
        out = tmp_path / "bl.json"
        result = CliRunner().invoke(
            cli, ["baseline", "create", "--otel-traces", str(MULTI_SVC_TRACES), "-o", str(out)]
        )
        assert result.exit_code == 0
        assert str(out) in result.output

    def test_deterministic_output(self, tmp_path: Path) -> None:
        out1 = tmp_path / "bl1.json"
        out2 = tmp_path / "bl2.json"
        for out in (out1, out2):
            result = CliRunner().invoke(
                cli,
                ["baseline", "create", "--otel-traces", str(MULTI_SVC_TRACES), "-o", str(out)],
            )
            assert result.exit_code == 0

        data1 = json.loads(out1.read_text())
        data2 = json.loads(out2.read_text())
        assert data1["fingerprints"] == data2["fingerprints"]
        assert data1["trace_count"] == data2["trace_count"]
        assert data1["span_count"] == data2["span_count"]

    def test_topology_fixture(self, tmp_path: Path) -> None:
        out = tmp_path / "topo.json"
        result = CliRunner().invoke(
            cli, ["baseline", "create", "--otel-traces", str(TOPOLOGY_TRACES), "-o", str(out)]
        )
        assert result.exit_code == 0
        data = json.loads(out.read_text())
        assert data["trace_count"] >= 2
        assert len(data["fingerprints"]) >= 3

    def test_missing_file(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "baseline",
                "create",
                "--otel-traces",
                str(tmp_path / "nope.ndjson"),
                "-o",
                str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0

    def test_empty_trace_file(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text("{}")
        out = tmp_path / "out.json"
        result = CliRunner().invoke(
            cli, ["baseline", "create", "--otel-traces", str(empty), "-o", str(out)]
        )
        assert result.exit_code != 0
        assert "no spans" in result.output.lower()
