# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration discovery orchestration with strategy registry.

Dispatches integration discovery across focused strategy modules
(K8s, Compose, build systems, config files, gRPC) and provides the
public API consumed by ``arch_orchestrator``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

from nfr_review.arch_integ_build import (
    discover_cmake_integrations,
    discover_gradle_integrations,
    discover_maven_integrations,
    repo_name_from_url,
)
from nfr_review.arch_integ_compose import (
    discover_compose_env_integrations,
    discover_compose_integrations,
)
from nfr_review.arch_integ_config import (
    EMBEDDED_DB_TYPES,
    discover_config_integrations,
)
from nfr_review.arch_integ_grpc import discover_grpc_integrations
from nfr_review.arch_integ_k8s import (
    discover_k8s_env_integrations,
    discover_k8s_integrations,
)
from nfr_review.arch_integ_manifest import discover_manifest_cross_repo_integrations
from nfr_review.arch_models import (
    Component,
    ComponentBoundary,
    IntegrationPoint,
)
from nfr_review.arch_utils import discover_build_dep_integrations

logger = logging.getLogger(__name__)

ComponentType = Literal[
    "service", "library", "database", "queue", "gateway", "ui", "worker", "external"
]

# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

StrategyFn = Callable[[Path, list[Component], str], list[IntegrationPoint]]

_STRATEGIES: list[tuple[str, StrategyFn]] = [
    ("k8s", discover_k8s_integrations),
    ("compose", discover_compose_integrations),
    ("maven", discover_maven_integrations),
    ("gradle", discover_gradle_integrations),
    ("config", discover_config_integrations),
    ("compose-env", discover_compose_env_integrations),
    ("k8s-env", discover_k8s_env_integrations),
    ("grpc", discover_grpc_integrations),
    ("build-deps", discover_build_dep_integrations),
    ("cmake", discover_cmake_integrations),
    ("manifest-cross-repo", discover_manifest_cross_repo_integrations),
]


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate_integrations(
    integrations: list[IntegrationPoint],
) -> list[IntegrationPoint]:
    """Remove duplicate integration points (same source + target + style)."""
    seen: set[str] = set()
    result: list[IntegrationPoint] = []

    for intg in integrations:
        key = f"{intg.source_component_id}|{intg.target_component_id}|{intg.style}"
        if key not in seen:
            seen.add(key)
            result.append(intg)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Discover integration points in a single repository.

    Runs all registered strategies and returns a deduplicated list of
    IntegrationPoint objects.

    Parameters
    ----------
    repo_path:
        Path to the repository root.
    components:
        Pre-discovered components to match against.
    repo_name:
        Optional human-friendly name for the repository.

    Returns
    -------
    list[IntegrationPoint]
        Deduplicated integration points.
    """
    effective_name = repo_name or repo_path.name
    logger.info("Discovering integrations in %s", repo_path)

    all_integrations: list[IntegrationPoint] = []

    for strategy_name, strategy_fn in _STRATEGIES:
        try:
            all_integrations.extend(strategy_fn(repo_path, components, effective_name))
        except Exception:  # noqa: BLE001
            logger.warning(
                "Strategy %s failed for %s", strategy_name, repo_path, exc_info=True
            )

    result = _deduplicate_integrations(all_integrations)
    logger.info("Total integrations discovered: %d", len(result))
    return result


def discover_integrations_multi_repo(
    repo_paths: list[Path],
    all_components: list[Component],
    repo_names: list[str] | None = None,
) -> list[IntegrationPoint]:
    """Discover integrations across multiple repositories.

    Sets ``is_cross_repo=True`` on integration points where the source
    and target components belong to different repos.

    Parameters
    ----------
    repo_paths:
        Paths to each repository root.
    all_components:
        Components from all repos (with ``repo`` attribute set).
    repo_names:
        Optional human-friendly names for each repository.

    Returns
    -------
    list[IntegrationPoint]
        Deduplicated integration points with cross-repo flags.
    """
    if repo_names and len(repo_names) != len(repo_paths):
        raise ValueError("repo_names must match repo_paths in length")

    comp_repo: dict[str, str | None] = {}
    for comp in all_components:
        comp_repo[comp.id] = comp.repo

    all_integrations: list[IntegrationPoint] = []

    for i, repo_path in enumerate(repo_paths):
        name = repo_names[i] if repo_names else None
        intgs = discover_integrations(repo_path, all_components, repo_name=name)
        all_integrations.extend(intgs)

    result: list[IntegrationPoint] = []
    for intg in _deduplicate_integrations(all_integrations):
        src_repo = comp_repo.get(intg.source_component_id)
        tgt_repo = comp_repo.get(intg.target_component_id)
        if src_repo and tgt_repo and src_repo != tgt_repo:
            intg = intg.model_copy(update={"is_cross_repo": True})
        result.append(intg)

    return result


_PROTOCOL_TO_COMPONENT_TYPE: dict[str, str] = {
    "postgresql": "database",
    "mysql": "database",
    "mongodb": "database",
    "redis": "database",
    "cassandra": "database",
    "neo4j": "database",
    "h2": "database",
    "elasticsearch": "database",
    "kafka": "queue",
    "amqp": "queue",
    "nats": "queue",
    "smtp": "external",
    "http": "external",
    "https": "external",
    "grpc": "external",
}


def materialize_infra_components(
    components: list[Component],
    integrations: list[IntegrationPoint],
) -> list[Component]:
    """Create Component objects for infrastructure targets not already known.

    Integration discovery creates stable IDs via ``find_or_create_infra_id``
    but never materializes them as real Component objects. This means diagram
    edges to databases/queues are silently dropped because the target node
    doesn't exist.

    This function scans all integration endpoints, finds IDs with no matching
    component, and creates lightweight Component stubs so diagrams can render
    them.  When the same infra target is referenced with different environments,
    per-environment components are created and integration edges are rewritten
    to point to the env-specific copy.
    """
    known_ids = {c.id for c in components}

    infra_envs: dict[str, dict[str | None, list[int]]] = {}
    infra_meta: dict[str, tuple[str, ComponentType]] = {}

    for idx, intg in enumerate(integrations):
        for target_id in (intg.source_component_id, intg.target_component_id):
            if target_id in known_ids:
                continue
            if not target_id.startswith("infra-"):
                continue

            if target_id not in infra_meta:
                slug = target_id.split("-", 1)[1].rsplit("-", 1)[0]
                name = slug.replace("-", " ").title()
                comp_type: ComponentType = "database"
                if intg.protocol:
                    proto_key = intg.protocol.split(":")[0].lower()
                    raw = _PROTOCOL_TO_COMPONENT_TYPE.get(proto_key, "external")
                    comp_type = cast(ComponentType, raw)
                infra_meta[target_id] = (name, comp_type)

            infra_envs.setdefault(target_id, {}).setdefault(intg.environment, []).append(idx)

    comp_by_id = {c.id: c for c in components}

    new_components: dict[str, Component] = {}

    for base_id, env_map in infra_envs.items():
        name, comp_type = infra_meta[base_id]

        repo: str | None = None
        for intg_indices in env_map.values():
            for idx in intg_indices:
                intg = integrations[idx]
                for cid in (intg.source_component_id, intg.target_component_id):
                    peer = comp_by_id.get(cid)
                    if peer and peer.repo:
                        repo = peer.repo
                        break
                if repo:
                    break
            if repo:
                break

        slug = base_id.split("-", 1)[1].rsplit("-", 1)[0]
        if None in env_map and any(db in slug for db in EMBEDDED_DB_TYPES):
            indices = env_map.pop(None)
            env_map.setdefault("dev", []).extend(indices)
            for idx in indices:
                integrations[idx] = integrations[idx].model_copy(update={"environment": "dev"})

        envs = set(env_map.keys())

        if len(envs) <= 1:
            env = next(iter(envs))
            new_components[base_id] = Component(
                id=base_id,
                name=name,
                description=f"Infrastructure: {name}",
                component_type=comp_type,
                boundaries=[ComponentBoundary(boundary_type="repo", path=".")],
                environment=env,
                repo=repo,
            )
        else:
            for env, intg_indices in env_map.items():
                env_suffix = env or "default"
                env_id = f"{base_id}--{env_suffix}"
                display = f"{name} ({env_suffix})" if env else name
                new_components[env_id] = Component(
                    id=env_id,
                    name=display,
                    description=f"Infrastructure: {display}",
                    component_type=comp_type,
                    boundaries=[ComponentBoundary(boundary_type="repo", path=".")],
                    environment=env,
                    repo=repo,
                )
                for idx in intg_indices:
                    intg = integrations[idx]
                    updates: dict[str, str] = {}
                    if intg.source_component_id == base_id:
                        updates["source_component_id"] = env_id
                    if intg.target_component_id == base_id:
                        updates["target_component_id"] = env_id
                    if updates:
                        integrations[idx] = intg.model_copy(update=updates)

    if new_components:
        for comp in new_components.values():
            components.append(comp)
        logger.info("Materialized %d infrastructure components", len(new_components))

    return components


__all__ = [
    "discover_integrations",
    "discover_integrations_multi_repo",
    "materialize_infra_components",
    "repo_name_from_url",
]
