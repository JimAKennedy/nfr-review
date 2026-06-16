# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Dependency analysis: tree resolution and upgrade recommendations.

Orchestrates dependency collectors, the resolvelib-based solver, and the
deps.dev API to produce a structured analysis of each ecosystem's
dependency tree with upgrade recommendations.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from packaging.version import InvalidVersion, Version

from nfr_review.dep_solver import ResolveResult, TreeNode, resolve_dependencies
from nfr_review.deps_dev_client import DepsDevClient
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

if TYPE_CHECKING:
    from collections.abc import Callable

    from nfr_review.config import Config

logger = logging.getLogger(__name__)

_KIND_TO_ECOSYSTEM: dict[str, str] = {
    "java-deps": "maven",
    "python-deps": "pypi",
    "go-deps": "go",
    "csharp-deps": "nuget",
    "nodejs-deps": "npm",
}


@dataclass
class DepUpgradeInfo:
    """Upgrade information for a single dependency."""

    name: str
    declared_version: str
    latest_version: str | None
    recommended_version: str | None
    gap_description: str


@dataclass
class EcosystemDepsReport:
    """Dependency analysis results for a single ecosystem."""

    ecosystem: str
    manifest_files: list[str]
    upgrades: list[DepUpgradeInfo]
    tree: list[TreeNode] | None = None
    unsolvable: bool = False
    blocking_constraints: list[str] = field(default_factory=list)


def _compute_gap(declared: str, target: str | None) -> str:
    if not target:
        return "unknown"
    try:
        d = Version(declared)
        t = Version(target)
    except InvalidVersion:
        return "unknown"
    if t <= d:
        return "up to date"
    d_rel = d.release
    t_rel = t.release
    d_major = d_rel[0] if d_rel else 0
    t_major = t_rel[0] if t_rel else 0
    d_minor = d_rel[1] if len(d_rel) > 1 else 0
    t_minor = t_rel[1] if len(t_rel) > 1 else 0
    if t_major != d_major:
        diff = t_major - d_major
        return f"{diff} major" if diff > 0 else "up to date"
    if t_minor != d_minor:
        diff = t_minor - d_minor
        return f"{diff} minor" if diff > 0 else "up to date"
    d_patch = d_rel[2] if len(d_rel) > 2 else 0
    t_patch = t_rel[2] if len(t_rel) > 2 else 0
    if t_patch != d_patch:
        diff = t_patch - d_patch
        return f"{diff} patch" if diff > 0 else "up to date"
    return "up to date"


_NORM_RE = re.compile(r"^v(\d)", re.IGNORECASE)


def _normalize_for_comparison(version: str, ecosystem: str) -> str:
    v = version.strip()
    if ecosystem == "go":
        m = _NORM_RE.match(v)
        if m:
            v = v[1:]
    return v


def _collect_dep_evidence(
    target: Path,
    config: Config,
) -> list[Evidence]:
    """Run only the dependency collectors and return their Evidence."""
    evidence: list[Evidence] = []
    for cid in collector_registry.ids():
        if not cid.endswith("-deps"):
            continue
        collector = collector_registry.get(cid)
        try:
            produced = collector.collect(target, config)
            evidence.extend(produced)
        except Exception:  # noqa: BLE001
            logger.warning("collector %s failed during deps analysis", cid, exc_info=True)
    return evidence


def _group_by_ecosystem(
    evidence_list: list[Evidence],
) -> dict[str, tuple[list[str], list[dict[str, Any]]]]:
    """Group dependency evidence by ecosystem.

    Returns mapping of ecosystem -> (manifest_files, dependencies).
    """
    result: dict[str, tuple[list[str], list[dict[str, Any]]]] = {}
    for ev in evidence_list:
        ecosystem = _KIND_TO_ECOSYSTEM.get(ev.kind)
        if ecosystem is None:
            continue
        deps = ev.payload.dependencies
        manifests = ev.payload.manifest_files_found
        if ecosystem in result:
            existing_manifests, existing_deps = result[ecosystem]
            existing_manifests.extend(manifests)
            existing_deps.extend(deps)
        else:
            result[ecosystem] = (list(manifests), list(deps))
    return result


def analyze_deps(
    target: Path,
    config: Config,
    *,
    resolve_transitive: bool = True,
    progress_callback: Callable[[str], None] | None = None,
    max_resolve_rounds: int | None = None,
) -> list[EcosystemDepsReport]:
    """Run dependency analysis on a target repository.

    Runs only the dependency collectors, resolves each ecosystem's deps,
    and returns structured reports with upgrade recommendations and
    optional dependency trees.

    Args:
        max_resolve_rounds: Maximum resolver iterations.  When *None*
            (the default), falls back to ``config.max_resolve_rounds``.
    """
    effective_max_rounds = (
        max_resolve_rounds if max_resolve_rounds is not None else config.max_resolve_rounds
    )

    if progress_callback:
        progress_callback("Collecting dependency manifests...")

    evidence = _collect_dep_evidence(target, config)
    grouped = _group_by_ecosystem(evidence)
    if not grouped:
        return []

    client = DepsDevClient()
    reports: list[EcosystemDepsReport] = []

    for ecosystem, (manifests, deps) in sorted(grouped.items()):
        if progress_callback:
            progress_callback(f"Resolving {ecosystem} dependencies ({len(deps)} packages)...")

        resolver_deps = []
        for dep in deps:
            name = dep.get("name", "")
            constraint = dep.get("version_constraint", "")
            if name:
                resolver_deps.append({"name": name, "version_constraint": constraint})

        result: ResolveResult = resolve_dependencies(
            resolver_deps,
            client,
            ecosystem,
            resolve_transitive=resolve_transitive,
            max_rounds=effective_max_rounds,
        )

        upgrades: list[DepUpgradeInfo] = []
        for dep in deps:
            name = dep.get("name", "")
            declared = dep.get("declared_version", "")
            latest = dep.get("latest_version")
            recommended = result.optimal_set.get(name)

            declared_norm = _normalize_for_comparison(declared, ecosystem)
            latest_norm = _normalize_for_comparison(latest, ecosystem) if latest else None
            gap = _compute_gap(declared_norm, latest_norm)

            upgrades.append(
                DepUpgradeInfo(
                    name=name,
                    declared_version=declared,
                    latest_version=latest,
                    recommended_version=recommended,
                    gap_description=gap,
                )
            )

        reports.append(
            EcosystemDepsReport(
                ecosystem=ecosystem,
                manifest_files=manifests,
                upgrades=upgrades,
                tree=result.tree,
                unsolvable=result.unsolvable,
                blocking_constraints=result.blocking_constraints,
            )
        )

    return reports


__all__ = [
    "DepUpgradeInfo",
    "EcosystemDepsReport",
    "analyze_deps",
]
