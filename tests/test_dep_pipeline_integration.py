"""Integration test: dep findings flow through CSV/JSONL pipeline across all 5 ecosystems.

Exercises the full Engine pipeline with all 5 ecosystem collectors, dep-freshness
rule, and dep-upgrade-path rule in a single run. Mocks deps.dev to return controlled
version data. Verifies findings appear in both CSV and JSONL output with correct
R007 field shape.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from nfr_review.collectors.csharp_deps import CsharpDepsCollector
from nfr_review.collectors.go_deps import GoDepsCollector
from nfr_review.collectors.java_deps import JavaDepsCollector
from nfr_review.collectors.nodejs_deps import NodejsDepsCollector
from nfr_review.collectors.python_deps import PythonDepsCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.dep_solver import ResolveResult
from nfr_review.engine import Engine, RunResult
from nfr_review.output.csv import CSV_HEADER, write_csv
from nfr_review.output.jsonl import write_jsonl
from nfr_review.registry import Registry
from nfr_review.rules.dep_freshness import DepFreshnessRule
from nfr_review.rules.dep_upgrade_path import DepUpgradePathRule

FIXTURES = Path(__file__).parent / "fixtures"
MULTI_ECO_REPO = FIXTURES / "multi-ecosystem-deps-repo"

ALL_COLLECTOR_NAMES = {"python-deps", "nodejs-deps", "java-deps", "go-deps", "csharp-deps"}


def _fake_package_versions(ecosystem: str, package_name: str) -> dict | None:
    return {
        "versions": [
            {
                "versionKey": {"version": "99.0.0"},
                "publishedAt": "2026-01-15T00:00:00Z",
            }
        ]
    }


def _fake_resolve(dependencies: list[dict], client: Any, ecosystem: str) -> ResolveResult:
    """Return a controlled ResolveResult that resolves all deps to 99.0.0."""
    optimal = {dep["name"]: "99.0.0" for dep in dependencies}
    return ResolveResult(optimal_set=optimal, unsolvable=False, blocking_constraints=[])


def _build_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("python-deps", PythonDepsCollector())
    cregistry.register("nodejs-deps", NodejsDepsCollector())
    cregistry.register("java-deps", JavaDepsCollector())
    cregistry.register("go-deps", GoDepsCollector())
    cregistry.register("csharp-deps", CsharpDepsCollector())

    rregistry.register("dep-freshness", DepFreshnessRule())
    rregistry.register("dep-upgrade-path", DepUpgradePathRule())

    return cregistry, rregistry


def _run_pipeline() -> RunResult:
    cregistry, rregistry = _build_registries()
    engine = Engine(collectors=cregistry, rules=rregistry)
    cfg = Config()
    with (
        patch(
            "nfr_review.deps_dev_client.DepsDevClient.get_package_versions",
            side_effect=_fake_package_versions,
        ),
        patch(
            "nfr_review.rules.dep_upgrade_path.resolve_dependencies",
            side_effect=_fake_resolve,
        ),
    ):
        return engine.run(target=MULTI_ECO_REPO, config=cfg)


class TestDepPipelineEndToEnd:
    """Full 5-ecosystem dep pipeline → CSV + JSONL output."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_pipeline()

    @pytest.fixture(scope="class")
    def csv_path(self, result: RunResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
        p = tmp_path_factory.mktemp("output") / "nfr-report.csv"
        write_csv(result, p)
        return p

    @pytest.fixture(scope="class")
    def jsonl_path(self, result: RunResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
        p = tmp_path_factory.mktemp("output") / "nfr-report.jsonl"
        write_jsonl(result, p)
        return p

    @pytest.fixture(scope="class")
    def csv_rows(self, csv_path: Path) -> list[dict[str, str]]:
        with csv_path.open(encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    @pytest.fixture(scope="class")
    def jsonl_records(self, jsonl_path: Path) -> list[dict[str, Any]]:
        with jsonl_path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    # ── CSV assertions ──────────────────────────────────────────────────

    def test_csv_header_matches(self, csv_path: Path) -> None:
        with csv_path.open(encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = tuple(next(reader))
        assert header == CSV_HEADER

    def test_csv_has_dep_freshness_finding(self, csv_rows: list[dict[str, str]]) -> None:
        freshness = [r for r in csv_rows if r["rule_id"] == "dep-freshness"]
        assert len(freshness) >= 1, "Expected at least one dep-freshness finding in CSV"

    def test_csv_has_dep_upgrade_path_finding(self, csv_rows: list[dict[str, str]]) -> None:
        upgrade = [r for r in csv_rows if r["rule_id"] == "dep-upgrade-path"]
        assert len(upgrade) >= 1, "Expected at least one dep-upgrade-path finding in CSV"

    def test_csv_all_10_fields_populated(self, csv_rows: list[dict[str, str]]) -> None:
        for row in csv_rows:
            if row.get("rag") == "skipped":
                continue
            for field in CSV_HEADER:
                assert row.get(field, "") != "", (
                    f"Field {field!r} is empty in row with rule_id={row.get('rule_id')}"
                )

    # ── JSONL assertions ────────────────────────────────────────────────

    def test_jsonl_first_line_is_run_metadata(
        self, jsonl_records: list[dict[str, Any]]
    ) -> None:
        assert len(jsonl_records) >= 1
        assert jsonl_records[0]["record_type"] == "run_metadata"

    def test_jsonl_metadata_has_all_5_collectors(
        self, jsonl_records: list[dict[str, Any]]
    ) -> None:
        metadata = jsonl_records[0]
        collector_versions = metadata.get("collector_versions", {})
        for name in ALL_COLLECTOR_NAMES:
            assert name in collector_versions, (
                f"Collector {name!r} missing from run_metadata.collector_versions"
            )

    def test_jsonl_has_dep_freshness_finding(
        self, jsonl_records: list[dict[str, Any]]
    ) -> None:
        findings = [
            r
            for r in jsonl_records
            if r.get("record_type") == "finding" and r.get("rule_id") == "dep-freshness"
        ]
        assert len(findings) >= 1, "Expected at least one dep-freshness finding in JSONL"

    def test_jsonl_has_dep_upgrade_path_finding(
        self, jsonl_records: list[dict[str, Any]]
    ) -> None:
        findings = [
            r
            for r in jsonl_records
            if r.get("record_type") == "finding" and r.get("rule_id") == "dep-upgrade-path"
        ]
        assert len(findings) >= 1, "Expected at least one dep-upgrade-path finding in JSONL"

    # ── Multi-ecosystem coverage ────────────────────────────────────────

    def test_findings_from_at_least_2_collectors(self, result: RunResult) -> None:
        collector_names = {f.collector_name for f in result.findings}
        overlap = collector_names & ALL_COLLECTOR_NAMES
        assert len(overlap) >= 2, f"Expected findings from ≥2 collectors, got {overlap}"

    def test_all_5_collectors_succeeded(self, result: RunResult) -> None:
        assert result.run_metadata is not None
        for name in ALL_COLLECTOR_NAMES:
            assert name in result.run_metadata.collector_versions

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert len(result.warnings) == 0, f"Engine warnings: {result.warnings}"

    def test_both_dep_rules_ran(self, result: RunResult) -> None:
        assert result.run_metadata is not None
        assert "dep-freshness" in result.run_metadata.rules_run
        assert "dep-upgrade-path" in result.run_metadata.rules_run
