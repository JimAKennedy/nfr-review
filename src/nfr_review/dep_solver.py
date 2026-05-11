"""Resolvelib-based dependency constraint solver.

Resolves a set of package dependencies to the most up-to-date compatible
versions using deps.dev as the version/dependency oracle, or identifies
which inter-package constraints make the set unsolvable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import resolvelib
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict

from nfr_review.deps_dev_client import DepsDevClient

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DepsDevRequirement:
    """A single package requirement with a PEP 440 specifier."""

    name: str
    specifier: str


@dataclass(frozen=True)
class DepsDevCandidate:
    """A resolved package at a specific version."""

    name: str
    version: str


class ResolveResult(BaseModel):
    """Outcome of a dependency resolution attempt."""

    model_config = ConfigDict(extra="forbid")

    optimal_set: dict[str, str]
    unsolvable: bool
    blocking_constraints: list[str]


class DepsDevProvider(resolvelib.AbstractProvider):
    """Resolvelib provider backed by the deps.dev API."""

    def __init__(self, client: DepsDevClient, ecosystem: str) -> None:
        self._client = client
        self._ecosystem = ecosystem
        self._versions_cache: dict[str, list[dict]] = {}
        self._deps_cache: dict[tuple[str, str], list[DepsDevRequirement]] = {}

    def identify(self, requirement_or_candidate: DepsDevRequirement | DepsDevCandidate) -> str:
        return requirement_or_candidate.name

    def get_preference(
        self,
        identifier: str,
        resolutions: Mapping[str, DepsDevCandidate],
        candidates: Mapping[str, Any],
        information: Mapping[str, Any],
        backtrack_causes: Sequence[Any],
    ) -> int:
        return -sum(1 for _ in information.get(identifier, []))

    def find_matches(
        self,
        identifier: str,
        requirements: Mapping[str, Any],
        incompatibilities: Mapping[str, Any],
    ) -> list[DepsDevCandidate]:
        if identifier not in self._versions_cache:
            data = self._client.get_package_versions(self._ecosystem, identifier)
            if data is None:
                logger.debug("deps.dev returned None for package versions: %s", identifier)
                self._versions_cache[identifier] = []
            else:
                self._versions_cache[identifier] = data.get("versions", [])

        raw_versions = self._versions_cache[identifier]

        parsed: list[tuple[Version, str]] = []
        for v_entry in raw_versions:
            v_str = v_entry.get("versionKey", {}).get("version", "")
            if not v_str:
                continue
            try:
                parsed.append((Version(v_str), v_str))
            except InvalidVersion:
                continue

        reqs = list(requirements.get(identifier, []))
        combined = SpecifierSet()
        for req in reqs:
            if req.specifier:
                try:
                    combined &= SpecifierSet(req.specifier)
                except InvalidSpecifier:
                    logger.debug(
                        "Invalid specifier %r for %s — treating as unconstrained",
                        req.specifier,
                        identifier,
                    )

        filtered = [
            (ver, ver_str)
            for ver, ver_str in parsed
            if ver_str in combined or not str(combined)
        ]

        incompat_versions = {c.version for c in incompatibilities.get(identifier, [])}
        filtered = [
            (ver, ver_str) for ver, ver_str in filtered if ver_str not in incompat_versions
        ]

        filtered.sort(key=lambda x: x[0], reverse=True)

        logger.debug(
            "find_matches %s: %d candidates after filtering", identifier, len(filtered)
        )

        return [DepsDevCandidate(name=identifier, version=vs) for _, vs in filtered]

    def is_satisfied_by(
        self, requirement: DepsDevRequirement, candidate: DepsDevCandidate
    ) -> bool:
        if not requirement.specifier:
            return True
        try:
            spec = SpecifierSet(requirement.specifier)
        except InvalidSpecifier:
            logger.debug(
                "Invalid specifier %r for %s — returning unsatisfied",
                requirement.specifier,
                requirement.name,
            )
            return False
        return candidate.version in spec

    def get_dependencies(self, candidate: DepsDevCandidate) -> list[DepsDevRequirement]:
        cache_key = (candidate.name, candidate.version)
        if cache_key in self._deps_cache:
            return self._deps_cache[cache_key]

        data = self._client.get_dependency_graph(
            self._ecosystem, candidate.name, candidate.version
        )
        if data is None:
            logger.debug(
                "deps.dev returned None for dependency graph: %s==%s",
                candidate.name,
                candidate.version,
            )
            self._deps_cache[cache_key] = []
            return []

        nodes: list[dict] = data.get("nodes", [])
        edges: list[dict] = data.get("edges", [])
        if not edges or not nodes:
            self._deps_cache[cache_key] = []
            return []

        deps: list[DepsDevRequirement] = []
        for edge in edges:
            if edge.get("fromNode") != 0:
                continue
            to_node = edge.get("toNode", -1)
            if to_node < 0 or to_node >= len(nodes):
                continue
            target = nodes[to_node]
            dep_name = target.get("versionKey", {}).get("name", "")
            if not dep_name:
                continue
            req_str = edge.get("requirement", "")
            deps.append(DepsDevRequirement(name=dep_name, specifier=req_str))

        self._deps_cache[cache_key] = deps
        return deps

    def narrow_requirement_selection(
        self,
        identifiers: Any,
        resolutions: Any,
        candidates: Any,
        information: Any,
        backtrack_causes: Any,
    ) -> Any:
        return identifiers


def resolve_dependencies(
    dependencies: list[dict],
    client: DepsDevClient,
    ecosystem: str,
) -> ResolveResult:
    """Resolve a set of dependencies to compatible versions.

    Args:
        dependencies: List of dicts with 'name' and optional 'version_constraint'.
        client: DepsDevClient instance for API lookups.
        ecosystem: Package ecosystem (e.g. 'pypi', 'npm').

    Returns:
        ResolveResult with the optimal version set or unsolvable diagnostics.
    """
    if not dependencies:
        return ResolveResult(optimal_set={}, unsolvable=False, blocking_constraints=[])

    requirements = [
        DepsDevRequirement(
            name=dep["name"],
            specifier=dep.get("version_constraint", ""),
        )
        for dep in dependencies
    ]

    logger.info(
        "Starting dependency resolution for %d packages in %s",
        len(requirements),
        ecosystem,
    )

    provider = DepsDevProvider(client, ecosystem)
    reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
    resolver = resolvelib.Resolver(provider, reporter)

    try:
        result = resolver.resolve(requirements, max_rounds=200)
    except resolvelib.ResolutionImpossible as exc:
        constraints: list[str] = []
        for cause in exc.causes:
            req = cause.requirement
            parent = cause.parent
            if parent is None:
                constraints.append(f"(root) requires {req.name}{req.specifier}")
            else:
                constraints.append(
                    f"{parent.name}=={parent.version} requires {req.name}{req.specifier}"
                )
        logger.info("Resolution failed: unsolvable constraints — %s", "; ".join(constraints))
        return ResolveResult(optimal_set={}, unsolvable=True, blocking_constraints=constraints)
    except resolvelib.ResolutionTooDeep:
        msg = (
            "Resolution exceeded maximum rounds — dependency graph "
            "may be circular or too complex"
        )
        logger.info("Resolution failed: %s", msg)
        return ResolveResult(optimal_set={}, unsolvable=True, blocking_constraints=[msg])

    optimal_set = {name: candidate.version for name, candidate in result.mapping.items()}
    logger.info("Resolution succeeded: %d packages resolved", len(optimal_set))
    return ResolveResult(optimal_set=optimal_set, unsolvable=False, blocking_constraints=[])


__all__ = [
    "DepsDevCandidate",
    "DepsDevProvider",
    "DepsDevRequirement",
    "ResolveResult",
    "resolve_dependencies",
]
