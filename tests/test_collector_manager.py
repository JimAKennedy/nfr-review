# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the OTel Collector lifecycle manager."""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nfr_review.collector_manager import (
    CollectorManager,
    find_binary,
    resolve_config,
)

# ---------------------------------------------------------------------------
# find_binary
# ---------------------------------------------------------------------------


class TestFindBinary:
    def test_finds_otelcol_contrib_first(self):
        def fake_which(name: str) -> str | None:
            return "/usr/local/bin/otelcol-contrib" if name == "otelcol-contrib" else None

        with patch("nfr_review.collector_manager.shutil.which", side_effect=fake_which):
            result = find_binary()
        assert result == Path("/usr/local/bin/otelcol-contrib")

    def test_falls_back_to_otelcol(self):
        def fake_which(name: str) -> str | None:
            return "/usr/bin/otelcol" if name == "otelcol" else None

        with patch("nfr_review.collector_manager.shutil.which", side_effect=fake_which):
            result = find_binary()
        assert result == Path("/usr/bin/otelcol")

    def test_returns_none_when_not_found(self):
        with patch("nfr_review.collector_manager.shutil.which", return_value=None):
            result = find_binary()
        assert result is None


# ---------------------------------------------------------------------------
# resolve_config
# ---------------------------------------------------------------------------


class TestResolveConfig:
    def test_uses_repo_local_config(self, tmp_path: Path):
        repo_config = tmp_path / "otel-collector-config.yaml"
        repo_config.write_text("receivers: {}")
        result = resolve_config(tmp_path)
        assert result == repo_config

    def test_falls_back_to_bundled_config(self, tmp_path: Path):
        result = resolve_config(tmp_path)
        assert "otel-collector-config.yaml" in result.name
        assert result.exists()


# ---------------------------------------------------------------------------
# CollectorManager
# ---------------------------------------------------------------------------


class TestCollectorManager:
    def test_start_creates_temp_file_and_launches_process(self, tmp_path: Path):
        binary = tmp_path / "otelcol"
        binary.touch()
        config = tmp_path / "config.yaml"
        config.write_text("receivers: {}")

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 12345

        with patch("nfr_review.collector_manager.subprocess.Popen", return_value=mock_proc):
            mgr = CollectorManager(binary, config)
            trace_path = mgr.start()

        assert trace_path.suffix == ".ndjson"
        assert "nfr-otel-traces" in trace_path.name
        assert mgr._process is mock_proc
        mgr.cleanup()

    def test_start_uses_provided_trace_output(self, tmp_path: Path):
        binary = tmp_path / "otelcol"
        binary.touch()
        config = tmp_path / "config.yaml"
        config.write_text("receivers: {}")
        output = tmp_path / "traces.ndjson"

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 99

        with patch("nfr_review.collector_manager.subprocess.Popen", return_value=mock_proc):
            mgr = CollectorManager(binary, config, trace_output=output)
            result = mgr.start()

        assert result == output

    def test_start_raises_if_already_started(self, tmp_path: Path):
        binary = tmp_path / "otelcol"
        binary.touch()
        config = tmp_path / "config.yaml"
        config.write_text("receivers: {}")

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 1

        with patch("nfr_review.collector_manager.subprocess.Popen", return_value=mock_proc):
            mgr = CollectorManager(binary, config)
            mgr.start()
            with pytest.raises(RuntimeError, match="already started"):
                mgr.start()
        mgr.cleanup()

    def test_stop_sends_sigterm_and_waits(self, tmp_path: Path):
        binary = tmp_path / "otelcol"
        binary.touch()
        config = tmp_path / "config.yaml"
        config.write_text("receivers: {}")

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 42
        mock_proc.wait.return_value = 0

        with patch("nfr_review.collector_manager.subprocess.Popen", return_value=mock_proc):
            mgr = CollectorManager(binary, config)
            mgr.start()
            mgr.stop()

        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)
        mock_proc.wait.assert_called_once()
        assert mgr._process is None
        mgr.cleanup()

    def test_stop_escalates_to_sigkill_on_timeout(self, tmp_path: Path):
        binary = tmp_path / "otelcol"
        binary.touch()
        config = tmp_path / "config.yaml"
        config.write_text("receivers: {}")

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 42
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="otelcol", timeout=10), 0]

        with patch("nfr_review.collector_manager.subprocess.Popen", return_value=mock_proc):
            mgr = CollectorManager(binary, config)
            mgr.start()
            mgr.stop()

        mock_proc.kill.assert_called_once()
        mgr.cleanup()

    def test_stop_is_noop_when_not_started(self, tmp_path: Path):
        mgr = CollectorManager(tmp_path / "otelcol", tmp_path / "config.yaml")
        mgr.stop()  # should not raise

    def test_context_manager_calls_stop(self, tmp_path: Path):
        binary = tmp_path / "otelcol"
        binary.touch()
        config = tmp_path / "config.yaml"
        config.write_text("receivers: {}")

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 55
        mock_proc.wait.return_value = 0

        with patch("nfr_review.collector_manager.subprocess.Popen", return_value=mock_proc):
            with CollectorManager(binary, config) as mgr:
                assert mgr._process is mock_proc

        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_context_manager_stops_on_exception(self, tmp_path: Path):
        binary = tmp_path / "otelcol"
        binary.touch()
        config = tmp_path / "config.yaml"
        config.write_text("receivers: {}")

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 77
        mock_proc.wait.return_value = 0

        with patch("nfr_review.collector_manager.subprocess.Popen", return_value=mock_proc):
            with pytest.raises(ValueError, match="boom"):
                with CollectorManager(binary, config):
                    raise ValueError("boom")

        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_cleanup_removes_temp_file(self, tmp_path: Path):
        binary = tmp_path / "otelcol"
        binary.touch()
        config = tmp_path / "config.yaml"
        config.write_text("receivers: {}")

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 88
        mock_proc.wait.return_value = 0

        with patch("nfr_review.collector_manager.subprocess.Popen", return_value=mock_proc):
            mgr = CollectorManager(binary, config)
            trace_path = mgr.start()
            assert trace_path.exists()
            mgr.stop()
            mgr.cleanup()
            assert not trace_path.exists()

    def test_cleanup_skips_user_provided_file(self, tmp_path: Path):
        binary = tmp_path / "otelcol"
        binary.touch()
        config = tmp_path / "config.yaml"
        config.write_text("receivers: {}")
        output = tmp_path / "my-traces.ndjson"
        output.write_text("")

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 99
        mock_proc.wait.return_value = 0

        with patch("nfr_review.collector_manager.subprocess.Popen", return_value=mock_proc):
            mgr = CollectorManager(binary, config, trace_output=output)
            mgr.start()
            mgr.stop()
            mgr.cleanup()
            assert output.exists()

    def test_trace_output_raises_before_start(self, tmp_path: Path):
        mgr = CollectorManager(tmp_path / "otelcol", tmp_path / "config.yaml")
        with pytest.raises(RuntimeError, match="not started"):
            _ = mgr.trace_output


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLICollectorFlag:
    def test_run_help_shows_collector_flag(self):
        from nfr_review.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert "--collector" in result.output

    def test_report_help_shows_collector_flag(self):
        from nfr_review.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--help"])
        assert "--collector" in result.output

    def test_run_collector_and_otel_traces_mutually_exclusive(self, tmp_path: Path):
        from nfr_review.cli import cli

        target = tmp_path / "repo"
        target.mkdir()
        traces = tmp_path / "traces.ndjson"
        traces.write_text("{}")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["run", str(target), "--collector", "--otel-traces", str(traces)]
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_run_collector_warns_when_binary_missing(self, tmp_path: Path):
        from nfr_review.cli import cli

        target = tmp_path / "repo"
        target.mkdir()

        runner = CliRunner()
        with patch("nfr_review.collector_manager.shutil.which", return_value=None):
            result = runner.invoke(cli, ["run", str(target), "--collector"])

        assert result.exit_code == 0
        assert "not found" in result.output
