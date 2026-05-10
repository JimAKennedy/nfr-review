"""Multi-ecosystem dependency collector integration tests.

Proves all four new collectors (Node.js, Go, Java, C#) produce Evidence that
flows through Engine.run(). Uses the _EvidenceSpyRule pattern from
test_python_deps_integration.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from nfr_review.collectors.csharp_deps import CsharpDepsCollector
from nfr_review.collectors.go_deps import GoDepsCollector
from nfr_review.collectors.java_deps import JavaDepsCollector
from nfr_review.collectors.nodejs_deps import NodejsDepsCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.models import Evidence, RuleResult
from nfr_review.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"
MULTI_ECO_REPO = FIXTURES / "multi-ecosystem-deps-repo"
NODEJS_SAMPLE = FIXTURES / "nodejs-deps-sample-repo"
GO_SAMPLE = FIXTURES / "go-deps-sample-repo"
JAVA_SAMPLE = FIXTURES / "java-deps-sample-repo"
CSHARP_SAMPLE = FIXTURES / "csharp-deps-sample-repo"

BOUNDARY_FIELDS = {
    "name",
    "declared_version",
    "latest_version",
    "latest_release_date",
    "version_constraint",
    "deps_dev_status",
}


def _fake_package_versions(ecosystem: str, package_name: str) -> dict | None:
    return {
        "versions": [
            {
                "versionKey": {"version": "99.0.0"},
                "publishedAt": "2026-01-15T00:00:00Z",
            }
        ]
    }


class _EvidenceSpyRule:
    """Spy rule that captures evidence passed through the engine pipeline."""

    id = "test-multi-eco-spy"
    band = 1
    required_collectors: list[str] = []
    required_tech: list[str] = []

    def __init__(self, required_collectors: list[str] | None = None) -> None:
        self.captured: list[Evidence] = []
        if required_collectors is not None:
            self.required_collectors = required_collectors

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        self.captured.extend(evidence)
        return RuleResult(rule_id=self.id)


def _make_registries(
    collectors: list[Any],
    spy: _EvidenceSpyRule,
) -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    cregistry.register("repo-structure", RepoStructureCollector())
    for c in collectors:
        cregistry.register(c.name, c)
    rregistry.register(spy.id, spy)
    return cregistry, rregistry


def _run_engine(
    target: Path,
    collectors: list[Any],
    spy: _EvidenceSpyRule,
    *,
    side_effect: Any = _fake_package_versions,
) -> RunResult:
    cregistry, rregistry = _make_registries(collectors, spy)
    engine = Engine(collectors=cregistry, rules=rregistry)
    cfg = Config()
    with patch(
        "nfr_review.deps_dev_client.DepsDevClient.get_package_versions",
        side_effect=side_effect,
    ):
        return engine.run(target=target, config=cfg)


def _evidence_by_kind(spy: _EvidenceSpyRule, kind: str) -> Evidence:
    matches = [e for e in spy.captured if e.kind == kind]
    assert len(matches) == 1, f"Expected 1 {kind} evidence, got {len(matches)}"
    return matches[0]


class TestNodejsDepsIntegration:
    """Node.js collector produces evidence through Engine.run()."""

    @pytest.fixture()
    def spy(self) -> _EvidenceSpyRule:
        return _EvidenceSpyRule(required_collectors=["nodejs-deps"])

    @pytest.fixture()
    def result(self, spy: _EvidenceSpyRule) -> RunResult:
        return _run_engine(
            NODEJS_SAMPLE,
            [NodejsDepsCollector()],
            spy,
        )

    def test_evidence_kind(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "nodejs-deps")
        assert evidence.collector_name == "nodejs-deps"

    def test_boundary_contract(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "nodejs-deps")
        deps = evidence.payload["dependencies"]
        assert len(deps) >= 2
        for dep in deps:
            missing = BOUNDARY_FIELDS - set(dep.keys())
            assert not missing, f"Missing fields in {dep.get('name')}: {missing}"

    def test_manifest_files_found(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "nodejs-deps")
        assert "package.json" in evidence.payload["manifest_files_found"]

    def test_enrichment_errors_list(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "nodejs-deps")
        assert isinstance(evidence.payload["enrichment_errors"], list)


class TestGoDepsIntegration:
    """Go collector produces evidence through Engine.run()."""

    @pytest.fixture()
    def spy(self) -> _EvidenceSpyRule:
        return _EvidenceSpyRule(required_collectors=["go-deps"])

    @pytest.fixture()
    def result(self, spy: _EvidenceSpyRule) -> RunResult:
        return _run_engine(
            GO_SAMPLE,
            [GoDepsCollector()],
            spy,
        )

    def test_evidence_kind(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "go-deps")
        assert evidence.collector_name == "go-deps"

    def test_boundary_contract(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "go-deps")
        deps = evidence.payload["dependencies"]
        assert len(deps) >= 2
        for dep in deps:
            missing = BOUNDARY_FIELDS - set(dep.keys())
            assert not missing, f"Missing fields in {dep.get('name')}: {missing}"

    def test_manifest_files_found(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "go-deps")
        assert "go.mod" in evidence.payload["manifest_files_found"]

    def test_enrichment_errors_list(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "go-deps")
        assert isinstance(evidence.payload["enrichment_errors"], list)


class TestJavaDepsIntegration:
    """Java collector produces evidence through Engine.run()."""

    @pytest.fixture()
    def spy(self) -> _EvidenceSpyRule:
        return _EvidenceSpyRule(required_collectors=["java-deps"])

    @pytest.fixture()
    def result(self, spy: _EvidenceSpyRule) -> RunResult:
        return _run_engine(
            JAVA_SAMPLE,
            [JavaDepsCollector()],
            spy,
        )

    def test_evidence_kind(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "java-deps")
        assert evidence.collector_name == "java-deps"

    def test_boundary_contract(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "java-deps")
        deps = evidence.payload["dependencies"]
        assert len(deps) >= 2
        for dep in deps:
            missing = BOUNDARY_FIELDS - set(dep.keys())
            assert not missing, f"Missing fields in {dep.get('name')}: {missing}"

    def test_manifest_files_found(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "java-deps")
        manifests = evidence.payload["manifest_files_found"]
        assert any("pom.xml" in m for m in manifests)

    def test_enrichment_errors_list(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "java-deps")
        assert isinstance(evidence.payload["enrichment_errors"], list)


class TestCsharpDepsIntegration:
    """C# collector produces evidence through Engine.run()."""

    @pytest.fixture()
    def spy(self) -> _EvidenceSpyRule:
        return _EvidenceSpyRule(required_collectors=["csharp-deps"])

    @pytest.fixture()
    def result(self, spy: _EvidenceSpyRule) -> RunResult:
        return _run_engine(
            CSHARP_SAMPLE,
            [CsharpDepsCollector()],
            spy,
        )

    def test_evidence_kind(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "csharp-deps")
        assert evidence.collector_name == "csharp-deps"

    def test_boundary_contract(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "csharp-deps")
        deps = evidence.payload["dependencies"]
        assert len(deps) >= 2
        for dep in deps:
            missing = BOUNDARY_FIELDS - set(dep.keys())
            assert not missing, f"Missing fields in {dep.get('name')}: {missing}"

    def test_manifest_files_found(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "csharp-deps")
        manifests = evidence.payload["manifest_files_found"]
        assert any(".csproj" in m for m in manifests)

    def test_enrichment_errors_list(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _evidence_by_kind(spy, "csharp-deps")
        assert isinstance(evidence.payload["enrichment_errors"], list)


class TestMultiEcosystemCombined:
    """All 4 collectors produce evidence simultaneously on a combined fixture."""

    @pytest.fixture()
    def spy(self) -> _EvidenceSpyRule:
        return _EvidenceSpyRule()

    @pytest.fixture()
    def result(self, spy: _EvidenceSpyRule) -> RunResult:
        return _run_engine(
            MULTI_ECO_REPO,
            [
                NodejsDepsCollector(),
                GoDepsCollector(),
                JavaDepsCollector(),
                CsharpDepsCollector(),
            ],
            spy,
        )

    def test_all_four_evidence_kinds_produced(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        kinds = {e.kind for e in spy.captured}
        assert "nodejs-deps" in kinds
        assert "go-deps" in kinds
        assert "java-deps" in kinds
        assert "csharp-deps" in kinds

    def test_each_has_dependencies(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        for kind in ("nodejs-deps", "go-deps", "java-deps", "csharp-deps"):
            evidence = _evidence_by_kind(spy, kind)
            assert len(evidence.payload["dependencies"]) >= 2, f"{kind} has <2 deps"

    def test_no_cross_contamination(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        nodejs_ev = _evidence_by_kind(spy, "nodejs-deps")
        go_ev = _evidence_by_kind(spy, "go-deps")
        nodejs_names = {d["name"] for d in nodejs_ev.payload["dependencies"]}
        go_names = {d["name"] for d in go_ev.payload["dependencies"]}
        assert not nodejs_names & go_names

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert len(result.warnings) == 0


class TestGracefulDegradation:
    """Evidence still produced when deps.dev returns None for all packages."""

    @pytest.fixture()
    def spy(self) -> _EvidenceSpyRule:
        return _EvidenceSpyRule()

    @pytest.fixture()
    def result(self, spy: _EvidenceSpyRule) -> RunResult:
        return _run_engine(
            MULTI_ECO_REPO,
            [
                NodejsDepsCollector(),
                GoDepsCollector(),
                JavaDepsCollector(),
                CsharpDepsCollector(),
            ],
            spy,
            side_effect=lambda *a: None,
        )

    def test_all_four_evidence_kinds_still_produced(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        kinds = {e.kind for e in spy.captured}
        assert "nodejs-deps" in kinds
        assert "go-deps" in kinds
        assert "java-deps" in kinds
        assert "csharp-deps" in kinds

    def test_deps_dev_status_is_error(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        for kind in ("nodejs-deps", "go-deps", "java-deps", "csharp-deps"):
            evidence = _evidence_by_kind(spy, kind)
            deps = evidence.payload["dependencies"]
            assert all(d["deps_dev_status"] == "error" for d in deps), (
                f"{kind} status mismatch"
            )

    def test_latest_version_is_none(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        for kind in ("nodejs-deps", "go-deps", "java-deps", "csharp-deps"):
            evidence = _evidence_by_kind(spy, kind)
            deps = evidence.payload["dependencies"]
            assert all(d["latest_version"] is None for d in deps), f"{kind} version not None"

    def test_enrichment_errors_populated(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        for kind in ("nodejs-deps", "go-deps", "java-deps", "csharp-deps"):
            evidence = _evidence_by_kind(spy, kind)
            assert len(evidence.payload["enrichment_errors"]) >= 1, f"{kind} no errors logged"

    def test_no_engine_crash(self, result: RunResult) -> None:
        assert result is not None
        assert len(result.warnings) == 0
