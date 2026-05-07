"""Tests for skaffold-build-config rule."""

from __future__ import annotations

import importlib
from pathlib import Path

from nfr_review.collectors.skaffold import SkaffoldCollector
from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.skaffold_build import SkaffoldBuildConfigRule


def _make_evidence(build: dict | None = None, profiles: list | None = None) -> list[Evidence]:
    payload: dict = {
        "file_path": "skaffold.yaml",
        "api_version": "skaffold/v4beta6",
        "build": build if build is not None else {},
        "deploy": {"kubectl": {"manifests": ["k8s/*.yaml"]}},
        "profiles": profiles or [],
    }
    return [
        Evidence(
            collector_name="skaffold",
            collector_version="0.1.0",
            locator="skaffold.yaml",
            kind="skaffold-analysis",
            payload=payload,
        )
    ]


class TestSkaffoldBuildConfigRegistration:
    def test_registered_in_rule_registry(self) -> None:
        import nfr_review.rules.skaffold_build

        importlib.reload(nfr_review.rules.skaffold_build)
        assert "skaffold-build-config" in rule_registry

    def test_rule_id(self) -> None:
        rule = SkaffoldBuildConfigRule()
        assert rule.id == "skaffold-build-config"

    def test_required_collectors(self) -> None:
        rule = SkaffoldBuildConfigRule()
        assert rule.required_collectors == ["skaffold"]

    def test_required_tech(self) -> None:
        rule = SkaffoldBuildConfigRule()
        assert rule.required_tech == ["skaffold"]


class TestSkaffoldBuildConfigSkip:
    def test_skipped_with_no_evidence(self) -> None:
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate([], context=None)
        assert result.skipped is True
        assert "no skaffold-analysis" in result.skip_reason

    def test_skipped_with_unrelated_evidence(self) -> None:
        unrelated = Evidence(
            collector_name="istio",
            collector_version="0.1.0",
            locator="istio.yaml",
            kind="istio-analysis",
            payload={},
        )
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate([unrelated], context=None)
        assert result.skipped is True


class TestSkaffoldBuildConfigRed:
    def test_no_build_section(self) -> None:
        evidence = _make_evidence(build={})
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert "no build section" in result.findings[0].summary

    def test_build_without_artifacts(self) -> None:
        evidence = _make_evidence(build={"tagPolicy": {"sha256": {}}})
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert result.findings[0].rag == "red"

    def test_none_build(self) -> None:
        ev = Evidence(
            collector_name="skaffold",
            collector_version="0.1.0",
            locator="skaffold.yaml",
            kind="skaffold-analysis",
            payload={
                "file_path": "skaffold.yaml",
                "api_version": "skaffold/v4beta6",
                "build": None,
                "deploy": {},
                "profiles": [],
            },
        )
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "red"


class TestSkaffoldBuildConfigAmber:
    def test_git_commit_tag_policy(self) -> None:
        evidence = _make_evidence(
            build={"artifacts": [{"image": "app"}], "tagPolicy": {"gitCommit": {}}}
        )
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert result.findings[0].rag == "amber"
        assert "gitCommit" in result.findings[0].summary

    def test_no_tag_policy(self) -> None:
        evidence = _make_evidence(build={"artifacts": [{"image": "app"}]})
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert result.findings[0].rag == "amber"
        assert "no explicit tag policy" in result.findings[0].summary

    def test_empty_tag_policy(self) -> None:
        evidence = _make_evidence(build={"artifacts": [{"image": "app"}], "tagPolicy": {}})
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert result.findings[0].rag == "amber"


class TestSkaffoldBuildConfigGreen:
    def test_sha256_tag_policy(self) -> None:
        evidence = _make_evidence(
            build={"artifacts": [{"image": "app"}], "tagPolicy": {"sha256": {}}}
        )
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert result.findings[0].rag == "green"

    def test_env_template_tag_policy(self) -> None:
        evidence = _make_evidence(
            build={
                "artifacts": [{"image": "app"}],
                "tagPolicy": {"envTemplate": {"template": "{{.IMAGE_TAG}}"}},
            }
        )
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert result.findings[0].rag == "green"

    def test_datetime_tag_policy(self) -> None:
        evidence = _make_evidence(
            build={
                "artifacts": [{"image": "app"}],
                "tagPolicy": {"dateTime": {"format": "2006-01-02"}},
            }
        )
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert result.findings[0].rag == "green"


class TestSkaffoldBuildConfigIntegration:
    def test_sample_repo_produces_amber(self) -> None:
        repo = Path(__file__).parent / "fixtures" / "skaffold-sample-repo"
        collector = SkaffoldCollector()
        evidence = collector.collect(repo, config=None)
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"

    def test_good_repo_produces_green(self) -> None:
        repo = Path(__file__).parent / "fixtures" / "skaffold-good-repo"
        collector = SkaffoldCollector()
        evidence = collector.collect(repo, config=None)
        rule = SkaffoldBuildConfigRule()
        result = rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
