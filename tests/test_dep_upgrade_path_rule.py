"""Tests for the dep-upgrade-path rule (R029 N-1 ceiling detection).

Validates that the rule fires RED when the resolvelib solver cannot find an
upgrade path that gets all dependencies within N-1 major version of latest,
and GREEN with upgrade recommendations when the path exists.
"""

from __future__ import annotations

from typing import Any

from nfr_review.deps_dev_client import DepsDevClient
from nfr_review.models import Evidence
from nfr_review.rules.dep_upgrade_path import DepUpgradePathRule

# ── helpers ──────────────────────────────────────────────────────────────


def _versions_response(versions: list[str]) -> dict:
    return {
        "versions": [
            {
                "versionKey": {"version": v},
                "publishedAt": "2024-01-01T00:00:00Z",
            }
            for v in versions
        ]
    }


def _dep_graph(direct_deps: list[tuple[str, str]] | None = None) -> dict:
    deps = direct_deps or []
    nodes: list[dict[str, Any]] = [
        {"versionKey": {"system": "PYPI", "name": "SELF", "version": "0.0.0"}}
    ]
    for dep_name, _ in deps:
        nodes.append({"versionKey": {"system": "PYPI", "name": dep_name, "version": "0.0.0"}})
    edges: list[dict[str, Any]] = []
    for i, (_, req_str) in enumerate(deps, start=1):
        edges.append({"fromNode": 0, "toNode": i, "requirement": req_str})
    return {"nodes": nodes, "edges": edges}


class MockDepsDevClient(DepsDevClient):
    """DepsDevClient subclass with configurable canned responses — no network."""

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


def _make_evidence(
    kind: str = "python-deps",
    collector_name: str = "python-deps",
    dependencies: list[dict[str, Any]] | None = None,
) -> Evidence:
    return Evidence(
        collector_name=collector_name,
        collector_version="1.0.0",
        locator="requirements.txt",
        kind=kind,
        payload={"dependencies": dependencies or []},
    )


def _make_dep(
    name: str,
    declared_version: str = ">=1.0",
    latest_version: str = "3.0.0",
    deps_dev_status: str = "ok",
) -> dict[str, Any]:
    return {
        "name": name,
        "declared_version": declared_version,
        "latest_version": latest_version,
        "deps_dev_status": deps_dev_status,
    }


def _rule_with_mock(mock: MockDepsDevClient) -> DepUpgradePathRule:
    return DepUpgradePathRule(client_factory=lambda: mock)


# ── GREEN path: all deps within N-1 ─────────────────────────────────────


class TestUpgradePathWithinN1:
    def test_single_ecosystem_all_within_n1_green(self) -> None:
        mock = MockDepsDevClient(
            versions={
                "alpha": _versions_response(["2.0.0", "3.0.0"]),
                "beta": _versions_response(["1.0.0", "2.0.0"]),
            },
            graphs={
                ("alpha", "3.0.0"): _dep_graph(),
                ("beta", "2.0.0"): _dep_graph(),
            },
        )
        evidence = [
            _make_evidence(
                dependencies=[
                    _make_dep("alpha", ">=2.0", latest_version="3.0.0"),
                    _make_dep("beta", ">=1.0", latest_version="2.0.0"),
                ]
            )
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.pattern_tag == "upgrade-path-ok"

    def test_green_finding_includes_optimal_set_in_summary(self) -> None:
        mock = MockDepsDevClient(
            versions={"solo": _versions_response(["3.0.0"])},
            graphs={("solo", "3.0.0"): _dep_graph()},
        )
        evidence = [_make_evidence(dependencies=[_make_dep("solo", ">=1.0", "3.0.0")])]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        f = result.findings[0]
        assert "solo==3.0.0" in f.summary

    def test_green_finding_severity_is_info(self) -> None:
        mock = MockDepsDevClient(
            versions={"pkg": _versions_response(["5.0.0"])},
            graphs={("pkg", "5.0.0"): _dep_graph()},
        )
        evidence = [_make_evidence(dependencies=[_make_dep("pkg", ">=1.0", "5.0.0")])]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert result.findings[0].severity == "info"


# ── RED path: N-1 breach (core R029) ────────────────────────────────────


class TestUpgradePathBeyondN1:
    def _make_stuck_scenario(self) -> tuple[MockDepsDevClient, list[Evidence]]:
        mock = MockDepsDevClient(
            versions={"stuck": _versions_response(["1.0.0", "1.5.0"])},
            graphs={("stuck", "1.5.0"): _dep_graph()},
        )
        evidence = [
            _make_evidence(
                dependencies=[_make_dep("stuck", ">=1.0,<2.0", latest_version="4.0.0")]
            )
        ]
        return mock, evidence

    def test_n1_breach_produces_red_finding(self) -> None:
        mock, evidence = self._make_stuck_scenario()
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_n1_breach_severity_is_high(self) -> None:
        mock, evidence = self._make_stuck_scenario()
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert result.findings[0].severity == "high"

    def test_n1_breach_lists_stuck_packages(self) -> None:
        mock, evidence = self._make_stuck_scenario()
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert "stuck" in result.findings[0].summary

    def test_n1_breach_pattern_tag(self) -> None:
        mock, evidence = self._make_stuck_scenario()
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert result.findings[0].pattern_tag == "upgrade-path-n1-breach"

    def test_n1_breach_shows_version_gap(self) -> None:
        mock, evidence = self._make_stuck_scenario()
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert "gap=3 majors" in result.findings[0].summary


# ── RED path: unsolvable constraints ─────────────────────────────────────


class TestUpgradePathUnsolvable:
    def _make_unsolvable_scenario(self) -> tuple[MockDepsDevClient, list[Evidence]]:
        mock = MockDepsDevClient(
            versions={
                "pkg-a": _versions_response(["1.0.0", "2.0.0"]),
                "pkg-b": None,
            },
            graphs={},
        )
        evidence = [
            _make_evidence(
                dependencies=[
                    _make_dep("pkg-a", ">=3.0", latest_version="2.0.0"),
                    _make_dep("pkg-b", ">=1.0", latest_version="1.0.0"),
                ]
            )
        ]
        return mock, evidence

    def test_unsolvable_produces_red_finding(self) -> None:
        mock, evidence = self._make_unsolvable_scenario()
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_unsolvable_severity_is_critical(self) -> None:
        mock, evidence = self._make_unsolvable_scenario()
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert result.findings[0].severity == "critical"

    def test_unsolvable_includes_blocking_constraints(self) -> None:
        mock, evidence = self._make_unsolvable_scenario()
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert "Blocking constraints:" in result.findings[0].summary

    def test_unsolvable_pattern_tag(self) -> None:
        mock, evidence = self._make_unsolvable_scenario()
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert result.findings[0].pattern_tag == "upgrade-path-unsolvable"


# ── Multi-ecosystem ──────────────────────────────────────────────────────


class TestUpgradePathMultiEcosystem:
    def test_multiple_ecosystems_resolved_independently(self) -> None:
        mock = MockDepsDevClient(
            versions={
                "py-pkg": _versions_response(["3.0.0"]),
                "node-pkg": _versions_response(["5.0.0"]),
            },
            graphs={
                ("py-pkg", "3.0.0"): _dep_graph(),
                ("node-pkg", "5.0.0"): _dep_graph(),
            },
        )
        evidence = [
            _make_evidence(
                kind="python-deps",
                collector_name="python-deps",
                dependencies=[_make_dep("py-pkg", ">=1.0", "3.0.0")],
            ),
            _make_evidence(
                kind="nodejs-deps",
                collector_name="nodejs-deps",
                dependencies=[_make_dep("node-pkg", ">=1.0", "5.0.0")],
            ),
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert not result.skipped
        assert len(result.findings) == 2
        collectors = {f.collector_name for f in result.findings}
        assert collectors == {"python-deps", "nodejs-deps"}

    def test_mixed_results_one_green_one_red(self) -> None:
        mock = MockDepsDevClient(
            versions={
                "healthy": _versions_response(["3.0.0"]),
                "stuck": _versions_response(["1.0.0"]),
            },
            graphs={
                ("healthy", "3.0.0"): _dep_graph(),
                ("stuck", "1.0.0"): _dep_graph(),
            },
        )
        evidence = [
            _make_evidence(
                kind="python-deps",
                collector_name="python-deps",
                dependencies=[_make_dep("healthy", ">=1.0", "3.0.0")],
            ),
            _make_evidence(
                kind="nodejs-deps",
                collector_name="nodejs-deps",
                dependencies=[_make_dep("stuck", ">=1.0,<2.0", "4.0.0")],
            ),
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert len(result.findings) == 2
        rags = {f.collector_name: f.rag for f in result.findings}
        assert rags["python-deps"] == "green"
        assert rags["nodejs-deps"] == "red"


# ── Edge cases ───────────────────────────────────────────────────────────


class TestUpgradePathEdgeCases:
    def test_no_dependency_evidence_skipped(self) -> None:
        evidence = [
            Evidence(
                collector_name="other-collector",
                collector_version="1.0.0",
                locator="foo",
                kind="other-kind",
                payload={},
            )
        ]
        rule = DepUpgradePathRule()
        result = rule.evaluate(evidence, context=None)

        assert result.skipped
        assert "no dependency evidence" in (result.skip_reason or "")

    def test_empty_evidence_list_skipped(self) -> None:
        rule = DepUpgradePathRule()
        result = rule.evaluate([], context=None)
        assert result.skipped

    def test_all_deps_filtered_out_skipped(self) -> None:
        mock = MockDepsDevClient()
        evidence = [
            _make_evidence(
                dependencies=[
                    _make_dep("bad", deps_dev_status="error"),
                    {
                        "name": "no-latest",
                        "declared_version": ">=1.0",
                        "deps_dev_status": "ok",
                    },
                ]
            )
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert result.skipped
        assert "no resolvable" in (result.skip_reason or "")

    def test_deps_with_missing_latest_version_excluded(self) -> None:
        mock = MockDepsDevClient(
            versions={"good": _versions_response(["2.0.0"])},
            graphs={("good", "2.0.0"): _dep_graph()},
        )
        evidence = [
            _make_evidence(
                dependencies=[
                    _make_dep("good", ">=1.0", "2.0.0"),
                    {
                        "name": "no-latest",
                        "declared_version": ">=1.0",
                        "deps_dev_status": "ok",
                    },
                ]
            )
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert not result.skipped
        assert len(result.findings) == 1
        assert "good" in result.findings[0].summary
        assert "no-latest" not in result.findings[0].summary

    def test_empty_dependency_list_no_findings(self) -> None:
        mock = MockDepsDevClient()
        evidence = [_make_evidence(dependencies=[])]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert result.skipped

    def test_exact_n1_boundary_is_green(self) -> None:
        """latest major = resolved major + 1 → gap is exactly 1 → GREEN."""
        mock = MockDepsDevClient(
            versions={"boundary": _versions_response(["2.0.0"])},
            graphs={("boundary", "2.0.0"): _dep_graph()},
        )
        evidence = [
            _make_evidence(
                dependencies=[_make_dep("boundary", ">=2.0", latest_version="3.0.0")]
            )
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert not result.skipped
        f = result.findings[0]
        assert f.rag == "green"
        assert f.pattern_tag == "upgrade-path-ok"

    def test_n2_boundary_is_red(self) -> None:
        """latest major = resolved major + 2 → gap is 2 → RED."""
        mock = MockDepsDevClient(
            versions={"behind": _versions_response(["2.0.0"])},
            graphs={("behind", "2.0.0"): _dep_graph()},
        )
        evidence = [
            _make_evidence(dependencies=[_make_dep("behind", ">=2.0", latest_version="4.0.0")])
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert not result.skipped
        f = result.findings[0]
        assert f.rag == "red"
        assert f.pattern_tag == "upgrade-path-n1-breach"

    def test_same_major_is_green(self) -> None:
        """Resolved and latest share the same major version → gap 0 → GREEN."""
        mock = MockDepsDevClient(
            versions={"current": _versions_response(["3.1.0"])},
            graphs={("current", "3.1.0"): _dep_graph()},
        )
        evidence = [
            _make_evidence(
                dependencies=[_make_dep("current", ">=3.0", latest_version="3.2.0")]
            )
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert result.findings[0].rag == "green"


# ── Finding shape validation ─────────────────────────────────────────────


class TestUpgradePathFindingShape:
    def test_all_10_finding_fields_present(self) -> None:
        mock = MockDepsDevClient(
            versions={"pkg": _versions_response(["2.0.0"])},
            graphs={("pkg", "2.0.0"): _dep_graph()},
        )
        evidence = [_make_evidence(dependencies=[_make_dep("pkg", ">=1.0", "2.0.0")])]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        f = result.findings[0]
        assert f.rule_id == "dep-upgrade-path"
        assert f.rag in {"red", "amber", "green", "skipped"}
        assert f.severity in {"critical", "high", "medium", "low", "info"}
        assert isinstance(f.summary, str) and len(f.summary) > 0
        assert isinstance(f.recommendation, str) and len(f.recommendation) > 0
        assert isinstance(f.evidence_locator, str) and len(f.evidence_locator) > 0
        assert isinstance(f.collector_name, str)
        assert isinstance(f.collector_version, str)
        assert isinstance(f.confidence, float) and 0.0 <= f.confidence <= 1.0
        assert isinstance(f.pattern_tag, str) and len(f.pattern_tag) > 0

    def test_collector_name_and_version_from_evidence(self) -> None:
        mock = MockDepsDevClient(
            versions={"x": _versions_response(["1.0.0"])},
            graphs={("x", "1.0.0"): _dep_graph()},
        )
        ev = Evidence(
            collector_name="nodejs-deps",
            collector_version="2.5.0",
            locator="package.json",
            kind="nodejs-deps",
            payload={"dependencies": [_make_dep("x", ">=1.0", "1.0.0")]},
        )
        result = _rule_with_mock(mock).evaluate([ev], context=None)

        f = result.findings[0]
        assert f.collector_name == "nodejs-deps"
        assert f.collector_version == "2.5.0"

    def test_evidence_locator_pattern(self) -> None:
        mock = MockDepsDevClient(
            versions={"z": _versions_response(["1.0.0"])},
            graphs={("z", "1.0.0"): _dep_graph()},
        )
        evidence = [
            _make_evidence(
                collector_name="go-deps",
                kind="go-deps",
                dependencies=[_make_dep("z", ">=1.0", "1.0.0")],
            )
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)

        assert result.findings[0].evidence_locator == "upgrade-path:go-deps"

    def test_unsolvable_finding_confidence(self) -> None:
        mock = MockDepsDevClient(
            versions={
                "a": _versions_response(["1.0.0", "2.0.0"]),
                "b": None,
            },
            graphs={},
        )
        evidence = [
            _make_evidence(
                dependencies=[
                    _make_dep("a", ">=3.0", "2.0.0"),
                    _make_dep("b", ">=1.0", "1.0.0"),
                ]
            )
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert result.findings[0].confidence == 0.9

    def test_n1_breach_finding_confidence(self) -> None:
        mock = MockDepsDevClient(
            versions={"old": _versions_response(["1.0.0"])},
            graphs={("old", "1.0.0"): _dep_graph()},
        )
        evidence = [
            _make_evidence(dependencies=[_make_dep("old", ">=1.0", latest_version="5.0.0")])
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert result.findings[0].confidence == 0.85

    def test_green_finding_confidence(self) -> None:
        mock = MockDepsDevClient(
            versions={"fresh": _versions_response(["3.0.0"])},
            graphs={("fresh", "3.0.0"): _dep_graph()},
        )
        evidence = [
            _make_evidence(dependencies=[_make_dep("fresh", ">=1.0", latest_version="3.0.0")])
        ]
        result = _rule_with_mock(mock).evaluate(evidence, context=None)
        assert result.findings[0].confidence == 0.85
