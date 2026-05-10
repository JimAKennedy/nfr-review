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
