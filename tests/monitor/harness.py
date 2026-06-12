# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Monitor test harness — wraps MonitorEngine lifecycle for concise tests."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

import aiohttp

from nfr_review.monitor.baseline import InteractionBaseline, save_baseline
from nfr_review.monitor.engine import MonitorConfig, MonitorEngine


class MonitorHarness:
    """Manages MonitorEngine lifecycle for integration tests.

    Usage::

        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(payload)
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []
    """

    def __init__(
        self,
        baseline: InteractionBaseline,
        tmp_dir: Path,
        *,
        window_seconds: float = 0.2,
        deduplicate: bool = True,
        max_queue_spans: int = 50_000,
    ) -> None:
        baseline_path = tmp_dir / f"baseline_{id(self)}.json"
        save_baseline(baseline, baseline_path)

        self._alert_buf = io.StringIO()
        self._config = MonitorConfig(
            baseline_path=baseline_path,
            host="127.0.0.1",
            port=0,
            window_seconds=window_seconds,
            deduplicate=deduplicate,
            max_queue_spans=max_queue_spans,
        )
        self._engine = MonitorEngine(self._config, alert_stream=self._alert_buf)
        self._task: asyncio.Task[None] | None = None
        self._session: aiohttp.ClientSession | None = None
        self._port: int | None = None

    @property
    def port(self) -> int:
        assert self._port is not None, "harness not started"
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def engine(self) -> MonitorEngine:
        return self._engine

    async def start(self) -> None:
        self._task = asyncio.create_task(self._engine.run())
        for _ in range(200):
            await asyncio.sleep(0.01)
            runner = self._engine._runner
            if runner and runner.sites:
                site = list(runner.sites)[0]
                sockets = getattr(site._server, "sockets", None) if site._server else None
                if sockets:
                    self._port = sockets[0].getsockname()[1]
                    break
        else:
            raise RuntimeError("MonitorEngine did not start within 2s")
        self._session = aiohttp.ClientSession()

    async def send_traces(self, payload: dict[str, Any]) -> int:
        """POST an OTLP JSON payload. Returns the HTTP status code."""
        assert self._session is not None, "harness not started"
        async with self._session.post(f"{self.base_url}/v1/traces", json=payload) as resp:
            return resp.status

    async def wait_for_flush(self, extra: float = 0.15) -> None:
        """Sleep long enough for at least one window flush cycle."""
        await asyncio.sleep(self._config.window_seconds + extra)

    def get_alerts(self) -> list[dict[str, Any]]:
        """Return all alert lines emitted so far, parsed as dicts."""
        output = self._alert_buf.getvalue().strip()
        if not output:
            return []
        return [json.loads(line) for line in output.splitlines()]

    def get_novel_alerts(self) -> list[dict[str, Any]]:
        """Return only novel-interaction alerts."""
        return [
            a for a in self.get_alerts() if a["finding_rule_id"] == "mon-novel-interaction"
        ]

    async def shutdown(self) -> None:
        self._engine._request_shutdown()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
        if self._session:
            await self._session.close()

    async def __aenter__(self) -> MonitorHarness:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.shutdown()


__all__ = ["MonitorHarness"]
