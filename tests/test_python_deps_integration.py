"""Python deps integration tests — full Engine pipeline with PythonDepsCollector.

Proves the collector is discoverable, produces correctly shaped Evidence through
the Engine.run() pipeline, and degrades gracefully when deps.dev is unavailable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from nfr_review.collectors.python_deps import PythonDepsCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.models import Evidence, RuleResult
from nfr_review.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"
PYTHON_DEPS_SAMPLE = FIXTURES / "python-deps-sample-repo"

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

    id = "test-evidence-spy"
    band = 1
    required_collectors: list[str] = ["python-deps"]
    required_tech: list[str] = []
    captured: list[Evidence]

    def __init__(self) -> None:
        self.captured = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        self.captured.extend(evidence)
        return RuleResult(rule_id=self.id)


def _python_deps_registries(
    spy: _EvidenceSpyRule | None = None,
) -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("python-deps", PythonDepsCollector())
    if spy is not None:
        rregistry.register(spy.id, spy)
    return cregistry, rregistry


def _run_with_mock_deps_dev(
    target: Path,
    side_effect: Any = _fake_package_versions,
    *,
    spy: _EvidenceSpyRule | None = None,
) -> RunResult:
    cregistry, rregistry = _python_deps_registries(spy=spy)
    engine = Engine(collectors=cregistry, rules=rregistry)
    cfg = Config()
    with patch(
        "nfr_review.collectors.python_deps.DepsDevClient.get_package_versions",
        side_effect=side_effect,
    ):
        return engine.run(target=target, config=cfg)


def _python_deps_evidence(spy: _EvidenceSpyRule) -> Evidence:
    matches = [e for e in spy.captured if e.kind == "python-deps"]
    assert len(matches) == 1, f"Expected 1 python-deps evidence, got {len(matches)}"
    return matches[0]


class TestPythonDepsPipeline:
    """Full collector→evidence→rule pipeline through Engine.run()."""

    @pytest.fixture()
    def spy(self) -> _EvidenceSpyRule:
        return _EvidenceSpyRule()

    @pytest.fixture()
    def result(self, spy: _EvidenceSpyRule) -> RunResult:
        return _run_with_mock_deps_dev(PYTHON_DEPS_SAMPLE, spy=spy)

    def test_evidence_produced_with_correct_kind(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        evidence = _python_deps_evidence(spy)
        assert evidence.kind == "python-deps"
        assert evidence.collector_name == "python-deps"

    def test_payload_boundary_contract(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _python_deps_evidence(spy)
        deps = evidence.payload["dependencies"]
        assert len(deps) >= 1
        for dep in deps:
            missing = BOUNDARY_FIELDS - set(dep.keys())
            assert not missing, f"Missing fields in dep {dep.get('name')}: {missing}"

    def test_enrichment_populates_latest_version(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        evidence = _python_deps_evidence(spy)
        deps = evidence.payload["dependencies"]
        ok_deps = [d for d in deps if d["deps_dev_status"] == "ok"]
        assert len(ok_deps) >= 1
        for dep in ok_deps:
            assert dep["latest_version"] == "99.0.0"
            assert dep["latest_release_date"] == "2026-01-15T00:00:00Z"

    def test_payload_has_manifest_files(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        evidence = _python_deps_evidence(spy)
        manifests = evidence.payload["manifest_files_found"]
        assert "requirements.txt" in manifests
        assert "pyproject.toml" in manifests

    def test_payload_has_enrichment_errors_list(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        evidence = _python_deps_evidence(spy)
        assert "enrichment_errors" in evidence.payload
        assert isinstance(evidence.payload["enrichment_errors"], list)

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert len(result.warnings) == 0

    def test_collector_version_in_metadata(self, result: RunResult) -> None:
        assert "python-deps" in result.run_metadata.collector_versions
        assert result.run_metadata.collector_versions["python-deps"] == "0.1.0"

    def test_spy_rule_received_evidence(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        assert spy.id in result.run_metadata.rules_run


class TestGracefulDegradation:
    """Evidence still produced when deps.dev is unavailable."""

    @pytest.fixture()
    def spy(self) -> _EvidenceSpyRule:
        return _EvidenceSpyRule()

    @pytest.fixture()
    def result(self, spy: _EvidenceSpyRule) -> RunResult:
        return _run_with_mock_deps_dev(
            PYTHON_DEPS_SAMPLE, side_effect=lambda *a: None, spy=spy
        )

    def test_evidence_still_produced(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _python_deps_evidence(spy)
        assert evidence.kind == "python-deps"

    def test_deps_dev_status_is_error(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _python_deps_evidence(spy)
        deps = evidence.payload["dependencies"]
        assert all(d["deps_dev_status"] == "error" for d in deps)

    def test_latest_version_is_none(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _python_deps_evidence(spy)
        deps = evidence.payload["dependencies"]
        assert all(d["latest_version"] is None for d in deps)
        assert all(d["latest_release_date"] is None for d in deps)

    def test_declared_versions_still_present(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        evidence = _python_deps_evidence(spy)
        deps = evidence.payload["dependencies"]
        named = {d["name"]: d for d in deps}
        assert "requests" in named
        assert named["requests"]["declared_version"] == ">=2.28"

    def test_enrichment_errors_populated(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        evidence = _python_deps_evidence(spy)
        errors = evidence.payload["enrichment_errors"]
        assert len(errors) >= 1

    def test_no_engine_crash(self, result: RunResult) -> None:
        assert result is not None
        assert len(result.warnings) == 0


class TestEmptyRepoProducesNoEvidence:
    """No Python manifests → no evidence, no crash."""

    def test_empty_repo(self, tmp_path: Path) -> None:
        spy = _EvidenceSpyRule()
        cregistry, rregistry = _python_deps_registries(spy=spy)
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config()
        result = engine.run(target=tmp_path, config=cfg)

        python_evidence = [e for e in spy.captured if e.kind == "python-deps"]
        assert len(python_evidence) == 0
        assert len(result.warnings) == 0


class TestMalformedRequirementsSkipped:
    """Malformed lines in requirements.txt are skipped; valid deps still collected."""

    @pytest.fixture()
    def spy(self) -> _EvidenceSpyRule:
        return _EvidenceSpyRule()

    @pytest.fixture()
    def result(self, spy: _EvidenceSpyRule) -> RunResult:
        return _run_with_mock_deps_dev(PYTHON_DEPS_SAMPLE, spy=spy)

    def test_valid_deps_collected(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _python_deps_evidence(spy)
        deps = evidence.payload["dependencies"]
        names = {d["name"] for d in deps}
        assert "requests" in names
        assert "flask" in names
        assert "pydantic" in names

    def test_malformed_line_excluded(self, result: RunResult, spy: _EvidenceSpyRule) -> None:
        evidence = _python_deps_evidence(spy)
        deps = evidence.payload["dependencies"]
        names = {d["name"] for d in deps}
        assert "!!!not-a-package" not in names

    def test_pyproject_deps_also_collected(
        self, result: RunResult, spy: _EvidenceSpyRule
    ) -> None:
        evidence = _python_deps_evidence(spy)
        deps = evidence.payload["dependencies"]
        names = {d["name"] for d in deps}
        assert "boto3" in names
        assert "rich" in names
        assert "pytest" in names
