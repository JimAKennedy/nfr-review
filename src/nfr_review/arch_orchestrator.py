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
    RepoInfo,
)

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
            except Exception:
                logger.debug("%s collection failed for %s", class_name, target, exc_info=True)
                continue
            for ev in evidence_list:
                if _is_vendor_path(ev.payload.get("file_path", "")):
                    continue
                for cls in ev.payload.get(payload_key, []):
                    if cls.get("name") and (
                        cls.get("base_classes") or cls.get("methods") or cls.get("fields")
                    ):
                        cls["language"] = language
                        all_classes.append(cls)
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
        llm_model=os.environ.get("NFR_LLM_MODEL", "claude-sonnet-4-20250514")
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
