from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config, RulesConfig
from nfr_review.engine import Engine, EngineError, RunResult
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.registry import (
    Registry,
    collector_registry,
    rule_registry,
)
from nfr_review.rules.sample import ReadmeExistsRule


class _StaticCollector:
    def __init__(self, name: str, evidence: list[Evidence]) -> None:
        self.name = name
        self.version = "0.0.1"
        self._evidence = evidence

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        return list(self._evidence)


class _RaisingCollector:
    name = "raises"
    version = "0.0.1"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        raise RuntimeError("boom-collector")


class _StaticRule:
    def __init__(
        self,
        rule_id: str,
        result: RuleResult,
        required: list[str] | None = None,
    ) -> None:
        self.id = rule_id
        self.band = 1
        self.required_collectors = required or []
        self._result = result

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        return self._result


class _RaisingRule:
    id = "raises-rule"
    band = 1
    required_collectors: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        raise RuntimeError("boom-rule")


def _make_finding(rule_id: str = "static") -> Finding:
    return Finding(
        rule_id=rule_id,
        rag="green",
        severity="info",
        summary="ok",
        recommendation="none",
        evidence_locator="x",
        collector_name="c",
        collector_version="0.0.1",
        confidence=1.0,
        pattern_tag="x",
    )


def test_target_missing_raises_engine_error(tmp_path: Path) -> None:
    engine, _, _ = _make_engine()
    missing = tmp_path / "does-not-exist"
    with pytest.raises(EngineError) as exc:
        engine.run(missing, Config())
    assert str(missing) in str(exc.value)


def test_target_is_file_raises_engine_error(tmp_path: Path) -> None:
    engine, _, _ = _make_engine()
    f = tmp_path / "f.txt"
    f.write_text("hi")
    with pytest.raises(EngineError):
        engine.run(f, Config())


def _make_engine() -> tuple[Engine, Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    engine = Engine(collectors=cregistry, rules=rregistry)
    return engine, cregistry, rregistry


def test_engine_run_returns_run_result_never_none(tmp_path: Path) -> None:
    engine, _, _ = _make_engine()
    result = engine.run(tmp_path, Config())
    assert isinstance(result, RunResult)
    assert result.run_metadata is not None
    assert result.findings == []
    assert result.rule_results == []


def test_collector_exception_does_not_abort_run(tmp_path: Path) -> None:
    engine, cregistry, rregistry = _make_engine()
    good_evidence = Evidence(
        collector_name="good",
        collector_version="0.0.1",
        locator=str(tmp_path),
        kind="x",
        payload={},
    )
    cregistry.register("raises", _RaisingCollector())
    cregistry.register("good", _StaticCollector("good", [good_evidence]))

    rregistry.register(
        "needs-good",
        _StaticRule(
            "needs-good",
            RuleResult(rule_id="needs-good", findings=[_make_finding("needs-good")]),
            required=["good"],
        ),
    )
    rregistry.register(
        "needs-broken",
        _StaticRule(
            "needs-broken",
            RuleResult(rule_id="needs-broken"),
            required=["raises"],
        ),
    )

    result = engine.run(tmp_path, Config())

    assert any("raises" in w for w in result.warnings)
    rule_ids = [r.rule_id for r in result.rule_results]
    assert "needs-good" in rule_ids
    assert "needs-broken" in rule_ids
    needs_broken = next(r for r in result.rule_results if r.rule_id == "needs-broken")
    assert needs_broken.skipped is True
    assert needs_broken.skip_reason is not None
    assert "raises" in needs_broken.skip_reason
    skipped_ids = {entry["rule_id"] for entry in result.run_metadata.rules_skipped}
    assert "needs-broken" in skipped_ids
    assert result.run_metadata.rules_run == ["needs-good"]


def test_rule_exception_does_not_abort_run(tmp_path: Path) -> None:
    engine, _, rregistry = _make_engine()
    rregistry.register("raises-rule", _RaisingRule())
    rregistry.register(
        "still-runs",
        _StaticRule(
            "still-runs",
            RuleResult(rule_id="still-runs", findings=[_make_finding("still-runs")]),
        ),
    )

    result = engine.run(tmp_path, Config())

    assert {r.rule_id for r in result.rule_results} == {"raises-rule", "still-runs"}
    raises_result = next(r for r in result.rule_results if r.rule_id == "raises-rule")
    assert raises_result.skipped is True
    assert "boom-rule" in (raises_result.skip_reason or "")
    still = next(r for r in result.rule_results if r.rule_id == "still-runs")
    assert still.skipped is False
    assert len(still.findings) == 1
    assert "raises-rule" in {
        entry["rule_id"] for entry in result.run_metadata.rules_skipped
    }


def test_config_rules_skip_excludes_rule(tmp_path: Path) -> None:
    engine, _, rregistry = _make_engine()
    rregistry.register(
        "drop-me",
        _StaticRule(
            "drop-me",
            RuleResult(rule_id="drop-me", findings=[_make_finding("drop-me")]),
        ),
    )
    cfg = Config(rules=RulesConfig(skip=["drop-me"]))
    result = engine.run(tmp_path, cfg)

    assert result.findings == []
    skipped_entries = result.run_metadata.rules_skipped
    assert any(e["rule_id"] == "drop-me" for e in skipped_entries)
    assert result.run_metadata.rules_run == []


def test_config_rules_include_only_filters(tmp_path: Path) -> None:
    engine, _, rregistry = _make_engine()
    rregistry.register(
        "keep",
        _StaticRule(
            "keep",
            RuleResult(rule_id="keep", findings=[_make_finding("keep")]),
        ),
    )
    rregistry.register(
        "drop",
        _StaticRule(
            "drop",
            RuleResult(rule_id="drop", findings=[_make_finding("drop")]),
        ),
    )
    cfg = Config(rules=RulesConfig(include_only=["keep"]))
    result = engine.run(tmp_path, cfg)

    assert [f.rule_id for f in result.findings] == ["keep"]
    skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
    assert "drop" in skipped_ids


def test_config_collectors_skip_propagates_to_dependent_rules(
    tmp_path: Path,
) -> None:
    engine, cregistry, rregistry = _make_engine()
    cregistry.register(
        "alpha",
        _StaticCollector(
            "alpha",
            [
                Evidence(
                    collector_name="alpha",
                    collector_version="0.0.1",
                    locator=str(tmp_path),
                    kind="x",
                    payload={},
                )
            ],
        ),
    )
    rregistry.register(
        "needs-alpha",
        _StaticRule(
            "needs-alpha",
            RuleResult(rule_id="needs-alpha", findings=[_make_finding("needs-alpha")]),
            required=["alpha"],
        ),
    )

    cfg = Config(collectors={"skip": ["alpha"]})
    result = engine.run(tmp_path, cfg)

    rule_result = result.rule_results[0]
    assert rule_result.skipped is True
    assert "alpha" in (rule_result.skip_reason or "")
    assert result.findings == []


def test_run_metadata_records_collector_versions(tmp_path: Path) -> None:
    engine, cregistry, _ = _make_engine()
    cregistry.register("alpha", _StaticCollector("alpha", []))
    cregistry.register("beta", _StaticCollector("beta", []))
    result = engine.run(tmp_path, Config())
    assert result.run_metadata.collector_versions == {
        "alpha": "0.0.1",
        "beta": "0.0.1",
    }


# ----- RepoStructureCollector -----------------------------------------------


def test_repo_structure_collector_detects_readme(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hi")
    (tmp_path / "src").mkdir()
    collector = RepoStructureCollector()
    evidence = collector.collect(tmp_path, Config())
    assert len(evidence) == 1
    payload = evidence[0].payload
    assert payload["has_readme"] is True
    assert payload["readme_name"] == "README.md"
    assert "src" in payload["top_level_dirs"]
    assert "README.md" in payload["top_level_files"]


def test_repo_structure_collector_no_readme(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    collector = RepoStructureCollector()
    payload = collector.collect(tmp_path, Config())[0].payload
    assert payload["has_readme"] is False
    assert payload["readme_name"] is None


# ----- ReadmeExistsRule -----------------------------------------------------


def _repo_structure_evidence(*, has_readme: bool) -> Evidence:
    return Evidence(
        collector_name="repo-structure",
        collector_version="0.1.0",
        locator="/tmp/x",
        kind="repo-structure-summary",
        payload={
            "has_readme": has_readme,
            "readme_name": "README.md" if has_readme else None,
            "top_level_files": [],
            "top_level_dirs": [],
            "has_git_dir": False,
            "has_pyproject": False,
        },
    )


def test_readme_rule_green_when_readme_present() -> None:
    rule = ReadmeExistsRule()
    result = rule.evaluate([_repo_structure_evidence(has_readme=True)], Config())
    assert result.skipped is False
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.rag == "green"
    assert finding.rule_id == "sample-readme-exists"


def test_readme_rule_amber_when_readme_absent() -> None:
    rule = ReadmeExistsRule()
    result = rule.evaluate([_repo_structure_evidence(has_readme=False)], Config())
    assert result.skipped is False
    assert result.findings[0].rag == "amber"
    assert result.findings[0].severity == "medium"


def test_readme_rule_skips_without_repo_structure_evidence() -> None:
    rule = ReadmeExistsRule()
    result = rule.evaluate([], Config())
    assert result.skipped is True
    assert "repo-structure" in (result.skip_reason or "")


# ----- Auto-registration ----------------------------------------------------


def test_sample_collector_and_rule_autoregistered() -> None:
    # Importing the sample modules must register them; if a previous test
    # cleared the global registries, re-import via importlib would normally
    # fix it but module caches mean we must directly verify the singletons.
    # We accept both states (already-registered or absent) and re-register
    # if needed, then assert presence.
    from nfr_review.collectors import repo_structure as _rs
    from nfr_review.rules import sample as _sample

    if "repo-structure" not in collector_registry:
        collector_registry.register(
            "repo-structure", _rs.RepoStructureCollector()
        )
    if "sample-readme-exists" not in rule_registry:
        rule_registry.register("sample-readme-exists", _sample.ReadmeExistsRule())

    assert "repo-structure" in collector_registry
    assert "sample-readme-exists" in rule_registry


# ----- End-to-end with real sample collector + rule -------------------------


class _TechGatedRule:
    """A rule that requires specific tech declarations."""

    def __init__(self, rule_id: str, tech: list[str]) -> None:
        self.id = rule_id
        self.band = 1
        self.required_collectors: list[str] = []
        self.required_tech: list[str] = tech

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        return RuleResult(rule_id=self.id, findings=[_make_finding(self.id)])


def test_tech_filter_skips_rule_when_tech_empty(tmp_path: Path) -> None:
    engine, _, rregistry = _make_engine()
    rregistry.register("spring-rule", _TechGatedRule("spring-rule", ["spring_boot"]))
    cfg = Config(tech={})
    result = engine.run(tmp_path, cfg)

    rule_result = result.rule_results[0]
    assert rule_result.skipped is True
    assert "tech not declared: spring_boot" in (rule_result.skip_reason or "")


def test_tech_filter_allows_rule_when_tech_declared(tmp_path: Path) -> None:
    engine, _, rregistry = _make_engine()
    rregistry.register("spring-rule", _TechGatedRule("spring-rule", ["spring_boot"]))
    cfg = Config(tech={"spring_boot": True})
    result = engine.run(tmp_path, cfg)

    rule_result = result.rule_results[0]
    assert rule_result.skipped is False
    assert len(rule_result.findings) == 1


def test_tech_filter_does_not_affect_rules_without_required_tech(
    tmp_path: Path,
) -> None:
    engine, _, rregistry = _make_engine()
    rregistry.register(
        "no-tech-rule",
        _StaticRule(
            "no-tech-rule",
            RuleResult(rule_id="no-tech-rule", findings=[_make_finding("no-tech-rule")]),
        ),
    )
    cfg = Config(tech={})
    result = engine.run(tmp_path, cfg)

    rule_result = result.rule_results[0]
    assert rule_result.skipped is False
    assert len(rule_result.findings) == 1


def test_tech_filter_skip_reason_appears_in_rules_skipped(tmp_path: Path) -> None:
    engine, _, rregistry = _make_engine()
    rregistry.register("apim-rule", _TechGatedRule("apim-rule", ["apim"]))
    cfg = Config(tech={"spring_boot": True})
    result = engine.run(tmp_path, cfg)

    assert result.rule_results[0].skipped is True
    skipped_entry = next(
        e for e in result.run_metadata.rules_skipped if e["rule_id"] == "apim-rule"
    )
    assert skipped_entry["reason"] == "tech not declared: apim"


def test_engine_end_to_end_with_sample_collector_and_rule(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# hi")
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    cregistry.register("repo-structure", RepoStructureCollector())
    rregistry.register("sample-readme-exists", ReadmeExistsRule())
    engine = Engine(collectors=cregistry, rules=rregistry)

    result = engine.run(tmp_path, Config())

    assert len(result.findings) == 1
    assert result.findings[0].rag == "green"
    assert result.findings[0].rule_id == "sample-readme-exists"
    assert result.run_metadata.rules_run == ["sample-readme-exists"]
    assert result.run_metadata.rules_skipped == []
    assert result.run_metadata.collector_versions == {"repo-structure": "0.1.0"}
    assert result.warnings == []
