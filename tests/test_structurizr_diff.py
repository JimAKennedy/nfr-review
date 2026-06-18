# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Structurizr workspace drift detection."""

from __future__ import annotations

from nfr_review.structurizr_diff import diff_workspaces, render_drift_markdown
from nfr_review.structurizr_models import (
    DslElement,
    DslModel,
    DslRelationship,
    DslWorkspace,
)


def _ws(name: str, **model_kw) -> DslWorkspace:
    return DslWorkspace(name=name, model=DslModel(**model_kw))


class TestDiffElements:
    def test_identical_workspaces(self) -> None:
        ws = _ws(
            "Same",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                )
            ],
        )
        report = diff_workspaces(ws, ws)
        assert not report.has_drift
        assert report.max_severity == "info"

    def test_new_element_detected(self) -> None:
        baseline = _ws(
            "Baseline",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                )
            ],
        )
        scan = _ws(
            "Scan",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                ),
                DslElement(
                    identifier="b",
                    element_type="softwareSystem",
                    name="B",
                ),
            ],
        )
        report = diff_workspaces(baseline, scan)
        assert report.has_drift
        added = [f for f in report.findings if f.kind == "element_added"]
        assert len(added) == 1
        assert added[0].element_id == "b"
        assert added[0].severity == "high"

    def test_removed_element_detected(self) -> None:
        baseline = _ws(
            "Baseline",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                ),
                DslElement(
                    identifier="b",
                    element_type="softwareSystem",
                    name="B",
                ),
            ],
        )
        scan = _ws(
            "Scan",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                )
            ],
        )
        report = diff_workspaces(baseline, scan)
        removed = [f for f in report.findings if f.kind == "element_removed"]
        assert len(removed) == 1
        assert removed[0].element_id == "b"

    def test_technology_change_detected(self) -> None:
        baseline = _ws(
            "Baseline",
            software_systems=[
                DslElement(
                    identifier="svc",
                    element_type="softwareSystem",
                    name="Service",
                    children=[
                        DslElement(
                            identifier="api",
                            element_type="container",
                            name="API",
                            technology="Python",
                        )
                    ],
                )
            ],
        )
        scan = _ws(
            "Scan",
            software_systems=[
                DslElement(
                    identifier="svc",
                    element_type="softwareSystem",
                    name="Service",
                    children=[
                        DslElement(
                            identifier="api",
                            element_type="container",
                            name="API",
                            technology="Go",
                        )
                    ],
                )
            ],
        )
        report = diff_workspaces(baseline, scan)
        tech = [f for f in report.findings if f.kind == "technology_changed"]
        assert len(tech) == 1
        assert tech[0].baseline_value == "Python"
        assert tech[0].scan_value == "Go"

    def test_description_change_detected(self) -> None:
        baseline = _ws(
            "Baseline",
            software_systems=[
                DslElement(
                    identifier="svc",
                    element_type="softwareSystem",
                    name="Service",
                    description="Handles orders",
                )
            ],
        )
        scan = _ws(
            "Scan",
            software_systems=[
                DslElement(
                    identifier="svc",
                    element_type="softwareSystem",
                    name="Service",
                    description="Handles orders and payments",
                )
            ],
        )
        report = diff_workspaces(baseline, scan)
        desc = [f for f in report.findings if f.kind == "description_changed"]
        assert len(desc) == 1
        assert desc[0].baseline_value == "Handles orders"
        assert desc[0].scan_value == "Handles orders and payments"

    def test_tag_change_detected(self) -> None:
        baseline = _ws(
            "Baseline",
            software_systems=[
                DslElement(
                    identifier="svc",
                    element_type="softwareSystem",
                    name="Service",
                    tags=["Internal"],
                )
            ],
        )
        scan = _ws(
            "Scan",
            software_systems=[
                DslElement(
                    identifier="svc",
                    element_type="softwareSystem",
                    name="Service",
                    tags=["Internal", "Critical"],
                )
            ],
        )
        report = diff_workspaces(baseline, scan)
        tags = [f for f in report.findings if f.kind == "tag_changed"]
        assert len(tags) == 1
        assert "Critical" in tags[0].message


class TestDiffRelationships:
    def test_new_relationship(self) -> None:
        baseline = _ws(
            "Baseline",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                ),
                DslElement(
                    identifier="b",
                    element_type="softwareSystem",
                    name="B",
                ),
            ],
        )
        scan = _ws(
            "Scan",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                ),
                DslElement(
                    identifier="b",
                    element_type="softwareSystem",
                    name="B",
                ),
            ],
            relationships=[
                DslRelationship(
                    source_id="a",
                    destination_id="b",
                    description="Calls",
                )
            ],
        )
        report = diff_workspaces(baseline, scan)
        added = [f for f in report.findings if f.kind == "relationship_added"]
        assert len(added) == 1
        assert "a -> b" in added[0].relationship_key

    def test_removed_relationship(self) -> None:
        baseline = _ws(
            "Baseline",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                ),
                DslElement(
                    identifier="b",
                    element_type="softwareSystem",
                    name="B",
                ),
            ],
            relationships=[
                DslRelationship(
                    source_id="a",
                    destination_id="b",
                    description="Calls",
                )
            ],
        )
        scan = _ws(
            "Scan",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                ),
                DslElement(
                    identifier="b",
                    element_type="softwareSystem",
                    name="B",
                ),
            ],
        )
        report = diff_workspaces(baseline, scan)
        removed = [f for f in report.findings if f.kind == "relationship_removed"]
        assert len(removed) == 1


class TestDriftReport:
    def test_max_severity(self) -> None:
        baseline = _ws("Baseline")
        scan = _ws(
            "Scan",
            software_systems=[
                DslElement(
                    identifier="new_sys",
                    element_type="softwareSystem",
                    name="New System",
                )
            ],
        )
        report = diff_workspaces(baseline, scan)
        assert report.max_severity == "high"


class TestRenderDriftMarkdown:
    def test_no_drift(self) -> None:
        ws = _ws("Same")
        report = diff_workspaces(ws, ws)
        md = render_drift_markdown(report)
        assert "No drift detected" in md

    def test_drift_report_has_tables(self) -> None:
        baseline = _ws(
            "Baseline",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                )
            ],
        )
        scan = _ws(
            "Scan",
            software_systems=[
                DslElement(
                    identifier="a",
                    element_type="softwareSystem",
                    name="A",
                ),
                DslElement(
                    identifier="b",
                    element_type="softwareSystem",
                    name="B",
                ),
            ],
            relationships=[
                DslRelationship(
                    source_id="a",
                    destination_id="b",
                    description="Calls",
                )
            ],
        )
        report = diff_workspaces(baseline, scan)
        md = render_drift_markdown(report)
        assert "New Elements" in md
        assert "New Relationships" in md
        assert "| high |" in md
