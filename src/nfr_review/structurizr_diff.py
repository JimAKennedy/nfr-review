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

import json
import logging
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from nfr_review.models import RAG, Finding
from nfr_review.structurizr_models import DslElement, DslRelationship, DslWorkspace

logger = logging.getLogger(__name__)

RULE_ID = "arch-drift"
COLLECTOR_NAME = "arch-drift"
COLLECTOR_VERSION = "1.0.0"

_DRIFT_RAG: dict[str, RAG] = {
    "high": "red",
    "medium": "amber",
    "low": "amber",
    "info": "green",
}

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


_DRIFT_RECOMMENDATION: dict[str, str] = {
    "element_added": (
        "Update the architecture baseline to include this element,"
        " or investigate whether it represents unplanned growth."
    ),
    "element_removed": (
        "Confirm whether this element was intentionally removed."
        " If so, update the baseline; otherwise restore it."
    ),
    "relationship_added": (
        "Review this new dependency for unplanned coupling."
        " Update the baseline if the relationship is intentional."
    ),
    "relationship_removed": (
        "Confirm whether this dependency was intentionally removed."
        " A missing relationship may indicate a broken integration."
    ),
    "technology_changed": (
        "Verify the technology change was intentional and update"
        " the architecture baseline to reflect it."
    ),
    "description_changed": (
        "Update the architecture baseline description if the"
        " change accurately reflects the current design."
    ),
    "tag_changed": (
        "Review the tag change and update the architecture"
        " baseline if it reflects a deliberate reclassification."
    ),
}


def findings_from_drift(
    report: DriftReport,
    baseline_path: str = "",
) -> list[Finding]:
    """Convert a DriftReport into standard Finding objects."""
    findings: list[Finding] = []
    for df in report.findings:
        rag = _DRIFT_RAG.get(df.severity, "amber")
        findings.append(
            Finding(
                rule_id=RULE_ID,
                rag=rag,
                severity=df.severity if df.severity != "info" else "low",
                summary=df.message,
                recommendation=_DRIFT_RECOMMENDATION.get(df.kind, "Review this drift."),
                evidence_locator=baseline_path,
                collector_name=COLLECTOR_NAME,
                collector_version=COLLECTOR_VERSION,
                confidence=1.0,
                pattern_tag=f"arch-drift:{df.kind}",
            )
        )
    return findings


def save_arch_baseline(workspace: DslWorkspace, path: Path) -> None:
    """Serialize a DslWorkspace to JSON for use as an architecture baseline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = workspace.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    logger.info("Saved architecture baseline to %s", path)


def load_arch_baseline(path: Path) -> DslWorkspace:
    """Load a DslWorkspace from a previously saved JSON baseline."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return DslWorkspace.model_validate(data)


__all__ = [
    "COLLECTOR_NAME",
    "COLLECTOR_VERSION",
    "RULE_ID",
    "DriftFinding",
    "DriftReport",
    "DriftSeverity",
    "diff_workspaces",
    "findings_from_drift",
    "load_arch_baseline",
    "render_drift_markdown",
    "save_arch_baseline",
]
