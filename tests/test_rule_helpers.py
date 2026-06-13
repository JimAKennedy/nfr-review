# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for rule_helpers — make_green_finding and filter_evidence."""

from __future__ import annotations

from nfr_review.models import Evidence, Finding
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


def _make_evidence(
    collector_name: str = "test-collector",
    collector_version: str = "1.0.0",
    kind: str = "test-kind",
) -> Evidence:
    return Evidence(
        collector_name=collector_name,
        collector_version=collector_version,
        locator="test-file.py",
        kind=kind,
        payload={},
    )


class TestMakeGreenFinding:
    def test_with_evidence_ref(self) -> None:
        ev = _make_evidence(collector_name="python-ast", collector_version="2.1.0")
        f = make_green_finding("my-rule", "my-pattern", ev)

        assert isinstance(f, Finding)
        assert f.rule_id == "my-rule"
        assert f.rag == "green"
        assert f.severity == "info"
        assert f.pattern_tag == "my-pattern"
        assert f.collector_name == "python-ast"
        assert f.collector_version == "2.1.0"
        assert f.confidence == 0.85
        assert f.recommendation == "No action required."
        assert f.evidence_locator == "project-wide"

    def test_default_summary(self) -> None:
        ev = _make_evidence()
        f = make_green_finding("r1", "bare-except", ev)
        assert f.summary == "No bare-except issues detected."

    def test_custom_summary(self) -> None:
        ev = _make_evidence()
        f = make_green_finding("r1", "tag", ev, summary="All clear.")
        assert f.summary == "All clear."

    def test_custom_confidence(self) -> None:
        ev = _make_evidence()
        f = make_green_finding("r1", "tag", ev, confidence=0.95)
        assert f.confidence == 0.95

    def test_custom_evidence_locator(self) -> None:
        ev = _make_evidence()
        f = make_green_finding("r1", "tag", ev, evidence_locator="all-tf-files")
        assert f.evidence_locator == "all-tf-files"

    def test_custom_recommendation(self) -> None:
        ev = _make_evidence()
        f = make_green_finding("r1", "tag", ev, recommendation="Keep it up.")
        assert f.recommendation == "Keep it up."

    def test_explicit_collector_fields(self) -> None:
        f = make_green_finding(
            "r1",
            "tag",
            collector_name="manual-collector",
            collector_version="0.0.1",
        )
        assert f.collector_name == "manual-collector"
        assert f.collector_version == "0.0.1"

    def test_evidence_ref_overrides_empty_explicit(self) -> None:
        ev = _make_evidence(collector_name="from-ev", collector_version="3.0.0")
        f = make_green_finding("r1", "tag", ev)
        assert f.collector_name == "from-ev"
        assert f.collector_version == "3.0.0"

    def test_explicit_overrides_evidence_ref(self) -> None:
        ev = _make_evidence(collector_name="from-ev", collector_version="3.0.0")
        f = make_green_finding(
            "r1", "tag", ev, collector_name="explicit", collector_version="9.9.9"
        )
        assert f.collector_name == "explicit"
        assert f.collector_version == "9.9.9"


class TestFilterEvidence:
    def test_filter_by_collector_and_kind(self) -> None:
        evs = [
            _make_evidence(collector_name="python-ast", kind="python-ast-file"),
            _make_evidence(collector_name="java-ast", kind="java-ast-file"),
            _make_evidence(collector_name="python-ast", kind="other-kind"),
        ]
        result = filter_evidence(evs, "python-ast", "python-ast-file")
        assert len(result) == 1
        assert result[0].collector_name == "python-ast"
        assert result[0].kind == "python-ast-file"

    def test_filter_by_collector_only(self) -> None:
        evs = [
            _make_evidence(collector_name="python-ast", kind="python-ast-file"),
            _make_evidence(collector_name="java-ast", kind="java-ast-file"),
            _make_evidence(collector_name="python-ast", kind="other-kind"),
        ]
        result = filter_evidence(evs, "python-ast")
        assert len(result) == 2

    def test_empty_when_no_match(self) -> None:
        evs = [_make_evidence(collector_name="java-ast", kind="java-ast-file")]
        result = filter_evidence(evs, "python-ast", "python-ast-file")
        assert result == []

    def test_empty_input(self) -> None:
        result = filter_evidence([], "python-ast", "python-ast-file")
        assert result == []
