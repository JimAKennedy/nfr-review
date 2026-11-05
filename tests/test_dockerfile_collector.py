"""Tests for the DockerfileCollector — parsing, payload structure, and edge cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.dockerfile import DockerfileCollector
from nfr_review.models import Evidence

FIXTURES = Path(__file__).parent / "fixtures" / "dockerfile-sample-repo"


@pytest.fixture
def collector() -> DockerfileCollector:
    return DockerfileCollector()


def _payload_by_path(results: list[Evidence], substr: str) -> dict[str, Any]:
    return next(e.payload for e in results if substr in e.payload["file_path"])


class TestBasicParsing:
    def test_returns_evidence_for_each_dockerfile(
        self, collector: DockerfileCollector
    ) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert len(results) == 3
        assert all(e.kind == "dockerfile-analysis" for e in results)
        assert all(e.collector_name == "dockerfile" for e in results)
        assert all(e.collector_version == "0.1.0" for e in results)

    def test_payload_has_required_keys(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        required_keys = {
            "file_path",
            "stages",
            "user_directives",
            "has_user_directive",
            "run_commands",
            "copy_add_commands",
            "env_args",
            "stage_count",
            "is_multistage",
        }
        for ev in results:
            assert required_keys.issubset(ev.payload.keys())


class TestBadDockerfile:
    """The root Dockerfile is intentionally bad: unpinned, no USER, single stage."""

    def test_unpinned_base_image(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "Dockerfile")
        # Filter out ones that are in services/ subdirectory
        if "services" in payload["file_path"]:
            payload = next(
                e.payload for e in results if e.payload["file_path"] == "Dockerfile"
            )
        stages = payload["stages"]
        assert len(stages) == 1
        assert stages[0]["base_image"] == "python"
        assert stages[0]["base_tag"] == "latest"
        assert stages[0]["has_digest"] is False

    def test_no_user_directive(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = next(e.payload for e in results if e.payload["file_path"] == "Dockerfile")
        assert payload["has_user_directive"] is False
        assert payload["user_directives"] == []

    def test_single_stage(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = next(e.payload for e in results if e.payload["file_path"] == "Dockerfile")
        assert payload["stage_count"] == 1
        assert payload["is_multistage"] is False

    def test_secret_looking_args(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = next(e.payload for e in results if e.payload["file_path"] == "Dockerfile")
        arg_names = [e["name"] for e in payload["env_args"] if e["instruction"] == "ARG"]
        assert "SECRET_KEY" in arg_names
        assert "DB_PASSWORD" in arg_names

    def test_copy_of_env_file(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = next(e.payload for e in results if e.payload["file_path"] == "Dockerfile")
        sources = [src for cmd in payload["copy_add_commands"] for src in cmd["sources"]]
        assert ".env" in sources


class TestGoodDockerfile:
    """The good Dockerfile: pinned with digest, USER directive, multi-stage."""

    def test_pinned_base_with_digest(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "services/good")
        stages = payload["stages"]
        assert len(stages) == 2
        assert stages[0]["base_image"] == "golang"
        assert stages[0]["base_tag"] == "1.22.3"
        assert stages[0]["has_digest"] is True
        assert stages[0]["name"] == "builder"

    def test_has_user_directive(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "services/good")
        assert payload["has_user_directive"] is True
        assert any(d["user"].startswith("nonroot") for d in payload["user_directives"])

    def test_multi_stage(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "services/good")
        assert payload["stage_count"] == 2
        assert payload["is_multistage"] is True


class TestPartialDockerfile:
    """The partial Dockerfile: pinned tag (no digest), multi-stage, but no USER."""

    def test_pinned_but_no_digest(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "services/partial")
        stages = payload["stages"]
        assert stages[0]["base_tag"] == "20.12.2-slim"
        assert stages[0]["has_digest"] is False

    def test_no_user_directive(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "services/partial")
        assert payload["has_user_directive"] is False

    def test_is_multistage(self, collector: DockerfileCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "services/partial")
        assert payload["is_multistage"] is True
        assert payload["stage_count"] == 2


class TestEdgeCases:
    def test_empty_repo_produces_empty_evidence(
        self, collector: DockerfileCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_collector_name_and_version(self, collector: DockerfileCollector) -> None:
        assert collector.name == "dockerfile"
        assert collector.version == "0.1.0"
