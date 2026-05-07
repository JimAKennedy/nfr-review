"""Tests for SkaffoldCollector."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from nfr_review.collectors.skaffold import SkaffoldCollector
from nfr_review.registry import collector_registry


class TestSkaffoldCollectorRegistration:
    def test_registered_in_collector_registry(self) -> None:
        import nfr_review.collectors.skaffold

        importlib.reload(nfr_review.collectors.skaffold)
        assert "skaffold" in collector_registry

    def test_collector_name(self) -> None:
        collector = SkaffoldCollector()
        assert collector.name == "skaffold"

    def test_collector_version(self) -> None:
        collector = SkaffoldCollector()
        assert collector.version == "0.1.0"


class TestSkaffoldCollectorSampleRepo:
    @pytest.fixture()
    def evidence(self) -> list:
        repo = Path(__file__).parent / "fixtures" / "skaffold-sample-repo"
        collector = SkaffoldCollector()
        return collector.collect(repo, config=None)

    def test_produces_evidence(self, evidence: list) -> None:
        assert len(evidence) == 1

    def test_evidence_kind(self, evidence: list) -> None:
        assert evidence[0].kind == "skaffold-analysis"

    def test_evidence_collector_name(self, evidence: list) -> None:
        assert evidence[0].collector_name == "skaffold"

    def test_evidence_collector_version(self, evidence: list) -> None:
        assert evidence[0].collector_version == "0.1.0"

    def test_payload_has_api_version(self, evidence: list) -> None:
        assert "skaffold" in evidence[0].payload["api_version"]

    def test_payload_has_build(self, evidence: list) -> None:
        build = evidence[0].payload["build"]
        assert "artifacts" in build

    def test_payload_has_deploy(self, evidence: list) -> None:
        deploy = evidence[0].payload["deploy"]
        assert "kubectl" in deploy

    def test_payload_profiles_empty(self, evidence: list) -> None:
        assert evidence[0].payload["profiles"] == []


class TestSkaffoldCollectorGoodRepo:
    @pytest.fixture()
    def evidence(self) -> list:
        repo = Path(__file__).parent / "fixtures" / "skaffold-good-repo"
        collector = SkaffoldCollector()
        return collector.collect(repo, config=None)

    def test_produces_evidence(self, evidence: list) -> None:
        assert len(evidence) == 1

    def test_payload_has_profiles(self, evidence: list) -> None:
        profiles = evidence[0].payload["profiles"]
        assert len(profiles) == 2

    def test_payload_tag_policy_is_sha256(self, evidence: list) -> None:
        build = evidence[0].payload["build"]
        assert "sha256" in build.get("tagPolicy", {})


class TestSkaffoldCollectorEdgeCases:
    def test_empty_directory(self, tmp_path: Path) -> None:
        collector = SkaffoldCollector()
        result = collector.collect(tmp_path, config=None)
        assert result == []

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        collector = SkaffoldCollector()
        result = collector.collect(tmp_path / "nope", config=None)
        assert result == []

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        hidden = tmp_path / ".git" / "hooks"
        hidden.mkdir(parents=True)
        (hidden / "skaffold.yaml").write_text("apiVersion: skaffold/v4beta6\nkind: Config\n")
        collector = SkaffoldCollector()
        result = collector.collect(tmp_path, config=None)
        assert result == []

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "skaffold.yaml").write_text("{{invalid yaml")
        collector = SkaffoldCollector()
        result = collector.collect(tmp_path, config=None)
        assert result == []

    def test_non_skaffold_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "skaffold.yaml").write_text("apiVersion: apps/v1\nkind: Deployment\n")
        collector = SkaffoldCollector()
        result = collector.collect(tmp_path, config=None)
        assert result == []

    def test_skaffold_without_build(self, tmp_path: Path) -> None:
        (tmp_path / "skaffold.yaml").write_text("apiVersion: skaffold/v4beta6\nkind: Config\n")
        collector = SkaffoldCollector()
        result = collector.collect(tmp_path, config=None)
        assert len(result) == 1
        assert result[0].payload["build"] == {}
