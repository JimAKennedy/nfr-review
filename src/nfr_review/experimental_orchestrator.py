# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Orchestrator for experimental class-diagram-focused reviews."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from nfr_review import __version__
from nfr_review.experimental_models import (
    CrossRepoEdge,
    DynamicAnalysisSection,
    ExperimentalReport,
)
from nfr_review.models import Evidence
from nfr_review.output.topology import build_topology_graph, render_topology_mermaid

logger = logging.getLogger(__name__)


def _noop_progress(_phase: str, _detail: str) -> None:
    pass


def _find_cross_repo_edges(class_data: list[dict]) -> list[CrossRepoEdge]:
    """Identify class references where source repo differs from target repo.

    Scans base_classes and field type references to detect cross-repo
    relationships.
    """
    # Build a lookup from class name to repo
    name_to_repo: dict[str, str] = {}
    for cls in class_data:
        name = cls.get("name", "")
        repo = cls.get("repo", "")
        if name and repo:
            name_to_repo[name] = repo

    edges: list[CrossRepoEdge] = []
    seen: set[tuple[str, str, str, str]] = set()

    for cls in class_data:
        src_name = cls.get("name", "")
        src_repo = cls.get("repo", "")
        if not src_name or not src_repo:
            continue

        # Check base classes
        for base in cls.get("base_classes", []):
            base_name = base.get("name", "") if isinstance(base, dict) else str(base)
            if not base_name:
                continue
            tgt_repo = name_to_repo.get(base_name, "")
            if tgt_repo and tgt_repo != src_repo:
                key = (src_repo, tgt_repo, src_name, base_name)
                if key not in seen:
                    seen.add(key)
                    edges.append(
                        CrossRepoEdge(
                            source_repo=src_repo,
                            target_repo=tgt_repo,
                            source_class=src_name,
                            target_class=base_name,
                        )
                    )

        # Check field types for references to classes in other repos
        for field in cls.get("fields", []):
            field_type = field.get("type", "") if isinstance(field, dict) else ""
            for known_name, known_repo in name_to_repo.items():
                if known_name in field_type and known_repo != src_repo:
                    key = (src_repo, known_repo, src_name, known_name)
                    if key not in seen:
                        seen.add(key)
                        edges.append(
                            CrossRepoEdge(
                                source_repo=src_repo,
                                target_repo=known_repo,
                                source_class=src_name,
                                target_class=known_name,
                            )
                        )

    return edges


def _build_dynamic_analysis(
    evidence: list[Evidence],
    cb: Callable[[str, str], None],
) -> DynamicAnalysisSection | None:
    """Build a dynamic analysis section from OTel trace evidence."""
    trace_evidence = [
        e for e in evidence if e.collector_name == "otel-trace" and e.kind == "otel-trace"
    ]
    if not trace_evidence:
        cb("dynamic", "No OTel trace evidence found — skipping dynamic analysis")
        return None

    cb("dynamic", f"Building topology from {len(trace_evidence)} trace evidence item(s)")
    graph = build_topology_graph(trace_evidence)

    if not graph.services:
        cb("dynamic", "No services found in trace data")
        return None

    mermaid = render_topology_mermaid(graph)
    section = DynamicAnalysisSection(
        service_count=len(graph.services),
        edge_count=len(graph.edges),
        topology_mermaid=mermaid,
        services=sorted(graph.services),
    )
    cb(
        "dynamic",
        f"Topology: {section.service_count} services, {section.edge_count} edges",
    )
    return section


def run_experimental_review(
    targets: list[Path],
    *,
    evidence: list[Evidence] | None = None,
    progress_callback: Callable[[str, str], None] | None = None,
) -> ExperimentalReport:
    """Run an experimental class-diagram-focused review.

    Parameters
    ----------
    targets:
        One or more repository root directories to analyze.
    evidence:
        Optional pre-collected evidence list.  When OTel trace evidence
        is present, a Dynamic Analysis section is added to the report.
    progress_callback:
        Optional callback invoked with ``(phase, detail)`` status messages.

    Returns
    -------
    ExperimentalReport
        A report containing class diagrams, cross-repo edges, and
        optionally a dynamic analysis topology.
    """
    from nfr_review.arch_diagrams import render_partitioned_class_diagrams
    from nfr_review.arch_orchestrator import _collect_class_data

    cb = progress_callback or _noop_progress

    repo_name = targets[0].name if targets else "unknown"

    # --- collect class data ---
    cb("collecting", "Extracting class data from source files...")

    def _progress_adapter(msg: str) -> None:
        cb("collecting", msg)

    class_data = _collect_class_data(targets, _progress_adapter)

    # --- dynamic analysis (independent of class data) ---
    dynamic_section: DynamicAnalysisSection | None = None
    if evidence:
        dynamic_section = _build_dynamic_analysis(evidence, cb)

    if class_data is None:
        cb("collecting", "No class data found")
        return ExperimentalReport(
            repo_name=repo_name,
            dynamic_analysis=dynamic_section,
            metadata={
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "version": __version__,
                "repos_analyzed": len(targets),
            },
        )

    cb("collecting", f"Found {len(class_data)} classes across {len(targets)} target(s)")

    # --- filter class data by target repos ---
    target_repo_names = {t.name for t in targets}
    scoped_data = [cls for cls in class_data if cls.get("repo", "") in target_repo_names]
    if not scoped_data:
        scoped_data = class_data

    cb("filtering", f"Scoped to {len(scoped_data)} classes for target repos")

    # --- detect cross-repo edges ---
    cb("edges", "Detecting cross-repo class references...")
    cross_repo_edges = _find_cross_repo_edges(class_data)
    if cross_repo_edges:
        cb("edges", f"Found {len(cross_repo_edges)} cross-repo edge(s)")
    else:
        cb("edges", "No cross-repo edges detected")

    # --- render class diagrams ---
    cb("diagrams", "Rendering partitioned class diagrams...")
    class_diagrams = render_partitioned_class_diagrams(
        scoped_data,
        title_prefix="Class Diagram",
        group_by_namespace=True,
    )
    cb("diagrams", f"Generated {len(class_diagrams)} class diagram(s)")

    # --- assemble report ---
    metadata = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": __version__,
        "repos_analyzed": len(targets),
    }

    report = ExperimentalReport(
        repo_name=repo_name,
        class_diagrams=class_diagrams,
        cross_repo_edges=cross_repo_edges,
        dynamic_analysis=dynamic_section,
        metadata=metadata,
    )

    parts = [f"{len(class_diagrams)} diagrams", f"{len(cross_repo_edges)} cross-repo edges"]
    if dynamic_section:
        parts.append(f"{dynamic_section.service_count} services in topology")
    cb("complete", f"Experimental report: {', '.join(parts)}")
    return report


__all__ = [
    "run_experimental_review",
]
