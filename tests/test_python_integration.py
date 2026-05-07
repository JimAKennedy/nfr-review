"""Integration tests — PythonAstCollector → Engine → Python rules pipeline."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nfr_review.collectors.python_ast import PythonAstCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.python_async_fire_forget import PythonAsyncFireForgetRule
from nfr_review.rules.python_broad_except_silent import PythonBroadExceptSilentRule
from nfr_review.rules.python_mutable_default import PythonMutableDefaultRule
from nfr_review.rules.python_star_import import PythonStarImportRule
from nfr_review.rules.sample import ReadmeExistsRule

FIXTURES = Path(__file__).parent / "fixtures"
PYTHON_REPO = FIXTURES / "python-sample-repo"

PYTHON_RULE_IDS = {
    "python-mutable-default",
    "python-star-import",
    "python-broad-except-silent",
    "python-async-fire-and-forget",
}


def _python_registries() -> tuple[Registry, Registry]:
    """Build registries with python-ast collector and 4 Python rules."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("python-ast", PythonAstCollector())

    rregistry.register("python-mutable-default", PythonMutableDefaultRule())
    rregistry.register("python-star-import", PythonStarImportRule())
    rregistry.register("python-broad-except-silent", PythonBroadExceptSilentRule())
    rregistry.register("python-async-fire-and-forget", PythonAsyncFireForgetRule())

    return cregistry, rregistry


def _python_registries_with_extras() -> tuple[Registry, Registry]:
    """Registries with python-ast collector, 4 Python rules, and repo-structure + sample."""
    cregistry, rregistry = _python_registries()
    cregistry.register("repo-structure", RepoStructureCollector())
    rregistry.register("sample-readme-exists", ReadmeExistsRule())
    return cregistry, rregistry


class TestPythonPipelineEndToEnd:
    """Full pipeline: PythonAstCollector → Engine → all 4 Python rules produce findings."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _python_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        return engine.run(target=PYTHON_REPO, config=cfg)

    def test_collector_ran(self, result: RunResult) -> None:
        assert "python-ast" in result.run_metadata.collector_versions

    def test_all_four_rules_fired(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert PYTHON_RULE_IDS <= run_set

    def test_no_python_rules_skipped(self, result: RunResult) -> None:
        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        assert not (PYTHON_RULE_IDS & skipped_ids)

    def test_mutable_default_findings(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "python-mutable-default"]
        assert len(findings) >= 5

    def test_star_import_findings(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "python-star-import"]
        assert len(findings) >= 2

    def test_broad_except_findings(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "python-broad-except-silent"]
        assert len(findings) >= 2

    def test_async_fire_forget_findings(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "python-async-fire-and-forget"]
        assert len(findings) >= 2

    def test_total_findings_minimum(self, result: RunResult) -> None:
        assert len(result.findings) >= 6

    def test_no_warnings(self, result: RunResult) -> None:
        assert result.warnings == []


class TestTechGatingCollectorAbsent:
    """When python-ast collector is NOT registered, all 4 Python rules are skipped."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")

        cregistry.register("repo-structure", RepoStructureCollector())

        rregistry.register("sample-readme-exists", ReadmeExistsRule())
        rregistry.register("python-mutable-default", PythonMutableDefaultRule())
        rregistry.register("python-star-import", PythonStarImportRule())
        rregistry.register("python-broad-except-silent", PythonBroadExceptSilentRule())
        rregistry.register("python-async-fire-and-forget", PythonAsyncFireForgetRule())

        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": False})
        return engine.run(target=PYTHON_REPO, config=cfg)

    def test_all_four_python_rules_skipped(self, result: RunResult) -> None:
        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        assert PYTHON_RULE_IDS <= skipped_ids

    def test_skip_reason_mentions_missing_collector(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in PYTHON_RULE_IDS:
            assert "missing required collectors" in skipped[rule_id]
            assert "python-ast" in skipped[rule_id]

    def test_non_python_rules_still_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set

    def test_no_python_findings(self, result: RunResult) -> None:
        python_findings = [f for f in result.findings if f.rule_id in PYTHON_RULE_IDS]
        assert python_findings == []


class TestGoodCodeNoFindings:
    """Running only against good_code.py produces green findings — no amber/red."""

    @pytest.fixture()
    def result(self, tmp_path: Path) -> RunResult:
        shutil.copy(PYTHON_REPO / "good_code.py", tmp_path / "good_code.py")

        cregistry, rregistry = _python_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        return engine.run(target=tmp_path, config=cfg)

    def test_all_four_rules_fired(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert PYTHON_RULE_IDS <= run_set

    def test_no_amber_or_red_findings(self, result: RunResult) -> None:
        bad_findings = [f for f in result.findings if f.rag in ("amber", "red")]
        assert bad_findings == []

    def test_all_findings_are_green(self, result: RunResult) -> None:
        for finding in result.findings:
            assert finding.rag == "green", (
                f"Expected green but got {finding.rag} for {finding.rule_id}"
            )


class TestEvidenceStructure:
    """Verify Evidence objects have correct structure from PythonAstCollector."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry: Registry = Registry("collector")
        cregistry.register("python-ast", PythonAstCollector())
        rregistry: Registry = Registry("rule")

        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        return engine.run(target=PYTHON_REPO, config=cfg)

    def test_evidence_collector_name(self, result: RunResult) -> None:
        assert "python-ast" in result.run_metadata.collector_versions

    def test_evidence_in_findings_has_correct_collector(self, result: RunResult) -> None:
        cregistry, rregistry = _python_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        full_result = engine.run(target=PYTHON_REPO, config=cfg)

        for finding in full_result.findings:
            if finding.rule_id in PYTHON_RULE_IDS:
                assert finding.collector_name == "python-ast"


class TestEvidencePayloadFields:
    """Verify that evidence payloads contain all required fields."""

    def test_payload_contains_all_required_fields(self) -> None:
        collector = PythonAstCollector()
        cfg = Config(tech={"python": True})
        evidence = collector.collect(PYTHON_REPO, cfg)

        assert len(evidence) >= 1
        required_keys = {
            "catch_blocks",
            "log_statements",
            "functions",
            "imports",
            "async_calls",
        }
        for ev in evidence:
            assert ev.collector_name == "python-ast"
            assert ev.kind == "python-ast-file"
            assert required_keys <= set(ev.payload.keys())
            assert "file_path" in ev.payload


class TestMultipleFindingsPerRule:
    """Verify rules detect multiple instances in a single file."""

    def test_mutable_default_finds_five_in_bad_defaults(self, tmp_path: Path) -> None:
        shutil.copy(PYTHON_REPO / "bad_defaults.py", tmp_path / "bad_defaults.py")

        cregistry, rregistry = _python_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        result = engine.run(target=tmp_path, config=cfg)

        mutable_findings = [
            f
            for f in result.findings
            if f.rule_id == "python-mutable-default" and f.rag != "green"
        ]
        assert len(mutable_findings) == 5

    def test_star_import_finds_two_in_bad_imports(self, tmp_path: Path) -> None:
        shutil.copy(PYTHON_REPO / "bad_imports.py", tmp_path / "bad_imports.py")

        cregistry, rregistry = _python_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        result = engine.run(target=tmp_path, config=cfg)

        star_findings = [
            f
            for f in result.findings
            if f.rule_id == "python-star-import" and f.rag != "green"
        ]
        assert len(star_findings) == 2


class TestMixedCollectorRun:
    """Python rules fire alongside non-Python rules when both collector types registered."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _python_registries_with_extras()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        return engine.run(target=PYTHON_REPO, config=cfg)

    def test_python_rules_in_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert PYTHON_RULE_IDS <= run_set

    def test_sample_rule_also_runs(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set

    def test_both_collectors_ran(self, result: RunResult) -> None:
        versions = result.run_metadata.collector_versions
        assert "python-ast" in versions
        assert "repo-structure" in versions


class TestRulesRunCount:
    """Verify exactly 4 Python rule IDs appear in rules_run."""

    def test_four_python_rules_in_run(self) -> None:
        cregistry, rregistry = _python_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        result = engine.run(target=PYTHON_REPO, config=cfg)

        python_run = {r for r in result.run_metadata.rules_run if r.startswith("python-")}
        assert python_run == PYTHON_RULE_IDS


class TestFindingSeverityAndRag:
    """Verify findings have expected severity and RAG values."""

    def test_amber_findings_from_bad_files(self) -> None:
        cregistry, rregistry = _python_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        result = engine.run(target=PYTHON_REPO, config=cfg)

        amber_findings = [f for f in result.findings if f.rag == "amber"]
        assert len(amber_findings) >= 4

    def test_all_findings_have_valid_rag(self) -> None:
        cregistry, rregistry = _python_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        result = engine.run(target=PYTHON_REPO, config=cfg)

        for finding in result.findings:
            assert finding.rag in ("green", "amber", "red")

    def test_all_findings_have_confidence(self) -> None:
        cregistry, rregistry = _python_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"python": True})
        result = engine.run(target=PYTHON_REPO, config=cfg)

        for finding in result.findings:
            assert 0.0 <= finding.confidence <= 1.0
