# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Detect architectural drift between a baseline DSL workspace and a scan workspace.

Compares element sets and relationship sets to surface:
- New elements in scan but absent in baseline (undocumented growth)
- Elements in baseline but absent in scan (dead architecture)
- New relationships (unplanned coupling)
- Missing relationships (removed dependency)
- Technology mismatches (tech-stack change)
"""

from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from nfr_review.structurizr_models import DslElement, DslRelationship, DslWorkspace

DriftKind = Literal[
    "element_added",
    "element_removed",
    "relationship_added",
    "relationship_removed",
    "technology_changed",
    "description_changed",
    "tag_changed",
]

DriftSeverity = Literal["info", "low", "medium", "high"]


class DriftFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DriftKind
    severity: DriftSeverity
    element_id: str = ""
    relationship_key: str = ""
    baseline_value: str = ""
    scan_value: str = ""
    message: str = ""


class DriftReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_name: str = ""
    scan_name: str = ""
    findings: list[DriftFinding] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return len(self.findings) > 0

    @property
    def max_severity(self) -> DriftSeverity:
        order: dict[str, int] = {"high": 3, "medium": 2, "low": 1, "info": 0}
        best = 0
        for f in self.findings:
            best = max(best, order.get(f.severity, 0))
        reverse = {v: k for k, v in order.items()}
        return cast(DriftSeverity, reverse.get(best, "info"))


def _collect_elements(ws: DslWorkspace) -> dict[str, DslElement]:
    """Flatten all elements into a dict keyed by identifier."""
    result: dict[str, DslElement] = {}

    def _walk(elem: DslElement, prefix: str = "") -> None:
        full_id = f"{prefix}.{elem.identifier}" if prefix else elem.identifier
        result[full_id] = elem
        for child in elem.children:
            _walk(child, full_id)

    for person in ws.model.people:
        _walk(person)
    for system in ws.model.software_systems:
        _walk(system)
    for group in ws.model.groups:
        for elem in group.elements:
            _walk(elem)

    return result


def _rel_key(rel: DslRelationship) -> str:
    return f"{rel.source_id} -> {rel.destination_id}"


def _collect_relationships(ws: DslWorkspace) -> dict[str, DslRelationship]:
    """Collect all relationships (explicit + implicit) keyed by source->dest."""
    result: dict[str, DslRelationship] = {}

    for rel in ws.model.relationships:
        result[_rel_key(rel)] = rel

    def _walk_implicit(elem: DslElement, prefix: str = "") -> None:
        full_id = f"{prefix}.{elem.identifier}" if prefix else elem.identifier
        for rel in elem.implicit_relationships:
            key = f"{full_id} -> {rel.destination_id}"
            result[key] = rel
        for child in elem.children:
            _walk_implicit(child, full_id)

    for person in ws.model.people:
        _walk_implicit(person)
    for system in ws.model.software_systems:
        _walk_implicit(system)

    return result


def _severity_for_element(elem: DslElement) -> DriftSeverity:
    if elem.element_type == "softwareSystem":
        return "high"
    if elem.element_type == "container":
        return "medium"
    return "low"


def diff_workspaces(
    baseline: DslWorkspace,
    scan: DslWorkspace,
) -> DriftReport:
    """Compare baseline and scan workspaces and return a drift report."""
    findings: list[DriftFinding] = []

    base_elems = _collect_elements(baseline)
    scan_elems = _collect_elements(scan)

    for eid, elem in scan_elems.items():
        if eid not in base_elems:
            findings.append(
                DriftFinding(
                    kind="element_added",
                    severity=_severity_for_element(elem),
                    element_id=eid,
                    scan_value=elem.name,
                    message=f"New {elem.element_type} '{elem.name}' not in baseline",
                )
            )

    for eid, elem in base_elems.items():
        if eid not in scan_elems:
            findings.append(
                DriftFinding(
                    kind="element_removed",
                    severity=_severity_for_element(elem),
                    element_id=eid,
                    baseline_value=elem.name,
                    message=(
                        f"{elem.element_type} '{elem.name}' in baseline but missing from scan"
                    ),
                )
            )

    for eid in base_elems.keys() & scan_elems.keys():
        base_elem = base_elems[eid]
        scan_elem = scan_elems[eid]

        if base_elem.technology != scan_elem.technology:
            findings.append(
                DriftFinding(
                    kind="technology_changed",
                    severity="medium",
                    element_id=eid,
                    baseline_value=base_elem.technology,
                    scan_value=scan_elem.technology,
                    message=(
                        f"Technology changed for '{base_elem.name}': "
                        f"'{base_elem.technology}' -> '{scan_elem.technology}'"
                    ),
                )
            )

        if base_elem.description != scan_elem.description:
            findings.append(
                DriftFinding(
                    kind="description_changed",
                    severity="low",
                    element_id=eid,
                    baseline_value=base_elem.description,
                    scan_value=scan_elem.description,
                    message=(
                        f"Description changed for '{base_elem.name}': "
                        f"'{base_elem.description}' -> '{scan_elem.description}'"
                    ),
                )
            )

        base_tags = set(base_elem.tags)
        scan_tags = set(scan_elem.tags)
        if base_tags != scan_tags:
            added = scan_tags - base_tags
            removed = base_tags - scan_tags
            parts = []
            if added:
                parts.append(f"added: {', '.join(sorted(added))}")
            if removed:
                parts.append(f"removed: {', '.join(sorted(removed))}")
            findings.append(
                DriftFinding(
                    kind="tag_changed",
                    severity="low",
                    element_id=eid,
                    baseline_value=", ".join(sorted(base_tags)),
                    scan_value=", ".join(sorted(scan_tags)),
                    message=f"Tags changed for '{base_elem.name}': {'; '.join(parts)}",
                )
            )

    base_rels = _collect_relationships(baseline)
    scan_rels = _collect_relationships(scan)

    for rkey, rel in scan_rels.items():
        if rkey not in base_rels:
            findings.append(
                DriftFinding(
                    kind="relationship_added",
                    severity="medium",
                    relationship_key=rkey,
                    scan_value=rel.description,
                    message=f"New relationship {rkey}: '{rel.description}'",
                )
            )

    for rkey, rel in base_rels.items():
        if rkey not in scan_rels:
            findings.append(
                DriftFinding(
                    kind="relationship_removed",
                    severity="medium",
                    relationship_key=rkey,
                    baseline_value=rel.description,
                    message=f"Relationship {rkey} ('{rel.description}') removed",
                )
            )

    return DriftReport(
        baseline_name=baseline.name,
        scan_name=scan.name,
        findings=findings,
    )


def render_drift_markdown(report: DriftReport) -> str:
    """Render a drift report as Markdown."""
    lines: list[str] = []
    lines.append("# Architectural Drift Report")
    lines.append("")
    lines.append(f"**Baseline:** {report.baseline_name}  ")
    lines.append(f"**Scan:** {report.scan_name}  ")
    lines.append(f"**Findings:** {len(report.findings)}  ")
    lines.append(f"**Max severity:** {report.max_severity}  ")
    lines.append("")

    if not report.findings:
        lines.append("No drift detected. Architecture matches baseline.")
        lines.append("")
        return "\n".join(lines)

    by_kind: dict[str, list[DriftFinding]] = {}
    for f in report.findings:
        by_kind.setdefault(f.kind, []).append(f)

    kind_labels: dict[str, str] = {
        "element_added": "New Elements (not in baseline)",
        "element_removed": "Removed Elements (in baseline, missing from scan)",
        "relationship_added": "New Relationships",
        "relationship_removed": "Removed Relationships",
        "technology_changed": "Technology Changes",
        "description_changed": "Description Changes",
        "tag_changed": "Tag Changes",
    }

    for kind_key, label in kind_labels.items():
        items = by_kind.get(kind_key, [])
        if not items:
            continue
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| Severity | ID | Details |")
        lines.append("|----------|----|---------| ")
        for f in sorted(items, key=lambda x: x.severity, reverse=True):
            eid = f.element_id or f.relationship_key
            lines.append(f"| {f.severity} | `{eid}` | {f.message} |")
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "DriftFinding",
    "DriftReport",
    "DriftSeverity",
    "diff_workspaces",
    "render_drift_markdown",
]
