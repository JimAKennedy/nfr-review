"""Resolvelib-based dependency constraint solver.

Resolves a set of package dependencies to the most up-to-date compatible
versions using deps.dev as the version/dependency oracle, or identifies
which inter-package constraints make the set unsolvable.
"""

from __future__ import annotations

import logging
import re
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

_MAVEN_PRE_RE = re.compile(
    r"^(\d+(?:\.\d+)*)[.-](RC|CR|alpha|beta|M)(\d+)$",
    re.IGNORECASE,
)
_MAVEN_SUFFIX_RE = re.compile(
    r"^(\d+(?:\.\d+)*)[.-](?:RELEASE|Final|GA)$",
    re.IGNORECASE,
)
_PEP440_PRE_MAP: dict[str, str] = {
    "rc": "rc",
    "cr": "rc",
    "alpha": "a",
    "beta": "b",
    "m": "rc",
}
_GO_V_RE = re.compile(r"^v(\d+(?:\.\d+)*)(.*)$")
_NPM_SEMVER_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _npm_parts(m: re.Match) -> tuple[int, int, int]:  # type: ignore[type-arg]
    return int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)


def _normalize_npm_specifier(raw: str) -> str:
    """Convert an npm semver range to a PEP 440 specifier string."""
    raw = raw.strip()
    if not raw:
        return ""

    if "||" in raw:
        return ""

    if " - " in raw:
        left_str, right_str = raw.split(" - ", 1)
        left_m = _NPM_SEMVER_RE.match(left_str.strip())
        right_m = _NPM_SEMVER_RE.match(right_str.strip())
        if left_m and right_m:
            l_maj, l_min, l_pat = _npm_parts(left_m)
            r_maj, r_min, r_pat = _npm_parts(right_m)
            lower = f"{l_maj}.{l_min}.{l_pat}"
            if right_m.group(3) is not None:
                return f">={lower},<={r_maj}.{r_min}.{r_pat}"
            elif right_m.group(2) is not None:
                return f">={lower},<{r_maj}.{r_min + 1}.0"
            else:
                return f">={lower},<{r_maj + 1}.0.0"
        return ""

    if raw.startswith("^"):
        m = _NPM_SEMVER_RE.match(raw[1:])
        if not m:
            return ""
        major, minor, patch = _npm_parts(m)
        lower = f"{major}.{minor}.{patch}"
        if major > 0:
            upper = f"{major + 1}.0.0"
        elif minor > 0:
            upper = f"0.{minor + 1}.0"
        else:
            upper = f"0.0.{patch + 1}"
        return f">={lower},<{upper}"

    if raw.startswith("~"):
        m = _NPM_SEMVER_RE.match(raw[1:])
        if not m:
            return ""
        major, minor, patch = _npm_parts(m)
        return f">={major}.{minor}.{patch},<{major}.{minor + 1}.0"

    if raw.endswith(".x") or raw.endswith(".*"):
        base = raw[:-2]
        m = _NPM_SEMVER_RE.match(base)
        if m:
            major = int(m.group(1))
            if m.group(2) is not None:
                minor_val = int(m.group(2))
                return f">={major}.{minor_val}.0,<{major}.{minor_val + 1}.0"
            return f">={major}.0.0,<{major + 1}.0.0"
        return ""

    if raw[0] in (">", "<", "=", "!"):
        try:
            SpecifierSet(raw)
            return raw
        except InvalidSpecifier:
            parts = raw.split()
            if len(parts) > 1:
                joined = ",".join(parts)
                try:
                    SpecifierSet(joined)
                    return joined
                except InvalidSpecifier:
                    pass
            return ""

    m = _NPM_SEMVER_RE.match(raw)
    if m and m.end() == len(raw):
        return f">={raw}"

    return ""


def _normalize_ecosystem_version(raw: str, ecosystem: str) -> str:
    """Normalize an ecosystem-specific version string to PEP 440."""
    if not raw:
        return ""
    if ecosystem == "maven":
        if raw.upper().endswith("-SNAPSHOT"):
            return ""
        result = raw
        m = _MAVEN_SUFFIX_RE.match(result)
        if m:
            result = m.group(1)
        m = _MAVEN_PRE_RE.match(result)
        if m:
            base, qualifier, num = m.groups()
            tag = _PEP440_PRE_MAP.get(qualifier.lower(), "rc")
            result = f"{base}{tag}{num}"
        try:
            Version(result)
            return result
        except InvalidVersion:
            return ""
    if ecosystem == "go":
        m = _GO_V_RE.match(raw)
        if m:
            result = f"{m.group(1)}{m.group(2)}"
            try:
                Version(result)
                return result
            except InvalidVersion:
                return ""
    return raw


def _normalize_ecosystem_specifier(raw: str, ecosystem: str) -> str:
    """Normalize an ecosystem-specific specifier to PEP 440."""
    if not raw:
        return ""
    try:
        SpecifierSet(raw)
        return raw
    except InvalidSpecifier:
        pass
    if ecosystem == "npm":
        return _normalize_npm_specifier(raw)
    normalized = _normalize_ecosystem_version(raw, ecosystem)
    if not normalized:
        return ""
    return f">={normalized}"


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
        self._raw_versions: dict[tuple[str, str], str] = {}

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
            normalized = _normalize_ecosystem_version(v_str, self._ecosystem)
            target = normalized or v_str
            try:
                parsed.append((Version(target), target))
                if target != v_str:
                    self._raw_versions[(identifier, target)] = v_str
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

        raw_ver = self._raw_versions.get(
            (candidate.name, candidate.version), candidate.version
        )
        data = self._client.get_dependency_graph(self._ecosystem, candidate.name, raw_ver)
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
            spec = _normalize_ecosystem_specifier(req_str, self._ecosystem)
            deps.append(DepsDevRequirement(name=dep_name, specifier=spec))

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
            specifier=_normalize_ecosystem_specifier(
                dep.get("version_constraint", ""), ecosystem
            ),
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
