# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for DriftReport → Finding conversion and baseline I/O."""

from __future__ import annotations

from nfr_review.structurizr_diff import (
    COLLECTOR_NAME,
    COLLECTOR_VERSION,
    RULE_ID,
    DriftFinding,
    DriftReport,
    findings_from_drift,
)


def _report(*drift_findings: DriftFinding) -> DriftReport:
    return DriftReport(
        baseline_name="baseline",
        scan_name="scan",
        findings=list(drift_findings),
    )


class TestFindingsFromDrift:
    def test_empty_report_produces_no_findings(self) -> None:
        assert findings_from_drift(_report()) == []

    def test_high_severity_maps_to_red_rag(self) -> None:
        df = DriftFinding(
            kind="element_added",
            severity="high",
            element_id="newSys",
            message="New softwareSystem 'NewSys' not in baseline",
        )
        findings = findings_from_drift(_report(df), baseline_path="/bl.json")
        assert len(findings) == 1
        f = findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert f.rule_id == RULE_ID
        assert f.collector_name == COLLECTOR_NAME
        assert f.collector_version == COLLECTOR_VERSION
        assert f.evidence_locator == "/bl.json"
        assert f.confidence == 1.0
        assert f.pattern_tag == "arch-drift:element_added"

    def test_medium_severity_maps_to_amber_rag(self) -> None:
        df = DriftFinding(
            kind="relationship_added",
            severity="medium",
            relationship_key="a -> b",
            message="New relationship a -> b",
        )
        findings = findings_from_drift(_report(df))
        assert findings[0].rag == "amber"
        assert findings[0].severity == "medium"
        assert findings[0].pattern_tag == "arch-drift:relationship_added"

    def test_low_severity_maps_to_amber_rag(self) -> None:
        df = DriftFinding(
            kind="description_changed",
            severity="low",
            element_id="svc",
            message="Description changed for 'Svc'",
        )
        findings = findings_from_drift(_report(df))
        assert findings[0].rag == "amber"
        assert findings[0].severity == "low"

    def test_info_severity_maps_to_green_rag(self) -> None:
        df = DriftFinding(
            kind="tag_changed",
            severity="info",
            element_id="svc",
            message="Tags changed",
        )
        findings = findings_from_drift(_report(df))
        f = findings[0]
        assert f.rag == "green"
        assert f.severity == "low"

    def test_all_drift_kinds_produce_correct_pattern_tags(self) -> None:
        kinds = [
            "element_added",
            "element_removed",
            "relationship_added",
            "relationship_removed",
            "technology_changed",
            "description_changed",
            "tag_changed",
        ]
        dfs = [DriftFinding(kind=k, severity="medium", message=f"msg-{k}") for k in kinds]
        findings = findings_from_drift(_report(*dfs))
        tags = [f.pattern_tag for f in findings]
        for k in kinds:
            assert f"arch-drift:{k}" in tags

    def test_multiple_findings_preserve_order(self) -> None:
        dfs = [
            DriftFinding(kind="element_added", severity="high", message="first"),
            DriftFinding(kind="element_removed", severity="medium", message="second"),
        ]
        findings = findings_from_drift(_report(*dfs))
        assert len(findings) == 2
        assert findings[0].summary == "first"
        assert findings[1].summary == "second"

    def test_recommendation_set_per_kind(self) -> None:
        df = DriftFinding(
            kind="technology_changed",
            severity="medium",
            message="tech changed",
        )
        findings = findings_from_drift(_report(df))
        assert "technology change" in findings[0].recommendation.lower()
