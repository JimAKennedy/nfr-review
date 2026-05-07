"""Skaffold integration tests — full Engine pipeline with SkaffoldCollector."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.collectors.skaffold import SkaffoldCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.sample import ReadmeExistsRule
from nfr_review.rules.skaffold_build import SkaffoldBuildConfigRule

FIXTURES = Path(__file__).parent / "fixtures"
SKAFFOLD_SAMPLE = FIXTURES / "skaffold-sample-repo"
SKAFFOLD_GOOD = FIXTURES / "skaffold-good-repo"

SKAFFOLD_RULE_IDS = {
    "skaffold-build-config",
}


def _skaffold_registries() -> tuple[Registry, Registry]:
    """Build registries with SkaffoldCollector + Skaffold rules (plus baseline)."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("skaffold", SkaffoldCollector())

    rregistry.register("sample-readme-exists", ReadmeExistsRule())
    rregistry.register("skaffold-build-config", SkaffoldBuildConfigRule())

    return cregistry, rregistry


class TestSkaffoldPipelineFindings:
    """Full collector->evidence->rules->findings pipeline against skaffold-sample-repo."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _skaffold_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"skaffold": True})
        return engine.run(target=SKAFFOLD_SAMPLE, config=cfg)

    def test_build_config_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "skaffold-build-config"]
        assert len(findings) >= 1
        assert any(
            "tag" in f.summary.lower() or "build" in f.summary.lower() for f in findings
        )

    def test_all_skaffold_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert SKAFFOLD_RULE_IDS <= run_set

    def test_finding_metadata_complete(self, result: RunResult) -> None:
        skaffold_findings = [f for f in result.findings if f.rule_id in SKAFFOLD_RULE_IDS]
        for f in skaffold_findings:
            assert f.rule_id, "missing rule_id"
            assert f.rag, "missing rag"
            assert f.severity, "missing severity"
            assert f.evidence_locator, "missing evidence_locator"
            assert f.recommendation, "missing recommendation"

    def test_run_metadata_has_skaffold_collector_version(self, result: RunResult) -> None:
        assert "skaffold" in result.run_metadata.collector_versions
        assert result.run_metadata.collector_versions["skaffold"] == "0.1.0"


class TestSkaffoldTechGating:
    """Skaffold rules are skipped when tech={"skaffold": False}."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _skaffold_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"skaffold": False})
        return engine.run(target=SKAFFOLD_SAMPLE, config=cfg)

    def test_all_skaffold_rules_skipped(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in SKAFFOLD_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: skaffold" in skipped[rule_id]

    def test_no_skaffold_findings_produced(self, result: RunResult) -> None:
        skaffold_findings = [f for f in result.findings if f.rule_id in SKAFFOLD_RULE_IDS]
        assert len(skaffold_findings) == 0

    def test_non_skaffold_rules_still_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set


class TestSkaffoldGoodRepo:
    """Good repo produces green/clean findings."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _skaffold_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"skaffold": True})
        return engine.run(target=SKAFFOLD_GOOD, config=cfg)

    def test_all_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert SKAFFOLD_RULE_IDS <= run_set

    def test_all_findings_green(self, result: RunResult) -> None:
        skaffold_findings = [f for f in result.findings if f.rule_id in SKAFFOLD_RULE_IDS]
        assert len(skaffold_findings) >= 1
        assert all(f.rag == "green" for f in skaffold_findings)

    def test_no_amber_or_red_findings(self, result: RunResult) -> None:
        bad_findings = [
            f
            for f in result.findings
            if f.rule_id in SKAFFOLD_RULE_IDS and f.rag in ("amber", "red")
        ]
        assert len(bad_findings) == 0


class TestSkaffoldEmptyTechSkipsAll:
    """With empty tech dict, all Skaffold rules are tech-skipped."""

    def test_skaffold_rules_skipped_with_empty_tech(self) -> None:
        cregistry, rregistry = _skaffold_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        result = engine.run(target=SKAFFOLD_SAMPLE, config=cfg)

        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in SKAFFOLD_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: skaffold" in skipped[rule_id]
