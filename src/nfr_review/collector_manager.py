"""OTel Collector lifecycle management for nfr-review.

Manages an OpenTelemetry Collector subprocess that receives traces during
a scan and writes them to a local file for Band 3 dynamic analysis.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess  # nosec B404 — args are not user input
import tempfile
from importlib.resources import files
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)

_BINARY_NAMES = ("otelcol-contrib", "otelcol")
_SHUTDOWN_TIMEOUT_S = 10
_TRACE_OUTPUT_ENV = "NFR_TRACE_OUTPUT_PATH"


def find_binary() -> Path | None:
    """Search PATH for an OTel Collector binary."""
    for name in _BINARY_NAMES:
        path = shutil.which(name)
        if path is not None:
            logger.info("Found OTel Collector binary: %s", path)
            return Path(path)
    return None


def resolve_config(repo_path: Path) -> Path:
    """Return the collector config to use.

    Checks the target repo root for ``otel-collector-config.yaml``,
    falling back to the bundled default shipped with nfr-review.
    """
    repo_config = repo_path / "otel-collector-config.yaml"
    if repo_config.is_file():
        logger.info("Using repo-local collector config: %s", repo_config)
        return repo_config

    bundled = files("nfr_review.data").joinpath("otel-collector-config.yaml")
    bundled_path = Path(str(bundled))
    logger.info("Using bundled collector config: %s", bundled_path)
    return bundled_path


class CollectorManager:
    """Context manager that starts/stops an OTel Collector subprocess."""

    def __init__(
        self,
        binary: Path,
        config_path: Path,
        trace_output: Path | None = None,
    ) -> None:
        self._binary = binary
        self._config_path = config_path
        self._process: subprocess.Popen[bytes] | None = None
        self._trace_output = trace_output
        self._owns_trace_file = trace_output is None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def trace_output(self) -> Path:
        """Path where the collector writes OTLP JSON traces."""
        if self._trace_output is None:
            raise RuntimeError("Collector not started yet")
        return self._trace_output

    def start(self) -> Path:
        """Start the collector subprocess, return the trace output path."""
        if self._process is not None:
            raise RuntimeError("Collector already started")

        if self._trace_output is None:
            fd, tmp = tempfile.mkstemp(suffix=".ndjson", prefix="nfr-otel-traces-")
            os.close(fd)
            self._trace_output = Path(tmp)

        env = {**os.environ, _TRACE_OUTPUT_ENV: str(self._trace_output)}

        cmd = [str(self._binary), "--config", str(self._config_path)]
        logger.info(
            "Starting OTel Collector: pid=pending binary=%s config=%s trace_output=%s",
            self._binary,
            self._config_path,
            self._trace_output,
        )
        self._process = subprocess.Popen(  # nosec B603
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info(
            "OTel Collector started: pid=%d trace_output=%s",
            self._process.pid,
            self._trace_output,
        )
        return self._trace_output

    def stop(self) -> None:
        """Stop the collector subprocess gracefully."""
        if self._process is None:
            return

        pid = self._process.pid
        logger.info("Stopping OTel Collector: pid=%d", pid)

        try:
            self._process.send_signal(signal.SIGTERM)
            self._process.wait(timeout=_SHUTDOWN_TIMEOUT_S)
            logger.info("OTel Collector stopped gracefully: pid=%d", pid)
        except subprocess.TimeoutExpired:
            logger.warning(
                "OTel Collector did not stop within %ds, sending SIGKILL: pid=%d",
                _SHUTDOWN_TIMEOUT_S,
                pid,
            )
            self._process.kill()
            self._process.wait(timeout=5)

        self._process = None

        if self._trace_output and self._trace_output.exists():
            size = self._trace_output.stat().st_size
            line_count = 0
            if size > 0:
                with open(self._trace_output) as f:
                    line_count = sum(1 for _ in f)
            logger.info(
                "Trace output: path=%s size=%d spans_approx=%d",
                self._trace_output,
                size,
                line_count,
            )

    def cleanup(self) -> None:
        """Remove the temp trace file if we created it."""
        if self._owns_trace_file and self._trace_output and self._trace_output.exists():
            self._trace_output.unlink(missing_ok=True)
            logger.debug("Cleaned up trace file: %s", self._trace_output)

    def __enter__(self) -> CollectorManager:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()
