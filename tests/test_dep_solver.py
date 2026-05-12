"""Comprehensive tests for the resolvelib-based constraint solver.

Covers DepsDevProvider methods, resolve_dependencies() public API (solvable,
unsolvable, edge cases), ResolveResult model validation, and S02→S05 boundary
contract with PythonDepsCollector payload shapes.
"""

from __future__ import annotations

from typing import Any

import pytest

from nfr_review.dep_solver import (
    DepsDevCandidate,
    DepsDevProvider,
    DepsDevRequirement,
    ResolveResult,
    _normalize_ecosystem_specifier,
    _normalize_ecosystem_version,
    _normalize_npm_specifier,
    resolve_dependencies,
)
from nfr_review.deps_dev_client import DepsDevClient

# ── helpers ──────────────────────────────────────────────────────────────


def _mock_versions_response(versions: list[str]) -> dict:
    return {
        "versions": [
            {
                "versionKey": {"version": v},
                "publishedAt": "2024-01-01T00:00:00Z",
            }
            for v in versions
        ]
    }


def _mock_dep_graph_response(direct_deps: list[tuple[str, str]]) -> dict:
    nodes: list[dict[str, Any]] = [
        {"versionKey": {"system": "PYPI", "name": "SELF", "version": "0.0.0"}}
    ]
    for dep_name, _ in direct_deps:
        nodes.append({"versionKey": {"system": "PYPI", "name": dep_name, "version": "0.0.0"}})

    edges: list[dict[str, Any]] = []
    for i, (_, req_str) in enumerate(direct_deps, start=1):
        edges.append({"fromNode": 0, "toNode": i, "requirement": req_str})

    return {"nodes": nodes, "edges": edges}


class MockDepsDevClient(DepsDevClient):
    """DepsDevClient subclass with configurable canned responses."""

    def __init__(
        self,
        versions: dict[str, dict | None] | None = None,
        graphs: dict[tuple[str, str], dict | None] | None = None,
    ) -> None:
        super().__init__(timeout=1)
        self._versions: dict[str, dict | None] = versions or {}
        self._graphs: dict[tuple[str, str], dict | None] = graphs or {}

    def get_package_versions(self, ecosystem: str, package_name: str) -> dict | None:
        return self._versions.get(package_name)

    def get_dependency_graph(
        self, ecosystem: str, package_name: str, version: str
    ) -> dict | None:
        return self._graphs.get((package_name, version))


# ── DepsDevProvider.identify ─────────────────────────────────────────────


class TestProviderIdentify:
    def test_identify_returns_name_for_requirement(self) -> None:
        req = DepsDevRequirement("pkg-a", ">=1.0")
        client = MockDepsDevClient()
        provider = DepsDevProvider(client, "pypi")
        assert provider.identify(req) == "pkg-a"

    def test_identify_returns_name_for_candidate(self) -> None:
        cand = DepsDevCandidate("pkg-a", "1.0.0")
        client = MockDepsDevClient()
        provider = DepsDevProvider(client, "pypi")
        assert provider.identify(cand) == "pkg-a"


# ── DepsDevProvider.find_matches ─────────────────────────────────────────


class TestProviderFindMatches:
    def _make_provider(self, versions: dict[str, dict | None]) -> DepsDevProvider:
        return DepsDevProvider(MockDepsDevClient(versions=versions), "pypi")

    def test_find_matches_returns_all_versions_when_unconstrained(self) -> None:
        provider = self._make_provider(
            {"mypkg": _mock_versions_response(["1.0.0", "1.1.0", "2.0.0"])}
        )
        req = DepsDevRequirement("mypkg", "")
        matches = provider.find_matches(
            identifier="mypkg",
            requirements={"mypkg": [req]},
            incompatibilities={"mypkg": []},
        )
        assert len(matches) == 3
        assert all(isinstance(m, DepsDevCandidate) for m in matches)

    def test_find_matches_filters_by_specifier(self) -> None:
        provider = self._make_provider(
            {"mypkg": _mock_versions_response(["0.9.0", "1.0.0", "1.5.0", "2.0.0"])}
        )
        req = DepsDevRequirement("mypkg", ">=1.0,<2.0")
        matches = provider.find_matches(
            identifier="mypkg",
            requirements={"mypkg": [req]},
            incompatibilities={"mypkg": []},
        )
        versions = [m.version for m in matches]
        assert "0.9.0" not in versions
        assert "2.0.0" not in versions
        assert "1.0.0" in versions
        assert "1.5.0" in versions

    def test_find_matches_orders_latest_first(self) -> None:
        provider = self._make_provider(
            {"mypkg": _mock_versions_response(["1.0.0", "2.0.0", "1.5.0"])}
        )
        req = DepsDevRequirement("mypkg", "")
        matches = provider.find_matches(
            identifier="mypkg",
            requirements={"mypkg": [req]},
            incompatibilities={"mypkg": []},
        )
        versions = [m.version for m in matches]
        assert versions == ["2.0.0", "1.5.0", "1.0.0"]

    def test_find_matches_returns_empty_when_deps_dev_unavailable(self) -> None:
        provider = self._make_provider({"mypkg": None})
        req = DepsDevRequirement("mypkg", "")
        matches = provider.find_matches(
            identifier="mypkg",
            requirements={"mypkg": [req]},
            incompatibilities={"mypkg": []},
        )
        assert matches == []


# ── DepsDevProvider.is_satisfied_by ──────────────────────────────────────


class TestProviderIsSatisfiedBy:
    def _provider(self) -> DepsDevProvider:
        return DepsDevProvider(MockDepsDevClient(), "pypi")

    def test_is_satisfied_by_matching_version(self) -> None:
        provider = self._provider()
        req = DepsDevRequirement("pkg", ">=1.0,<2.0")
        cand = DepsDevCandidate("pkg", "1.5.0")
        assert provider.is_satisfied_by(req, cand) is True

    def test_is_satisfied_by_non_matching_version(self) -> None:
        provider = self._provider()
        req = DepsDevRequirement("pkg", ">=2.0")
        cand = DepsDevCandidate("pkg", "1.5.0")
        assert provider.is_satisfied_by(req, cand) is False

    def test_is_satisfied_by_empty_specifier(self) -> None:
        provider = self._provider()
        req = DepsDevRequirement("pkg", "")
        cand = DepsDevCandidate("pkg", "99.0.0")
        assert provider.is_satisfied_by(req, cand) is True


# ── DepsDevProvider.get_dependencies ─────────────────────────────────────


class TestProviderGetDependencies:
    def test_get_dependencies_extracts_direct_deps(self) -> None:
        graph = _mock_dep_graph_response([("dep-a", ">=1.0"), ("dep-b", "<3.0")])
        client = MockDepsDevClient(graphs={("pkg", "1.0.0"): graph})
        provider = DepsDevProvider(client, "pypi")
        cand = DepsDevCandidate("pkg", "1.0.0")
        deps = provider.get_dependencies(cand)
        assert len(deps) == 2
        names = {d.name for d in deps}
        assert names == {"dep-a", "dep-b"}
        specs = {d.name: d.specifier for d in deps}
        assert specs["dep-a"] == ">=1.0"
        assert specs["dep-b"] == "<3.0"

    def test_get_dependencies_handles_none_graph(self) -> None:
        client = MockDepsDevClient(graphs={("pkg", "1.0.0"): None})
        provider = DepsDevProvider(client, "pypi")
        cand = DepsDevCandidate("pkg", "1.0.0")
        deps = provider.get_dependencies(cand)
        assert deps == []

    def test_get_dependencies_handles_missing_edges(self) -> None:
        client = MockDepsDevClient(
            graphs={("pkg", "1.0.0"): {"nodes": [{"versionKey": {"name": "SELF"}}]}}
        )
        provider = DepsDevProvider(client, "pypi")
        cand = DepsDevCandidate("pkg", "1.0.0")
        deps = provider.get_dependencies(cand)
        assert deps == []


# ── resolve_dependencies() ───────────────────────────────────────────────


class TestResolveDependencies:
    def test_resolve_solvable_simple(self) -> None:
        client = MockDepsDevClient(
            versions={
                "alpha": _mock_versions_response(["1.0.0", "1.1.0", "2.0.0"]),
                "beta": _mock_versions_response(["0.5.0", "1.0.0"]),
            },
            graphs={
                ("alpha", "2.0.0"): _mock_dep_graph_response([]),
                ("beta", "1.0.0"): _mock_dep_graph_response([]),
            },
        )
        deps = [
            {"name": "alpha", "version_constraint": ">=1.0"},
            {"name": "beta", "version_constraint": ">=0.5"},
        ]
        result = resolve_dependencies(deps, client, "pypi")
        assert result.unsolvable is False
        assert result.optimal_set["alpha"] == "2.0.0"
        assert result.optimal_set["beta"] == "1.0.0"
        assert result.blocking_constraints == []

    def test_resolve_solvable_with_transitive_constraints(self) -> None:
        client = MockDepsDevClient(
            versions={
                "pkg-a": _mock_versions_response(["1.0.0"]),
                "pkg-b": _mock_versions_response(["1.0.0"]),
                "shared": _mock_versions_response(["1.0.0", "1.5.0", "2.0.0"]),
            },
            graphs={
                ("pkg-a", "1.0.0"): _mock_dep_graph_response([("shared", ">=1.0")]),
                ("pkg-b", "1.0.0"): _mock_dep_graph_response([("shared", ">=1.0,<2.0")]),
                ("shared", "1.5.0"): _mock_dep_graph_response([]),
                ("shared", "1.0.0"): _mock_dep_graph_response([]),
            },
        )
        deps = [
            {"name": "pkg-a", "version_constraint": ">=1.0"},
            {"name": "pkg-b", "version_constraint": ">=1.0"},
        ]
        result = resolve_dependencies(deps, client, "pypi")
        assert result.unsolvable is False
        assert "shared" in result.optimal_set
        from packaging.version import Version

        resolved_shared = Version(result.optimal_set["shared"])
        assert resolved_shared >= Version("1.0.0")
        assert resolved_shared < Version("2.0.0")

    def test_resolve_unsolvable_conflicting_constraints(self) -> None:
        client = MockDepsDevClient(
            versions={
                "pkg-a": _mock_versions_response(["1.0.0"]),
                "pkg-b": _mock_versions_response(["1.0.0"]),
                "conflict": _mock_versions_response(["1.0.0", "1.5.0", "2.0.0"]),
            },
            graphs={
                ("pkg-a", "1.0.0"): _mock_dep_graph_response([("conflict", ">=2.0")]),
                ("pkg-b", "1.0.0"): _mock_dep_graph_response([("conflict", "<1.5")]),
                ("conflict", "2.0.0"): _mock_dep_graph_response([]),
                ("conflict", "1.0.0"): _mock_dep_graph_response([]),
            },
        )
        deps = [
            {"name": "pkg-a", "version_constraint": ">=1.0"},
            {"name": "pkg-b", "version_constraint": ">=1.0"},
        ]
        result = resolve_dependencies(deps, client, "pypi")
        assert result.unsolvable is True
        assert len(result.blocking_constraints) > 0
        assert all(isinstance(c, str) and len(c) > 0 for c in result.blocking_constraints)

    def test_resolve_empty_dependencies(self) -> None:
        client = MockDepsDevClient()
        result = resolve_dependencies([], client, "pypi")
        assert result.optimal_set == {}
        assert result.unsolvable is False
        assert result.blocking_constraints == []

    def test_resolve_single_dependency(self) -> None:
        client = MockDepsDevClient(
            versions={"solo": _mock_versions_response(["1.0.0", "2.0.0", "3.0.0"])},
            graphs={("solo", "3.0.0"): _mock_dep_graph_response([])},
        )
        result = resolve_dependencies(
            [{"name": "solo", "version_constraint": ">=1.0"}], client, "pypi"
        )
        assert result.unsolvable is False
        assert result.optimal_set["solo"] == "3.0.0"

    def test_resolve_unconstrained_deps(self) -> None:
        client = MockDepsDevClient(
            versions={"free": _mock_versions_response(["1.0.0", "5.0.0"])},
            graphs={("free", "5.0.0"): _mock_dep_graph_response([])},
        )
        result = resolve_dependencies(
            [{"name": "free", "version_constraint": ""}], client, "pypi"
        )
        assert result.unsolvable is False
        assert result.optimal_set["free"] == "5.0.0"

    def test_resolve_deps_dev_unavailable_for_package(self) -> None:
        client = MockDepsDevClient(
            versions={
                "available": _mock_versions_response(["1.0.0"]),
                "gone": None,
            },
            graphs={("available", "1.0.0"): _mock_dep_graph_response([])},
        )
        result = resolve_dependencies(
            [
                {"name": "available", "version_constraint": ">=1.0"},
                {"name": "gone", "version_constraint": ">=1.0"},
            ],
            client,
            "pypi",
        )
        assert result.unsolvable is True


# ── ResolveResult model ──────────────────────────────────────────────────


class TestResolveResult:
    def test_resolve_result_forbids_extra_fields(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResolveResult(
                optimal_set={},
                unsolvable=False,
                blocking_constraints=[],
                extra_field="bad",  # type: ignore[call-arg]
            )

    def test_resolve_result_field_types(self) -> None:
        r = ResolveResult(
            optimal_set={"a": "1.0"},
            unsolvable=True,
            blocking_constraints=["x requires y"],
        )
        assert isinstance(r.optimal_set, dict)
        assert isinstance(r.unsolvable, bool)
        assert isinstance(r.blocking_constraints, list)
        assert all(isinstance(c, str) for c in r.blocking_constraints)


# ── S02→S05 boundary contract ────────────────────────────────────────────


class TestBoundaryContract:
    def test_boundary_contract_with_collector_payload_shape(self) -> None:
        """Verify resolve_dependencies handles dicts shaped like
        PythonDepsCollector's dependency payload (extra keys ignored)."""
        client = MockDepsDevClient(
            versions={
                "requests": _mock_versions_response(["2.31.0", "2.32.0"]),
            },
            graphs={("requests", "2.32.0"): _mock_dep_graph_response([])},
        )
        collector_shaped_dep = {
            "name": "requests",
            "declared_version": ">=2.31.0",
            "version_constraint": ">=2.31.0",
            "source_file": "requirements.txt",
            "latest_version": "2.32.0",
            "latest_release_date": "2024-01-01T00:00:00Z",
            "deps_dev_status": "ok",
        }
        result = resolve_dependencies([collector_shaped_dep], client, "pypi")
        assert result.unsolvable is False
        assert result.optimal_set["requests"] == "2.32.0"


# ── negative / edge-case tests ───────────────────────────────────────────


class TestNegativeAndEdgeCases:
    def test_dependency_with_empty_name(self) -> None:
        client = MockDepsDevClient(versions={"": None})
        result = resolve_dependencies(
            [{"name": "", "version_constraint": ">=1.0"}], client, "pypi"
        )
        assert result.unsolvable is True

    def test_all_versions_filtered_by_specifier(self) -> None:
        client = MockDepsDevClient(
            versions={"strict": _mock_versions_response(["1.0.0", "2.0.0"])}
        )
        result = resolve_dependencies(
            [{"name": "strict", "version_constraint": ">=99.0"}], client, "pypi"
        )
        assert result.unsolvable is True

    def test_missing_version_constraint_key(self) -> None:
        """Dependency dict without version_constraint key defaults to unconstrained."""
        client = MockDepsDevClient(
            versions={"bare": _mock_versions_response(["1.0.0"])},
            graphs={("bare", "1.0.0"): _mock_dep_graph_response([])},
        )
        result = resolve_dependencies([{"name": "bare"}], client, "pypi")
        assert result.unsolvable is False
        assert result.optimal_set["bare"] == "1.0.0"

    def test_deps_dev_response_missing_versions_key(self) -> None:
        """get_package_versions returns a dict without 'versions' key."""
        client = MockDepsDevClient(versions={"broken": {"packageKey": {}}})
        result = resolve_dependencies(
            [{"name": "broken", "version_constraint": ">=1.0"}], client, "pypi"
        )
        assert result.unsolvable is True


# ── Ecosystem version normalization ─────────────────────────────────────


class TestNormalizeEcosystemVersion:
    def test_maven_rc(self) -> None:
        assert _normalize_ecosystem_version("4.1.0-RC1", "maven") == "4.1.0rc1"

    def test_maven_alpha(self) -> None:
        assert _normalize_ecosystem_version("2.0.0-alpha2", "maven") == "2.0.0a2"

    def test_maven_beta(self) -> None:
        assert _normalize_ecosystem_version("3.0.0-beta1", "maven") == "3.0.0b1"

    def test_maven_milestone(self) -> None:
        assert _normalize_ecosystem_version("5.0.0-M3", "maven") == "5.0.0rc3"

    def test_maven_snapshot_skipped(self) -> None:
        assert _normalize_ecosystem_version("4.1.0-SNAPSHOT", "maven") == ""

    def test_maven_release_suffix(self) -> None:
        assert _normalize_ecosystem_version("3.0.0.RELEASE", "maven") == "3.0.0"

    def test_maven_final_suffix(self) -> None:
        assert _normalize_ecosystem_version("3.0.0.Final", "maven") == "3.0.0"

    def test_maven_bare_version(self) -> None:
        assert _normalize_ecosystem_version("2.11.0", "maven") == "2.11.0"

    def test_go_v_prefix(self) -> None:
        assert _normalize_ecosystem_version("v1.5.2", "go") == "1.5.2"

    def test_go_pseudo_version_skipped(self) -> None:
        assert _normalize_ecosystem_version("v0.0.0-20220722155255-886fb9371eb4", "go") == ""

    def test_pypi_passthrough(self) -> None:
        assert _normalize_ecosystem_version("2.31.0", "pypi") == "2.31.0"

    def test_empty_string(self) -> None:
        assert _normalize_ecosystem_version("", "maven") == ""


class TestNormalizeEcosystemSpecifier:
    def test_valid_pep440_passthrough(self) -> None:
        assert _normalize_ecosystem_specifier(">=2.0", "maven") == ">=2.0"

    def test_maven_bare_rc(self) -> None:
        assert _normalize_ecosystem_specifier("4.1.0-RC1", "maven") == ">=4.1.0rc1"

    def test_go_bare_v_prefix(self) -> None:
        assert _normalize_ecosystem_specifier("v1.5.1", "go") == ">=1.5.1"

    def test_empty_returns_empty(self) -> None:
        assert _normalize_ecosystem_specifier("", "maven") == ""

    def test_snapshot_returns_empty(self) -> None:
        assert _normalize_ecosystem_specifier("4.1.0-SNAPSHOT", "maven") == ""


# ── npm semver specifier normalization ──────────────────────────────────


class TestNormalizeNpmSpecifier:
    def test_caret_major(self) -> None:
        assert _normalize_npm_specifier("^17.0.2") == ">=17.0.2,<18.0.0"

    def test_caret_minor(self) -> None:
        assert _normalize_npm_specifier("^0.2.3") == ">=0.2.3,<0.3.0"

    def test_caret_patch(self) -> None:
        assert _normalize_npm_specifier("^0.0.3") == ">=0.0.3,<0.0.4"

    def test_caret_major_only(self) -> None:
        assert _normalize_npm_specifier("^3") == ">=3.0.0,<4.0.0"

    def test_caret_major_minor(self) -> None:
        assert _normalize_npm_specifier("^1.2") == ">=1.2.0,<2.0.0"

    def test_tilde(self) -> None:
        assert _normalize_npm_specifier("~1.2.3") == ">=1.2.3,<1.3.0"

    def test_tilde_major_minor(self) -> None:
        assert _normalize_npm_specifier("~0.2") == ">=0.2.0,<0.3.0"

    def test_range_full(self) -> None:
        assert _normalize_npm_specifier("1.0.0 - 2.0.0") == ">=1.0.0,<=2.0.0"

    def test_range_partial_right(self) -> None:
        assert _normalize_npm_specifier("1.0.0 - 2") == ">=1.0.0,<3.0.0"

    def test_wildcard_major(self) -> None:
        assert _normalize_npm_specifier("1.x") == ">=1.0.0,<2.0.0"

    def test_wildcard_minor(self) -> None:
        assert _normalize_npm_specifier("1.2.*") == ">=1.2.0,<1.3.0"

    def test_union_returns_empty(self) -> None:
        assert _normalize_npm_specifier("^1.0.0 || ^2.0.0") == ""

    def test_bare_version(self) -> None:
        assert _normalize_npm_specifier("17.0.2") == ">=17.0.2"

    def test_empty(self) -> None:
        assert _normalize_npm_specifier("") == ""

    def test_space_separated_comparators(self) -> None:
        result = _normalize_npm_specifier(">=1.0.0 <2.0.0")
        assert result == ">=1.0.0,<2.0.0"

    def test_gte_passthrough(self) -> None:
        assert _normalize_npm_specifier(">=1.0.0") == ">=1.0.0"


class TestNpmEcosystemSpecifier:
    def test_caret_via_ecosystem(self) -> None:
        assert _normalize_ecosystem_specifier("^17.0.2", "npm") == ">=17.0.2,<18.0.0"

    def test_tilde_via_ecosystem(self) -> None:
        assert _normalize_ecosystem_specifier("~1.2.3", "npm") == ">=1.2.3,<1.3.0"

    def test_valid_pep440_passthrough(self) -> None:
        assert _normalize_ecosystem_specifier(">=1.0.0", "npm") == ">=1.0.0"

    def test_union_returns_empty(self) -> None:
        assert _normalize_ecosystem_specifier("^1.0.0 || ^2.0.0", "npm") == ""


# ── npm solver integration ─────────────────────────────────────────────


class TestNpmSolverIntegration:
    def test_npm_caret_constraints_resolve(self) -> None:
        """Reproduce the react ^17.0.2 failure from awesome-compose."""
        client = MockDepsDevClient(
            versions={
                "react": _mock_versions_response(
                    ["16.13.1", "16.14.0", "17.0.0", "17.0.1", "17.0.2", "18.0.0", "19.2.6"]
                ),
            },
            graphs={
                ("react", "17.0.2"): _mock_dep_graph_response([]),
            },
        )
        result = resolve_dependencies(
            [{"name": "react", "version_constraint": "^17.0.2"}],
            client,
            "npm",
        )
        assert result.unsolvable is False
        assert result.optimal_set["react"] == "17.0.2"

    def test_npm_tilde_constraints_resolve(self) -> None:
        client = MockDepsDevClient(
            versions={
                "lodash": _mock_versions_response(["4.17.19", "4.17.20", "4.17.21", "4.18.0"]),
            },
            graphs={
                ("lodash", "4.17.21"): _mock_dep_graph_response([]),
            },
        )
        result = resolve_dependencies(
            [{"name": "lodash", "version_constraint": "~4.17.19"}],
            client,
            "npm",
        )
        assert result.unsolvable is False
        from packaging.version import Version

        resolved = Version(result.optimal_set["lodash"])
        assert resolved >= Version("4.17.19")
        assert resolved < Version("4.18.0")

    def test_npm_multiple_caret_constraints(self) -> None:
        """Multiple packages with caret ranges — mirrors the real error."""
        client = MockDepsDevClient(
            versions={
                "react": _mock_versions_response(
                    ["16.13.1", "17.0.1", "17.0.2", "18.0.0", "19.2.6"]
                ),
                "react-dom": _mock_versions_response(
                    ["16.13.1", "17.0.1", "17.0.2", "18.0.0", "19.2.6"]
                ),
            },
            graphs={
                ("react", "17.0.2"): _mock_dep_graph_response([]),
                ("react-dom", "17.0.2"): _mock_dep_graph_response([("react", "^17.0.2")]),
            },
        )
        result = resolve_dependencies(
            [
                {"name": "react", "version_constraint": "^17.0.2"},
                {"name": "react-dom", "version_constraint": "^17.0.1"},
            ],
            client,
            "npm",
        )
        assert result.unsolvable is False
        assert result.optimal_set["react"] == "17.0.2"
        assert result.optimal_set["react-dom"] == "17.0.2"

    def test_npm_transitive_caret_requirement(self) -> None:
        """Transitive deps from deps.dev with npm caret specifiers should resolve."""
        graph_with_caret = _mock_dep_graph_response([("lodash", "^4.17.0")])
        client = MockDepsDevClient(
            versions={
                "express": _mock_versions_response(["4.18.0", "4.19.0"]),
                "lodash": _mock_versions_response(["4.17.20", "4.17.21", "5.0.0"]),
            },
            graphs={
                ("express", "4.19.0"): graph_with_caret,
                ("lodash", "4.17.21"): _mock_dep_graph_response([]),
            },
        )
        result = resolve_dependencies(
            [{"name": "express", "version_constraint": "^4.18.0"}],
            client,
            "npm",
        )
        assert result.unsolvable is False
        assert result.optimal_set["lodash"] == "4.17.21"

    def test_npm_union_treated_as_unconstrained(self) -> None:
        """Union specifiers (||) can't map to PEP 440 — treated as unconstrained."""
        client = MockDepsDevClient(
            versions={
                "typescript": _mock_versions_response(["4.9.0", "5.0.0", "5.1.0"]),
            },
            graphs={
                ("typescript", "5.1.0"): _mock_dep_graph_response([]),
            },
        )
        result = resolve_dependencies(
            [{"name": "typescript", "version_constraint": "^4.0.0 || ^5.0.0"}],
            client,
            "npm",
        )
        assert result.unsolvable is False
        assert result.optimal_set["typescript"] == "5.1.0"


# ── Maven version normalization in solver integration ───────────────────


class TestMavenSolverIntegration:
    def test_maven_rc_versions_resolved(self) -> None:
        """Maven RC versions from deps.dev should be normalized and resolvable."""
        client = MockDepsDevClient(
            versions={
                "org.example:lib": _mock_versions_response(["4.0.0", "4.1.0-RC1", "4.1.0"]),
            },
            graphs={
                ("org.example:lib", "4.1.0-RC1"): _mock_dep_graph_response([]),
                ("org.example:lib", "4.1.0"): _mock_dep_graph_response([]),
            },
        )
        result = resolve_dependencies(
            [{"name": "org.example:lib", "version_constraint": ">=4.1.0rc1"}],
            client,
            "maven",
        )
        assert result.unsolvable is False
        assert result.optimal_set["org.example:lib"] == "4.1.0"

    def test_maven_transitive_rc_requirement(self) -> None:
        """Transitive deps from deps.dev with Maven RC specifiers should resolve."""
        graph_with_rc_dep = _mock_dep_graph_response([("org.example:child", "4.1.0-RC1")])
        client = MockDepsDevClient(
            versions={
                "org.example:parent": _mock_versions_response(["1.0.0"]),
                "org.example:child": _mock_versions_response(["4.0.0", "4.1.0-RC1", "4.1.0"]),
            },
            graphs={
                ("org.example:parent", "1.0.0"): graph_with_rc_dep,
                ("org.example:child", "4.1.0-RC1"): _mock_dep_graph_response([]),
                ("org.example:child", "4.1.0"): _mock_dep_graph_response([]),
            },
        )
        result = resolve_dependencies(
            [{"name": "org.example:parent", "version_constraint": ">=1.0"}],
            client,
            "maven",
        )
        assert result.unsolvable is False
        assert "org.example:child" in result.optimal_set

    def test_go_v_prefix_versions_resolved(self) -> None:
        """Go v-prefixed versions from deps.dev should be normalized and resolvable."""
        client = MockDepsDevClient(
            versions={
                "github.com/example/lib": _mock_versions_response(
                    ["v1.0.0", "v1.5.0", "v2.0.0"]
                ),
            },
            graphs={
                ("github.com/example/lib", "v2.0.0"): _mock_dep_graph_response([]),
            },
        )
        result = resolve_dependencies(
            [{"name": "github.com/example/lib", "version_constraint": ">=1.0.0"}],
            client,
            "go",
        )
        assert result.unsolvable is False
        assert result.optimal_set["github.com/example/lib"] == "2.0.0"

    def test_go_transitive_v_prefix_requirement(self) -> None:
        """Transitive Go deps with v-prefix specifiers should resolve."""
        graph_with_go_dep = _mock_dep_graph_response([("github.com/example/child", "v1.5.0")])
        client = MockDepsDevClient(
            versions={
                "github.com/example/parent": _mock_versions_response(["v1.0.0"]),
                "github.com/example/child": _mock_versions_response(
                    ["v1.0.0", "v1.5.0", "v2.0.0"]
                ),
            },
            graphs={
                ("github.com/example/parent", "v1.0.0"): graph_with_go_dep,
                ("github.com/example/child", "v2.0.0"): _mock_dep_graph_response([]),
                ("github.com/example/child", "v1.5.0"): _mock_dep_graph_response([]),
            },
        )
        result = resolve_dependencies(
            [{"name": "github.com/example/parent", "version_constraint": ">=1.0.0"}],
            client,
            "go",
        )
        assert result.unsolvable is False
        assert "github.com/example/child" in result.optimal_set
