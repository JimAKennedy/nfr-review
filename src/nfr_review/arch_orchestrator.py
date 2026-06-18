# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Orchestrator that wires all arch_* modules into a single pipeline."""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404 — git commands with hardcoded args
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from nfr_review import __version__
from nfr_review.arch_models import (
    ArchReport,
    ArchReportMetadata,
    CrossRepoEdge,
    DynamicAnalysisSection,
    RepoInfo,
)
from nfr_review.models import Evidence

if TYPE_CHECKING:
    from nfr_review.arch_discovery import DvcPipeline

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]


def _noop_progress(_msg: str) -> None:
    pass


def _git_info(repo_path: Path) -> tuple[str | None, str | None]:
    """Return (sha, branch) from a git repo, or (None, None) on failure."""
    sha = branch = None
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_path),
            check=False,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()[:12]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_path),
            check=False,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return sha, branch


_VENDOR_PATH_SEGMENTS = frozenset(
    {
        "vst3sdk",
        "vst3_sdk",
        "third_party",
        "thirdparty",
        "3rdparty",
        "vendor",
        "external",
        "deps",
        "build",
        "build-test",
        "cmake-build",
        "node_modules",
        ".build",
    }
)


def _is_vendor_path(file_path: str) -> bool:
    """Return True if the file is under a vendor/SDK directory."""
    parts = file_path.lower().split("/")
    return bool(_VENDOR_PATH_SEGMENTS.intersection(parts))


def _collect_dvc_pipeline_data(
    targets: list[Path], cb: ProgressCallback
) -> list[DvcPipeline] | None:
    """Collect DVC pipeline data from all targets."""
    from nfr_review.arch_discovery import parse_dvc_pipeline

    pipelines: list[DvcPipeline] = []
    for target in targets:
        dvc_yaml = target / "dvc.yaml"
        if not dvc_yaml.is_file():
            for child in sorted(target.iterdir()):
                if child.is_dir() and (child / "dvc.yaml").is_file():
                    result = parse_dvc_pipeline(child / "dvc.yaml")
                    if result:
                        pipelines.append(result)
            continue
        result = parse_dvc_pipeline(dvc_yaml)
        if result:
            pipelines.append(result)

    if pipelines:
        total_stages = sum(len(p.stages) for p in pipelines)
        cb(f"Found {len(pipelines)} DVC pipeline(s) with {total_stages} stages")
        return pipelines
    return None


def _find_cross_repo_edges(class_data: list[dict]) -> list[CrossRepoEdge]:
    """Identify class references where source repo differs from target repo."""
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
    cb: ProgressCallback,
) -> DynamicAnalysisSection | None:
    """Build a dynamic analysis section from OTel trace evidence."""
    from nfr_review.output.topology import build_topology_graph, render_topology_mermaid

    trace_evidence = [
        e for e in evidence if e.collector_name == "otel-trace" and e.kind == "otel-trace"
    ]
    if not trace_evidence:
        cb("No OTel trace evidence found — skipping dynamic analysis")
        return None

    cb(f"Building topology from {len(trace_evidence)} trace evidence item(s)")
    graph = build_topology_graph(trace_evidence)

    if not graph.services:
        cb("No services found in trace data")
        return None

    mermaid = render_topology_mermaid(graph)
    section = DynamicAnalysisSection(
        service_count=len(graph.services),
        edge_count=len(graph.edges),
        topology_mermaid=mermaid,
        services=sorted(graph.services),
    )
    cb(f"Topology: {section.service_count} services, {section.edge_count} edges")
    return section


def _collect_class_data(targets: list[Path], cb: ProgressCallback) -> list[dict] | None:
    """Collect enriched class data from C++, Java, Python, and Go files."""
    import importlib

    _COLLECTORS: list[tuple[str, str, str, str]] = [
        ("nfr_review.collectors.cpp_ast", "CppAstCollector", "classes", "C++"),
        ("nfr_review.collectors.java_ast", "JavaAstCollector", "classes", "Java"),
        ("nfr_review.collectors.python_ast", "PythonAstCollector", "classes", "Python"),
        ("nfr_review.collectors.go_ast", "GoAstCollector", "structs", "Go"),
    ]

    all_classes: list[dict] = []
    lang_counts: dict[str, int] = {}

    for module_path, class_name, payload_key, language in _COLLECTORS:
        try:
            mod = importlib.import_module(module_path)
            collector = getattr(mod, class_name)()
        except (ImportError, AttributeError):
            continue

        count = 0
        for target in targets:
            try:
                evidence_list = collector.collect(target, config=None)
            except Exception:  # noqa: BLE001
                logger.debug("%s collection failed for %s", class_name, target, exc_info=True)
                continue
            for ev in evidence_list:
                if _is_vendor_path(ev.payload.file_path):
                    continue
                for cls in getattr(ev.payload, payload_key, []):
                    if cls.get("name") and (
                        cls.get("base_classes") or cls.get("methods") or cls.get("fields")
                    ):
                        cls_dict = (
                            cls.model_dump() if hasattr(cls, "model_dump") else dict(cls)
                        )
                        cls_dict["language"] = language
                        cls_dict["repo"] = target.name
                        all_classes.append(cls_dict)
                        count += 1

        if count:
            lang_counts[language] = count

    if all_classes:
        parts = [f"{count} {lang}" for lang, count in sorted(lang_counts.items())]
        cb(f"Extracted {len(all_classes)} classes for class diagram ({', '.join(parts)})")
        return all_classes
    return None


def run_arch_review(
    targets: list[Path],
    *,
    repo_names: list[str] | None = None,
    skip_llm: bool = False,
    diagram_mode: str = "hierarchical",
    evidence: list[Evidence] | None = None,
    progress: ProgressCallback | None = None,
) -> ArchReport:
    """Run the full architecture review pipeline and return an ArchReport.

    Parameters
    ----------
    targets:
        One or more repository root directories to analyze.
    repo_names:
        Optional human-readable names for each target (defaults to dir name).
    skip_llm:
        If True, skip LLM-dependent analysis (domain model enhancement,
        market comparison).
    evidence:
        Optional pre-collected evidence list (e.g. OTel traces).
    progress:
        Optional callback invoked with status messages.
    """
    from nfr_review.arch_diagrams import generate_all_diagrams
    from nfr_review.arch_discovery import (
        discover_components,
        discover_components_multi_repo,
    )
    from nfr_review.arch_integrations import (
        discover_integrations,
        discover_integrations_multi_repo,
        materialize_infra_components,
    )
    from nfr_review.arch_recommendations import generate_recommendations
    from nfr_review.arch_risk_analysis import analyze_risks
    from nfr_review.arch_test_coverage import (
        assess_test_coverage,
        assess_test_coverage_multi_repo,
    )

    cb = progress or _noop_progress
    multi = len(targets) > 1

    if repo_names is None:
        repo_names = [t.resolve().name for t in targets]

    # --- metadata ---
    repos_info: list[RepoInfo] = []
    for target, name in zip(targets, repo_names, strict=True):
        sha, branch = _git_info(target)
        repos_info.append(
            RepoInfo(
                path=str(target.resolve()),
                name=name,
                git_sha=sha,
                git_branch=branch,
            )
        )

    # --- LLM client ---
    llm = None
    if not skip_llm:
        from nfr_review.llm_client import create_llm_client

        client = create_llm_client()
        if client.available:
            llm = client
            cb("LLM available — domain model and market analysis enabled")
        else:
            cb("LLM not available — skipping LLM-dependent analysis")

    # --- component discovery ---
    cb("Discovering components...")
    if multi:
        components = discover_components_multi_repo(targets, repo_names)
    else:
        components = discover_components(targets[0], repo_name=repo_names[0])
    cb(f"Found {len(components)} components")

    # --- integration mapping ---
    cb("Mapping integrations...")
    if multi:
        integrations = discover_integrations_multi_repo(targets, components, repo_names)
    else:
        integrations = discover_integrations(targets[0], components, repo_name=repo_names[0])
    cb(f"Found {len(integrations)} integration points")

    # --- materialize infrastructure components ---
    prev_count = len(components)
    components = materialize_infra_components(components, integrations)
    new_infra = len(components) - prev_count
    if new_infra:
        cb(f"Materialized {new_infra} infrastructure components")

    # --- test coverage ---
    cb("Assessing test coverage...")
    if multi:
        test_coverage = assess_test_coverage_multi_repo(targets, components, repo_names)
    else:
        test_coverage = assess_test_coverage(targets[0], components, repo_name=repo_names[0])
    cb(f"Assessed coverage for {len(test_coverage)} components")

    # --- class extraction for class diagrams (C++, Java, Python, Go) ---
    class_data = _collect_class_data(targets, cb)

    # --- DVC pipeline extraction ---
    pipeline_data = _collect_dvc_pipeline_data(targets, cb)

    # --- C4 diagrams ---
    cb("Generating C4 diagrams...")
    diagrams = generate_all_diagrams(
        components,
        integrations,
        test_coverage,
        diagram_mode=diagram_mode,
        class_data=class_data,
        pipeline_data=pipeline_data,
    )
    cb(f"Generated {len(diagrams)} diagrams")

    # --- cross-repo edge detection ---
    cross_repo_edges: list[CrossRepoEdge] = []
    if class_data and multi:
        cb("Detecting cross-repo class references...")
        cross_repo_edges = _find_cross_repo_edges(class_data)
        if cross_repo_edges:
            cb(f"Found {len(cross_repo_edges)} cross-repo edge(s)")

    # --- dynamic analysis (from OTel evidence) ---
    dynamic_analysis: DynamicAnalysisSection | None = None
    if evidence:
        dynamic_analysis = _build_dynamic_analysis(evidence, cb)

    # --- risk analysis ---
    cb("Analyzing risks...")
    risks = analyze_risks(components, integrations, test_coverage)
    cb(f"Found {len(risks)} risk findings")

    # --- domain model ---
    domain_model = None
    cb("Inferring domain model...")
    from nfr_review.arch_domain_model import analyze_domain_model

    domain_model = analyze_domain_model(targets, components, llm=llm)
    if domain_model:
        cb(
            f"Domain model: {len(domain_model.entities)} entities, "
            f"{len(domain_model.bounded_contexts)} bounded contexts"
        )

    # --- market comparison ---
    market_analysis = None
    cb("Analyzing market positioning...")
    from nfr_review.arch_market_comparison import analyze_market

    market_analysis = analyze_market(targets, components, integrations, test_coverage, llm=llm)
    if market_analysis:
        cb(f"Market maturity: {market_analysis.overall_maturity}")

    # --- recommendations ---
    cb("Generating recommendations...")
    recommendations = generate_recommendations(
        components, integrations, test_coverage, risks, domain_model, market_analysis
    )
    cb(f"Generated {len(recommendations)} recommendations")

    # --- assemble report ---
    metadata = ArchReportMetadata(
        tool_version=__version__,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        repos_analyzed=repos_info,
        llm_available=llm is not None,
        llm_model=os.environ.get("NFR_LLM_MODEL", "claude-sonnet-4-6")
        if llm is not None
        else None,
    )

    report = ArchReport(
        metadata=metadata,
        components=components,
        integration_points=integrations,
        dynamic_scenarios=[],
        test_coverage=test_coverage,
        diagrams=diagrams,
        cross_repo_edges=cross_repo_edges,
        dynamic_analysis=dynamic_analysis,
        risk_findings=risks,
        domain_model=domain_model,
        market_analysis=market_analysis,
        recommendations=recommendations,
    )

    cb(
        f"Architecture report complete: {len(components)} components, "
        f"{len(risks)} risks, {len(recommendations)} recommendations"
    )
    return report


__all__ = [
    "ProgressCallback",
    "run_arch_review",
]
