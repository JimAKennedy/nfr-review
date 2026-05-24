"""Integration tests for the path-exclusion pipeline.

Verifies end-to-end: engine with real collectors on fixtures excludes
findings from test paths by default, and --include-tests
(exclude_test_paths=False) includes them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from nfr_review.collectors.java_ast import JavaAstCollector
from nfr_review.collectors.python_deps import PythonDepsCollector
from nfr_review.config import Config
from nfr_review.engine import Engine
from nfr_review.models import Evidence, RuleResult
from nfr_review.registry import Registry
from nfr_review.rules.ast_bare_except import BareExceptCatchAllRule

_JAVA_BARE_CATCH = """\
package com.example;

public class App {
    public void doWork() {
        try {
            int x = 1 / 0;
        } catch (Exception e) {
            // swallowed
        }
    }
}
"""


class _PassThroughRule:
    """Rule that records the evidence it received — for assertion."""

    id = "pass-through"
    band = 1
    required_collectors: list[str] = []

    def __init__(self) -> None:
        self.seen_evidence: list[Evidence] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        self.seen_evidence = list(evidence)
        return RuleResult(rule_id=self.id)


def _write_java_fixture(tmp_path: Path) -> None:
    """Create a Java file with a bare catch at both src/ and tests/ paths."""
    src_dir = tmp_path / "src" / "main" / "java" / "com" / "example"
    src_dir.mkdir(parents=True)
    (src_dir / "App.java").write_text(_JAVA_BARE_CATCH, encoding="utf-8")

    test_dir = tmp_path / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "AppTest.java").write_text(_JAVA_BARE_CATCH, encoding="utf-8")


def test_engine_excludes_test_path_findings(tmp_path: Path) -> None:
    _write_java_fixture(tmp_path)

    collectors: Registry = Registry("collector")
    collectors.register("java-ast", JavaAstCollector())

    rules: Registry = Registry("rule")
    rules.register("bare-except-catch-all", BareExceptCatchAllRule())

    engine = Engine(collectors=collectors, rules=rules)
    config = Config()
    result = engine.run(tmp_path, config)

    non_green = [f for f in result.findings if f.rag != "green"]
    assert len(non_green) > 0, "Expected at least one non-green finding from src/"
    for f in non_green:
        assert not f.evidence_locator.startswith("tests/"), (
            f"Finding from test path should have been filtered: {f.evidence_locator}"
        )
        assert f.evidence_locator.startswith("src/"), (
            f"Expected finding from src/ path: {f.evidence_locator}"
        )


def test_engine_includes_test_path_findings_with_flag(tmp_path: Path) -> None:
    _write_java_fixture(tmp_path)

    collectors: Registry = Registry("collector")
    collectors.register("java-ast", JavaAstCollector())

    rules: Registry = Registry("rule")
    rules.register("bare-except-catch-all", BareExceptCatchAllRule())

    engine = Engine(collectors=collectors, rules=rules)
    config = Config(exclude_test_paths=False)
    result = engine.run(tmp_path, config)

    non_green = [f for f in result.findings if f.rag != "green"]
    locators = {f.evidence_locator for f in non_green}
    src_locators = {loc for loc in locators if loc.startswith("src/")}
    test_locators = {loc for loc in locators if loc.startswith("tests/")}
    assert len(src_locators) > 0, "Expected findings from src/ paths"
    assert len(test_locators) > 0, (
        "Expected findings from tests/ paths with exclude_test_paths=False"
    )


def test_dep_collector_skips_fixture_manifests_e2e(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests>=2.28\n", encoding="utf-8")

    fixture_dir = tmp_path / "tests" / "fixtures" / "sample"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "requirements.txt").write_text("flask>=2.0\n", encoding="utf-8")

    collector = PythonDepsCollector()
    config = Config()

    import nfr_review.collectors.python_deps as pdm

    original_client_cls = pdm.DepsDevClient
    mock_client = MagicMock()
    mock_client.prefetch_package_versions = MagicMock()
    mock_client.get_package_version.return_value = None
    pdm.DepsDevClient = lambda: mock_client  # type: ignore[assignment,misc]
    try:
        evidence = collector.collect(tmp_path, config)
    finally:
        pdm.DepsDevClient = original_client_cls  # type: ignore[misc]

    assert len(evidence) == 1
    manifest_files = evidence[0].payload["manifest_files_found"]
    assert manifest_files == ["requirements.txt"], (
        f"Expected only root requirements.txt, got: {manifest_files}"
    )
