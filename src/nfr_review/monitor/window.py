# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Time-windowed fingerprint accumulation and baseline comparison."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from nfr_review.collectors.payloads.otel_trace import OtelTraceSpan
from nfr_review.models import Finding
from nfr_review.monitor.baseline import InteractionBaseline
from nfr_review.monitor.diff import generate_diff_findings
from nfr_review.monitor.fingerprint import extract_fingerprints

logger = logging.getLogger(__name__)


@dataclass
class WindowResult:
    """Result of flushing a time window."""

    window_start: float
    window_end: float
    span_count: int
    fingerprint_count: int
    novel_findings: list[Finding]
    novel_count: int
    disappeared_count: int


class WindowManager:
    """Accumulates spans over time windows and diffs against a baseline.

    Thread-safe: multiple HTTP handler coroutines can call ``ingest``
    concurrently from the event loop, and ``flush`` can be called from
    a background task.
    """

    def __init__(
        self,
        baseline: InteractionBaseline,
        window_seconds: float = 60.0,
    ) -> None:
        self._baseline = baseline
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._spans: list[OtelTraceSpan] = []
        self._window_start: float = time.monotonic()
        self._total_spans_ingested: int = 0
        self._total_flushes: int = 0
        self._seen_hashes: set[str] = set()

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    @property
    def total_spans_ingested(self) -> int:
        return self._total_spans_ingested

    @property
    def total_flushes(self) -> int:
        return self._total_flushes

    @property
    def pending_span_count(self) -> int:
        with self._lock:
            return len(self._spans)

    def ingest(self, spans: list[OtelTraceSpan]) -> None:
        """Add spans to the current window. Thread-safe."""
        with self._lock:
            self._spans.extend(spans)
            self._total_spans_ingested += len(spans)

    def should_flush(self) -> bool:
        """Return True if the current window has elapsed."""
        return (time.monotonic() - self._window_start) >= self._window_seconds

    def flush(self, *, deduplicate: bool = True) -> WindowResult:
        """Close the current window and return comparison results.

        When *deduplicate* is True (default), only novel fingerprints
        not already seen in prior windows are reported.  This prevents
        repeated alerts for the same novel interaction across windows.
        """
        with self._lock:
            spans = self._spans
            self._spans = []
            window_start = self._window_start
            self._window_start = time.monotonic()
            self._total_flushes += 1

        fingerprints = extract_fingerprints(spans)
        findings = generate_diff_findings(self._baseline, fingerprints)

        novel_findings = [f for f in findings if f.rule_id == "mon-novel-interaction"]
        disappeared_count = sum(
            1 for f in findings if f.rule_id == "mon-disappeared-interaction"
        )

        if deduplicate:
            new_novel: list[Finding] = []
            for finding in novel_findings:
                h = finding.evidence_locator.removeprefix("fingerprint:")
                if h not in self._seen_hashes:
                    self._seen_hashes.add(h)
                    new_novel.append(finding)
            novel_findings = new_novel

        return WindowResult(
            window_start=window_start,
            window_end=time.monotonic(),
            span_count=len(spans),
            fingerprint_count=len(fingerprints),
            novel_findings=novel_findings,
            novel_count=len(novel_findings),
            disappeared_count=disappeared_count,
        )

    def reset_seen(self) -> None:
        """Clear the deduplication set (e.g. after a baseline reload)."""
        self._seen_hashes.clear()


__all__ = ["WindowManager", "WindowResult"]
