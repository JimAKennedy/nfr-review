# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for baseline diff finding generation."""

from __future__ import annotations

from nfr_review.monitor.baseline import InteractionBaseline
from nfr_review.monitor.diff import (
    RULE_ID_DISAPPEARED,
    RULE_ID_NOVEL,
    generate_diff_findings,
)
from nfr_review.monitor.fingerprint import InteractionFingerprint


def _fp(
    caller: str = "a",
    callee: str = "b",
    op: str = "GET /x",
    kind: int = 3,
    proto: str = "http",
) -> InteractionFingerprint:
    return InteractionFingerprint(
        caller_service=caller,
        callee_service=callee,
        operation=op,
        span_kind=kind,
        protocol=proto,
    )


class TestGenerateDiffFindings:
    def test_novel_http_is_high_severity(self) -> None:
        bl = InteractionBaseline(fingerprints=[_fp(op="GET /a")])
        observed = {_fp(op="GET /a"), _fp(op="GET /new", proto="http")}
        findings = generate_diff_findings(bl, observed)
        novel = [f for f in findings if f.rule_id == RULE_ID_NOVEL]
        assert len(novel) == 1
        assert novel[0].severity == "high"
        assert novel[0].rag == "red"

    def test_novel_grpc_is_high(self) -> None:
        bl = InteractionBaseline()
        observed = {_fp(proto="grpc")}
        findings = generate_diff_findings(bl, observed)
        assert findings[0].severity == "high"

    def test_novel_db_is_medium(self) -> None:
        bl = InteractionBaseline()
        observed = {_fp(proto="db")}
        findings = generate_diff_findings(bl, observed)
        assert findings[0].severity == "medium"
        assert findings[0].rag == "amber"

    def test_novel_messaging_is_medium(self) -> None:
        bl = InteractionBaseline()
        observed = {_fp(proto="messaging")}
        findings = generate_diff_findings(bl, observed)
        assert findings[0].severity == "medium"

    def test_novel_unknown_is_low(self) -> None:
        bl = InteractionBaseline()
        observed = {_fp(proto="unknown")}
        findings = generate_diff_findings(bl, observed)
        assert findings[0].severity == "low"

    def test_disappeared_is_info(self) -> None:
        bl = InteractionBaseline(fingerprints=[_fp(op="GET /old")])
        observed: set[InteractionFingerprint] = set()
        findings = generate_diff_findings(bl, observed)
        disappeared = [f for f in findings if f.rule_id == RULE_ID_DISAPPEARED]
        assert len(disappeared) == 1
        assert disappeared[0].severity == "info"
        assert disappeared[0].rag == "green"

    def test_identical_no_findings(self) -> None:
        fp = _fp()
        bl = InteractionBaseline(fingerprints=[fp])
        findings = generate_diff_findings(bl, {fp})
        assert len(findings) == 0

    def test_mixed_novel_and_disappeared(self) -> None:
        bl = InteractionBaseline(fingerprints=[_fp(op="GET /a"), _fp(op="GET /b")])
        observed = {_fp(op="GET /a"), _fp(op="GET /c")}
        findings = generate_diff_findings(bl, observed)
        novel = [f for f in findings if f.rule_id == RULE_ID_NOVEL]
        disappeared = [f for f in findings if f.rule_id == RULE_ID_DISAPPEARED]
        assert len(novel) == 1
        assert len(disappeared) == 1

    def test_finding_has_fingerprint_hash_locator(self) -> None:
        bl = InteractionBaseline()
        fp = _fp()
        findings = generate_diff_findings(bl, {fp})
        assert findings[0].evidence_locator.startswith("fingerprint:")

    def test_finding_summary_includes_services(self) -> None:
        bl = InteractionBaseline()
        fp = _fp(caller="gateway", callee="orders", op="GET /api/orders")
        findings = generate_diff_findings(bl, {fp})
        assert "gateway" in findings[0].summary
        assert "orders" in findings[0].summary
        assert "GET /api/orders" in findings[0].summary

    def test_findings_are_sorted_by_hash(self) -> None:
        bl = InteractionBaseline()
        fps = {_fp(op=f"GET /{i}") for i in range(10)}
        findings = generate_diff_findings(bl, fps)
        hashes = [f.evidence_locator.split(":")[1] for f in findings]
        assert hashes == sorted(hashes)
