# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Monitor engine — ties OTLP receiver, window manager, and alert output."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

from aiohttp import web

from nfr_review.monitor.baseline import InteractionBaseline, load_baseline
from nfr_review.monitor.receiver import OtlpReceiver
from nfr_review.monitor.window import WindowManager, WindowResult

logger = logging.getLogger(__name__)


@dataclass
class MonitorConfig:
    """Configuration for the production monitor."""

    baseline_path: Path
    host: str = "0.0.0.0"  # nosec B104
    port: int = 4318
    window_seconds: float = 60.0
    max_body_bytes: int = 16 * 1024 * 1024
    deduplicate: bool = True


@dataclass
class Alert:
    """A JSON-serialisable alert emitted to stdout."""

    timestamp: str
    window_span_count: int
    window_fingerprint_count: int
    finding_rule_id: str
    finding_severity: str
    finding_summary: str
    finding_evidence: str


def _format_alert(finding, window_result: WindowResult) -> str:
    alert = Alert(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        window_span_count=window_result.span_count,
        window_fingerprint_count=window_result.fingerprint_count,
        finding_rule_id=finding.rule_id,
        finding_severity=finding.severity,
        finding_summary=finding.summary,
        finding_evidence=finding.evidence_locator,
    )
    return json.dumps(asdict(alert), separators=(",", ":"))


class MonitorEngine:
    """Long-lived monitor: receives OTLP spans, windows them, emits alerts."""

    def __init__(
        self,
        config: MonitorConfig,
        *,
        alert_stream: TextIO | None = None,
    ) -> None:
        self._config = config
        self._alert_stream: TextIO = alert_stream or sys.stdout
        self._baseline: InteractionBaseline | None = None
        self._window: WindowManager | None = None
        self._receiver: OtlpReceiver | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._runner: web.AppRunner | None = None

    @property
    def receiver(self) -> OtlpReceiver | None:
        return self._receiver

    @property
    def window_manager(self) -> WindowManager | None:
        return self._window

    def _load_baseline(self) -> InteractionBaseline:
        logger.info("loading baseline from %s", self._config.baseline_path)
        return load_baseline(self._config.baseline_path)

    def _emit_alerts(self, result: WindowResult) -> int:
        count = 0
        for finding in result.novel_findings:
            line = _format_alert(finding, result)
            self._alert_stream.write(line + "\n")
            self._alert_stream.flush()
            count += 1
        return count

    async def _window_loop(self) -> None:
        assert self._window is not None
        assert self._shutdown_event is not None
        interval = self._config.window_seconds
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=interval,
                )
                break
            except TimeoutError:
                pass

            result = self._window.flush(deduplicate=self._config.deduplicate)
            if result.span_count > 0:
                alert_count = self._emit_alerts(result)
                logger.info(
                    "window flush: %d spans, %d fingerprints, %d novel alerts",
                    result.span_count,
                    result.fingerprint_count,
                    alert_count,
                )
            else:
                logger.debug("window flush: no spans in window")

        if self._window.pending_span_count > 0:
            result = self._window.flush(deduplicate=self._config.deduplicate)
            self._emit_alerts(result)
            logger.info("final flush: %d spans", result.span_count)

    async def run(self) -> None:
        """Start the monitor and run until shutdown signal."""
        self._baseline = self._load_baseline()
        self._window = WindowManager(
            self._baseline,
            window_seconds=self._config.window_seconds,
        )
        self._receiver = OtlpReceiver(
            on_spans=self._window.ingest,
            host=self._config.host,
            port=self._config.port,
            max_body_bytes=self._config.max_body_bytes,
        )
        self._receiver.ready = True
        self._shutdown_event = asyncio.Event()

        app = self._receiver.create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._config.host, self._config.port)
        await site.start()

        logger.info(
            "monitor started on %s:%d (window=%ds, baseline=%d fingerprints)",
            self._config.host,
            self._config.port,
            int(self._config.window_seconds),
            len(self._baseline.fingerprints),
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._request_shutdown)

        try:
            await self._window_loop()
        finally:
            logger.info("shutting down monitor")
            if self._runner:
                await self._runner.cleanup()

    def _request_shutdown(self) -> None:
        logger.info("shutdown signal received")
        if self._shutdown_event:
            self._shutdown_event.set()


__all__ = ["Alert", "MonitorConfig", "MonitorEngine"]
