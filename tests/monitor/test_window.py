# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the time-windowed fingerprint accumulator."""

from __future__ import annotations

from nfr_review.collectors.payloads.otel_trace import OtelTraceSpan
from nfr_review.monitor.baseline import InteractionBaseline
from nfr_review.monitor.fingerprint import InteractionFingerprint
from nfr_review.monitor.window import WindowManager


def _make_span(
    service: str = "svc-a",
    name: str = "GET /api",
    kind: int = 3,
    trace_id: str = "t1",
    span_id: str = "s1",
    parent_span_id: str = "",
    attrs: dict[str, str] | None = None,
) -> OtelTraceSpan:
    return OtelTraceSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=name,
        service_name=service,
        kind=kind,
        start_time_unix_nano=1000000000,
        end_time_unix_nano=2000000000,
        status_code=0,
        code_namespace="",
        code_function="",
        attributes=attrs or {"http.method": "GET", "peer.service": "svc-b"},
    )


def _make_baseline(
    fingerprints: list[InteractionFingerprint] | None = None,
) -> InteractionBaseline:
    return InteractionBaseline(
        source="test",
        trace_count=1,
        span_count=1,
        fingerprints=fingerprints or [],
    )


class TestWindowManagerBasic:
    def test_empty_flush(self) -> None:
        wm = WindowManager(_make_baseline(), window_seconds=60)
        result = wm.flush()
        assert result.span_count == 0
        assert result.fingerprint_count == 0
        assert result.novel_count == 0
        assert wm.total_flushes == 1

    def test_ingest_and_flush(self) -> None:
        wm = WindowManager(_make_baseline(), window_seconds=60)
        spans = [_make_span()]
        wm.ingest(spans)
        assert wm.pending_span_count == 1
        assert wm.total_spans_ingested == 1

        result = wm.flush()
        assert result.span_count == 1
        assert result.fingerprint_count >= 1
        assert wm.pending_span_count == 0

    def test_novel_interactions_detected(self) -> None:
        baseline = _make_baseline()
        wm = WindowManager(baseline, window_seconds=60)
        wm.ingest([_make_span()])
        result = wm.flush()
        assert result.novel_count >= 1
        assert len(result.novel_findings) >= 1
        assert all(f.rule_id == "mon-novel-interaction" for f in result.novel_findings)

    def test_known_interactions_not_flagged(self) -> None:
        span = _make_span()
        from nfr_review.monitor.fingerprint import extract_fingerprints

        fps = list(extract_fingerprints([span]))
        baseline = _make_baseline(fps)

        wm = WindowManager(baseline, window_seconds=60)
        wm.ingest([span])
        result = wm.flush()
        assert result.novel_count == 0

    def test_should_flush_timing(self) -> None:
        wm = WindowManager(_make_baseline(), window_seconds=0.01)
        assert not wm.should_flush()
        import time

        time.sleep(0.02)
        assert wm.should_flush()


class TestWindowDeduplication:
    def test_duplicate_novel_suppressed_across_windows(self) -> None:
        baseline = _make_baseline()
        wm = WindowManager(baseline, window_seconds=60)

        span = _make_span()
        wm.ingest([span])
        r1 = wm.flush(deduplicate=True)
        assert r1.novel_count >= 1

        wm.ingest([span])
        r2 = wm.flush(deduplicate=True)
        assert r2.novel_count == 0

    def test_dedup_disabled_reports_again(self) -> None:
        baseline = _make_baseline()
        wm = WindowManager(baseline, window_seconds=60)

        span = _make_span()
        wm.ingest([span])
        r1 = wm.flush(deduplicate=False)
        assert r1.novel_count >= 1

        wm.ingest([span])
        r2 = wm.flush(deduplicate=False)
        assert r2.novel_count >= 1

    def test_reset_seen_allows_re_alert(self) -> None:
        baseline = _make_baseline()
        wm = WindowManager(baseline, window_seconds=60)

        span = _make_span()
        wm.ingest([span])
        wm.flush(deduplicate=True)

        wm.reset_seen()
        wm.ingest([span])
        r = wm.flush(deduplicate=True)
        assert r.novel_count >= 1


class TestWindowConcurrency:
    def test_concurrent_ingest(self) -> None:
        import concurrent.futures

        baseline = _make_baseline()
        wm = WindowManager(baseline, window_seconds=60)

        def ingest_batch(i: int) -> None:
            spans = [_make_span(span_id=f"s{i}_{j}") for j in range(10)]
            wm.ingest(spans)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(ingest_batch, range(4)))

        assert wm.total_spans_ingested == 40
        assert wm.pending_span_count == 40
