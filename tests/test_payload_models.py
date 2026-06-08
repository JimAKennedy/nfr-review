# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for typed payload infrastructure and ADR payload models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload
from nfr_review.collectors.payloads.ci import (
    CiPipelinePayload,
    CiSummaryPayload,
    CmakeTestSignalFile,
    CmakeTestSignalsPayload,
)
from nfr_review.collectors.payloads.deps import DependencyItem, DepsPayload
from nfr_review.collectors.payloads.dockerfile import (
    DockerfileAnalysisPayload,
    DockerStage,
)
from nfr_review.collectors.payloads.k8s import (
    K8sContainer,
    K8sManifestSummaryPayload,
    K8sPdbPayload,
    K8sResourcePayload,
)
from nfr_review.collectors.payloads.repo_structure import RepoStructureSummaryPayload
from nfr_review.models import BasePayload, Evidence


class TestBasePayload:
    def test_empty_base_payload(self) -> None:
        p = BasePayload()
        assert p.model_dump() == {}

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            BasePayload(bogus="nope")  # type: ignore[call-arg]


class TestEvidencePayloadUnion:
    def test_accepts_dict_payload(self) -> None:
        e = Evidence(
            collector_name="test",
            collector_version="0.1",
            locator="x",
            kind="test",
            payload={"key": "val"},
        )
        assert isinstance(e.payload, dict)
        assert e.payload["key"] == "val"

    def test_accepts_typed_payload(self) -> None:
        p = AdrDocumentPayload(file_path="docs/adr/0001.md", title="Test")
        e = Evidence(
            collector_name="adr",
            collector_version="0.1",
            locator="x",
            kind="adr-document",
            payload=p,
        )
        assert isinstance(e.payload, AdrDocumentPayload)
        assert e.payload.file_path == "docs/adr/0001.md"
        assert e.payload.title == "Test"

    def test_default_payload_is_empty_dict(self) -> None:
        e = Evidence(
            collector_name="test",
            collector_version="0.1",
            locator="x",
            kind="test",
        )
        assert e.payload == {}
        assert isinstance(e.payload, dict)

    def test_dict_payload_roundtrip(self) -> None:
        e = Evidence(
            collector_name="test",
            collector_version="0.1",
            locator="x",
            kind="test",
            payload={"count": 42},
        )
        dumped = e.model_dump()
        assert dumped["payload"] == {"count": 42}
        restored = Evidence(**dumped)
        assert restored == e

    def test_typed_payload_serializes_to_dict(self) -> None:
        p = AdrDocumentPayload(
            file_path="docs/adr/0001.md",
            title="Use Spring Boot",
            status="accepted",
            has_frontmatter=True,
        )
        e = Evidence(
            collector_name="adr",
            collector_version="0.1",
            locator="x",
            kind="adr-document",
            payload=p,
        )
        dumped = e.model_dump()
        assert dumped["payload"] == {
            "file_path": "docs/adr/0001.md",
            "title": "Use Spring Boot",
            "status": "accepted",
            "date": None,
            "superseded_by": None,
            "has_frontmatter": True,
            "body_text": "",
        }


class TestAdrDocumentPayload:
    def test_minimal_construction(self) -> None:
        p = AdrDocumentPayload(file_path="docs/adr/0001.md")
        assert p.file_path == "docs/adr/0001.md"
        assert p.title is None
        assert p.status is None
        assert p.date is None
        assert p.superseded_by is None
        assert p.has_frontmatter is False

    def test_full_construction(self) -> None:
        p = AdrDocumentPayload(
            file_path="docs/adr/0001.md",
            title="Use Spring Boot",
            status="accepted",
            date="2024-01-15",
            superseded_by="0002",
            has_frontmatter=True,
        )
        assert p.title == "Use Spring Boot"
        assert p.status == "accepted"
        assert p.date == "2024-01-15"
        assert p.superseded_by == "0002"
        assert p.has_frontmatter is True

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            AdrDocumentPayload(file_path="x", bogus="nope")  # type: ignore[call-arg]

    def test_requires_file_path(self) -> None:
        with pytest.raises(ValidationError):
            AdrDocumentPayload()  # type: ignore[call-arg]

    def test_json_schema(self) -> None:
        schema = AdrDocumentPayload.model_json_schema()
        assert "file_path" in schema["properties"]
        assert schema["properties"]["file_path"]["type"] == "string"
        assert "file_path" in schema["required"]


class TestAdrSummaryPayload:
    def test_construction(self) -> None:
        p = AdrSummaryPayload(
            total_adrs=3,
            statuses={"accepted": 2, "superseded": 1},
            has_lifecycle_tracking=True,
        )
        assert p.total_adrs == 3
        assert p.statuses == {"accepted": 2, "superseded": 1}
        assert p.has_lifecycle_tracking is True

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            AdrSummaryPayload(  # type: ignore[call-arg]
                total_adrs=1,
                statuses={},
                has_lifecycle_tracking=False,
                bogus="nope",
            )

    def test_requires_all_fields(self) -> None:
        with pytest.raises(ValidationError):
            AdrSummaryPayload(total_adrs=1)  # type: ignore[call-arg]


class TestDepsPayload:
    def test_minimal_dependency_item(self) -> None:
        d = DependencyItem(
            name="requests",
            declared_version=">=2.28",
            version_constraint=">=2.28",
            source_file="requirements.txt",
        )
        assert d.name == "requests"
        assert d.deps_dev_status == "error"
        assert d.scope is None
        assert d.indirect is None

    def test_full_dependency_item(self) -> None:
        d = DependencyItem(
            name="junit:junit",
            declared_version="4.13.2",
            version_constraint=">=4.13.2",
            source_file="pom.xml",
            latest_version="4.13.2",
            latest_release_date="2021-02-13",
            deps_dev_status="ok",
            scope="test",
        )
        assert d.scope == "test"
        assert d.latest_version == "4.13.2"

    def test_deps_payload(self) -> None:
        dep = DependencyItem(
            name="click",
            declared_version=">=8.1",
            version_constraint=">=8.1",
            source_file="pyproject.toml",
            deps_dev_status="ok",
        )
        p = DepsPayload(
            dependencies=[dep],
            manifest_files_found=["pyproject.toml"],
            enrichment_errors=[],
        )
        assert len(p.dependencies) == 1
        assert p.dependencies[0].name == "click"

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            DependencyItem(  # type: ignore[call-arg]
                name="x",
                declared_version="1",
                version_constraint="1",
                source_file="f",
                bogus="nope",
            )

    def test_dict_compat(self) -> None:
        d = DependencyItem(
            name="x",
            declared_version="1",
            version_constraint="1",
            source_file="f",
        )
        assert "name" in d
        assert d["name"] == "x"
        assert d.get("name") == "x"
        assert d.get("missing", "default") == "default"
        assert "name" in d.keys()


class TestCiPayloads:
    def test_ci_pipeline(self) -> None:
        p = CiPipelinePayload(
            file_path=".github/workflows/ci.yml",
            ci_system="github-actions",
            has_test_step=True,
            has_security_scan=False,
            job_names=["build", "test"],
            step_names=["checkout", "pytest"],
        )
        assert p.ci_system == "github-actions"
        assert p.has_test_step is True

    def test_cmake_test_signals(self) -> None:
        sig = CmakeTestSignalFile(
            file_path="CMakeLists.txt",
            signals=["enable_testing", "add_test"],
        )
        p = CmakeTestSignalsPayload(files=[sig], has_test_framework=True)
        assert len(p.files) == 1
        assert p.files[0].file_path == "CMakeLists.txt"

    def test_ci_summary(self) -> None:
        p = CiSummaryPayload(
            total_pipelines=2,
            ci_systems=["github-actions", "gitlab-ci"],
            any_test_step=True,
            any_security_scan=True,
        )
        assert p.total_pipelines == 2


class TestDockerfilePayloads:
    def test_dockerfile_analysis(self) -> None:
        stage = DockerStage(
            name="build",
            base_image="python",
            base_tag="3.11-slim",
            line=1,
        )
        p = DockerfileAnalysisPayload(
            file_path="Dockerfile",
            stages=[stage],
            user_directives=[],
            has_user_directive=False,
            run_commands=[],
            copy_add_commands=[],
            env_args=[],
            stage_count=1,
            is_multistage=False,
        )
        assert p.stages[0].base_image == "python"
        assert p.is_multistage is False

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            DockerStage(  # type: ignore[call-arg]
                name="x",
                base_image="y",
                line=1,
                bogus="nope",
            )


class TestK8sPayloads:
    def test_k8s_resource(self) -> None:
        container = K8sContainer(name="app", image="nginx:1.25")
        p = K8sResourcePayload(
            file_path="deploy.yaml",
            kind="Deployment",
            name="web",
            containers=[container],
        )
        assert p.kind == "Deployment"
        assert len(p.containers) == 1
        assert p.containers[0].image == "nginx:1.25"

    def test_k8s_pdb(self) -> None:
        p = K8sPdbPayload(
            file_path="pdb.yaml",
            name="web-pdb",
            min_available=1,
        )
        assert p.min_available == 1
        assert p.max_unavailable is None

    def test_k8s_summary(self) -> None:
        p = K8sManifestSummaryPayload(
            resource_counts={"Deployment": 2, "Service": 1},
            has_network_policy=False,
            files_parsed=3,
            files_failed=0,
        )
        assert p.resource_counts["Deployment"] == 2

    def test_container_coercion_from_dict(self) -> None:
        p = K8sResourcePayload(
            file_path="x.yaml",
            kind="Deployment",
            name="app",
            containers=[{"name": "web", "image": "nginx"}],
        )
        assert isinstance(p.containers[0], K8sContainer)


class TestRepoStructurePayload:
    def test_construction(self) -> None:
        p = RepoStructureSummaryPayload(
            top_level_files=["README.md", "pyproject.toml"],
            top_level_dirs=["src", "tests"],
            has_readme=True,
            readme_name="README.md",
            has_git_dir=True,
            has_pyproject=True,
        )
        assert p.has_readme is True
        assert "README.md" in p.top_level_files
