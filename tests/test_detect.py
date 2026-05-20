from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from nfr_review.detect import ALL_TECH_KEYS, detect_technologies

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_false(result: dict[str, bool]) -> bool:
    return all(v is False for v in result.values())


def _has_all_keys(result: dict[str, bool]) -> bool:
    return set(result.keys()) == set(ALL_TECH_KEYS)


# ---------------------------------------------------------------------------
# Whole-function behaviour
# ---------------------------------------------------------------------------


class TestDetectTechnologiesWholeFunction:
    def test_empty_directory_returns_all_false(self, tmp_path: Path) -> None:
        result = detect_technologies(tmp_path)
        assert _has_all_keys(result)
        assert _all_false(result)

    def test_nonexistent_path_returns_all_false(self, tmp_path: Path) -> None:
        result = detect_technologies(tmp_path / "does-not-exist")
        assert _has_all_keys(result)
        assert _all_false(result)

    def test_always_returns_all_keys(self, tmp_path: Path) -> None:
        result = detect_technologies(tmp_path)
        assert len(result) == len(ALL_TECH_KEYS)
        assert set(result.keys()) == set(ALL_TECH_KEYS)

    def test_polyglot_repo(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "Dockerfile").write_text("FROM openjdk:17")
        (tmp_path / "k8s").mkdir()
        (tmp_path / "k8s" / "deploy.yaml").write_text("kind: Deployment\n")
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / ".github" / "workflows" / "ci.yml").write_text("on: push")

        result = detect_technologies(tmp_path)
        assert _has_all_keys(result)
        assert result["java"] is True
        assert result["dockerfile"] is True
        assert result["kubernetes"] is True
        assert result["ci"] is True
        assert result["python"] is False


# ---------------------------------------------------------------------------
# Individual technology detectors — positive cases
# ---------------------------------------------------------------------------


class TestDetectJava:
    def test_pom_xml(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text("<project/>")
        assert detect_technologies(tmp_path)["java"] is True

    def test_build_gradle(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'")
        assert detect_technologies(tmp_path)["java"] is True

    def test_build_gradle_kts(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle.kts").write_text("plugins { java }")
        assert detect_technologies(tmp_path)["java"] is True

    def test_java_files_under_src(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "main" / "java").mkdir(parents=True)
        (tmp_path / "src" / "main" / "java" / "Foo.java").write_text("class Foo {}")
        assert detect_technologies(tmp_path)["java"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["java"] is False


class TestDetectSpringBoot:
    def test_application_yml(self, tmp_path: Path) -> None:
        resources = tmp_path / "src" / "main" / "resources"
        resources.mkdir(parents=True)
        (resources / "application.yml").write_text("server:\n  port: 8080")
        assert detect_technologies(tmp_path)["spring_boot"] is True

    def test_application_properties(self, tmp_path: Path) -> None:
        resources = tmp_path / "src" / "main" / "resources"
        resources.mkdir(parents=True)
        (resources / "application.properties").write_text("server.port=8080")
        assert detect_technologies(tmp_path)["spring_boot"] is True

    def test_spring_boot_in_pom(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text("<dependency>spring-boot-starter</dependency>")
        assert detect_technologies(tmp_path)["spring_boot"] is True

    def test_spring_boot_in_gradle(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle").write_text(
            "implementation 'org.springframework.boot:spring-boot-starter'"
        )
        assert detect_technologies(tmp_path)["spring_boot"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["spring_boot"] is False


class TestDetectKubernetes:
    def test_kustomization_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "kustomization.yaml").write_text("resources:\n  - deploy.yaml")
        assert detect_technologies(tmp_path)["kubernetes"] is True

    def test_k8s_directory_with_deployment(self, tmp_path: Path) -> None:
        (tmp_path / "k8s").mkdir()
        (tmp_path / "k8s" / "deploy.yaml").write_text("kind: Deployment\n")
        assert detect_technologies(tmp_path)["kubernetes"] is True

    def test_kubernetes_directory_with_service(self, tmp_path: Path) -> None:
        (tmp_path / "kubernetes").mkdir()
        (tmp_path / "kubernetes" / "svc.yaml").write_text("kind: Service\n")
        assert detect_technologies(tmp_path)["kubernetes"] is True

    def test_yaml_without_k8s_kinds_is_negative(self, tmp_path: Path) -> None:
        (tmp_path / "k8s").mkdir()
        (tmp_path / "k8s" / "random.yaml").write_text("foo: bar\n")
        assert detect_technologies(tmp_path)["kubernetes"] is False

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["kubernetes"] is False


class TestDetectApim:
    def test_apim_policy_xml(self, tmp_path: Path) -> None:
        (tmp_path / "policies").mkdir()
        (tmp_path / "policies" / "api.xml").write_text(
            "<policies><inbound/><backend/><outbound/></policies>"
        )
        assert detect_technologies(tmp_path)["apim"] is True

    def test_xml_without_apim_tags_is_negative(self, tmp_path: Path) -> None:
        (tmp_path / "data.xml").write_text("<root><item/></root>")
        assert detect_technologies(tmp_path)["apim"] is False

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["apim"] is False


class TestDetectCi:
    def test_github_workflows(self, tmp_path: Path) -> None:
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("on: push")
        assert detect_technologies(tmp_path)["ci"] is True

    def test_gitlab_ci(self, tmp_path: Path) -> None:
        (tmp_path / ".gitlab-ci.yml").write_text("stages: [build]")
        assert detect_technologies(tmp_path)["ci"] is True

    def test_jenkinsfile(self, tmp_path: Path) -> None:
        (tmp_path / "Jenkinsfile").write_text("pipeline {}")
        assert detect_technologies(tmp_path)["ci"] is True

    def test_azure_pipelines(self, tmp_path: Path) -> None:
        (tmp_path / "azure-pipelines.yml").write_text("trigger: none")
        assert detect_technologies(tmp_path)["ci"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["ci"] is False


class TestDetectAdr:
    def test_docs_adr(self, tmp_path: Path) -> None:
        d = tmp_path / "docs" / "adr"
        d.mkdir(parents=True)
        (d / "001-use-java.md").write_text("# Use Java")
        assert detect_technologies(tmp_path)["adr"] is True

    def test_doc_adr(self, tmp_path: Path) -> None:
        d = tmp_path / "doc" / "adr"
        d.mkdir(parents=True)
        (d / "001.md").write_text("# ADR")
        assert detect_technologies(tmp_path)["adr"] is True

    def test_adr_root(self, tmp_path: Path) -> None:
        d = tmp_path / "adr"
        d.mkdir()
        (d / "001.md").write_text("# ADR")
        assert detect_technologies(tmp_path)["adr"] is True

    def test_empty_adr_dir_is_negative(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "adr").mkdir(parents=True)
        assert detect_technologies(tmp_path)["adr"] is False

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["adr"] is False


class TestDetectDockerfile:
    def test_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM alpine")
        assert detect_technologies(tmp_path)["dockerfile"] is True

    def test_docker_compose_yml(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        assert detect_technologies(tmp_path)["dockerfile"] is True

    def test_docker_compose_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yaml").write_text("version: '3'")
        assert detect_technologies(tmp_path)["dockerfile"] is True

    def test_named_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "app.Dockerfile").write_text("FROM node:20")
        assert detect_technologies(tmp_path)["dockerfile"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["dockerfile"] is False


class TestDetectGrpc:
    def test_proto_file(self, tmp_path: Path) -> None:
        (tmp_path / "api").mkdir()
        (tmp_path / "api" / "service.proto").write_text('syntax = "proto3";')
        assert detect_technologies(tmp_path)["grpc"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["grpc"] is False


class TestDetectGo:
    def test_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/app")
        assert detect_technologies(tmp_path)["go"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["go"] is False


class TestDetectPython:
    def test_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'app'")
        assert detect_technologies(tmp_path)["python"] is True

    def test_setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text("from setuptools import setup")
        assert detect_technologies(tmp_path)["python"] is True

    def test_setup_cfg(self, tmp_path: Path) -> None:
        (tmp_path / "setup.cfg").write_text("[metadata]\nname = app")
        assert detect_technologies(tmp_path)["python"] is True

    def test_requirements_txt(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("flask==3.0")
        assert detect_technologies(tmp_path)["python"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["python"] is False


class TestDetectNodejs:
    def test_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "app"}')
        assert detect_technologies(tmp_path)["nodejs"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["nodejs"] is False


class TestDetectCsharp:
    def test_csproj(self, tmp_path: Path) -> None:
        (tmp_path / "App.csproj").write_text("<Project/>")
        assert detect_technologies(tmp_path)["csharp"] is True

    def test_sln(self, tmp_path: Path) -> None:
        (tmp_path / "App.sln").write_text("Microsoft Visual Studio Solution File")
        assert detect_technologies(tmp_path)["csharp"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["csharp"] is False


class TestDetectIstio:
    def test_istio_directory(self, tmp_path: Path) -> None:
        (tmp_path / "istio").mkdir()
        assert detect_technologies(tmp_path)["istio"] is True

    def test_virtual_service_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "networking.yaml").write_text("kind: VirtualService\n")
        assert detect_technologies(tmp_path)["istio"] is True

    def test_destination_rule_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "networking.yaml").write_text("kind: DestinationRule\n")
        assert detect_technologies(tmp_path)["istio"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["istio"] is False


class TestDetectOtel:
    def test_otel_in_pom(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text(
            "<dependency>io.opentelemetry:opentelemetry-api</dependency>"
        )
        assert detect_technologies(tmp_path)["otel"] is True

    def test_otel_in_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("require go.opentelemetry.io/otel v1.24.0")
        assert detect_technologies(tmp_path)["otel"] is True

    def test_otel_in_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            '{"dependencies": {"@opentelemetry/api": "1.0"}}'
        )
        assert detect_technologies(tmp_path)["otel"] is True

    def test_otel_in_requirements(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("opentelemetry-sdk==1.24")
        assert detect_technologies(tmp_path)["otel"] is True

    def test_otel_in_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["opentelemetry-sdk"]'
        )
        assert detect_technologies(tmp_path)["otel"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["otel"] is False


class TestDetectHelm:
    def test_chart_yaml_at_root(self, tmp_path: Path) -> None:
        (tmp_path / "Chart.yaml").write_text("apiVersion: v2\nname: myapp\n")
        assert detect_technologies(tmp_path)["helm"] is True

    def test_chart_yaml_nested(self, tmp_path: Path) -> None:
        charts = tmp_path / "charts" / "myapp"
        charts.mkdir(parents=True)
        (charts / "Chart.yaml").write_text("apiVersion: v2\nname: myapp\n")
        assert detect_technologies(tmp_path)["helm"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["helm"] is False


class TestDetectSkaffold:
    def test_skaffold_yaml_at_root(self, tmp_path: Path) -> None:
        (tmp_path / "skaffold.yaml").write_text("apiVersion: skaffold/v4beta6\n")
        assert detect_technologies(tmp_path)["skaffold"] is True

    def test_skaffold_yaml_nested(self, tmp_path: Path) -> None:
        sub = tmp_path / "deploy"
        sub.mkdir()
        (sub / "skaffold.yaml").write_text("apiVersion: skaffold/v4beta6\n")
        assert detect_technologies(tmp_path)["skaffold"] is True

    def test_negative(self, tmp_path: Path) -> None:
        assert detect_technologies(tmp_path)["skaffold"] is False


# ---------------------------------------------------------------------------
# Error handling / negative tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.skipif(os.getuid() == 0, reason="root can read any file")
    def test_unreadable_file_skipped_gracefully(self, tmp_path: Path) -> None:
        marker = tmp_path / "pom.xml"
        marker.write_text("<project/>")
        marker.chmod(0o000)
        try:
            result = detect_technologies(tmp_path)
            assert _has_all_keys(result)
            assert result["java"] is True  # detected via filename existence
        finally:
            marker.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.skipif(os.getuid() == 0, reason="root can read any file")
    def test_unreadable_spring_boot_marker_returns_false(self, tmp_path: Path) -> None:
        pom = tmp_path / "pom.xml"
        pom.write_text("<project>spring-boot</project>")
        pom.chmod(0o000)
        try:
            result = detect_technologies(tmp_path)
            assert result["spring_boot"] is False
        finally:
            pom.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_deeply_nested_java_marker(self, tmp_path: Path) -> None:
        deep = tmp_path / "src" / "main" / "java" / "com" / "example"
        deep.mkdir(parents=True)
        (deep / "App.java").write_text("class App {}")
        assert detect_technologies(tmp_path)["java"] is True

    def test_unrecognized_file_types_returns_all_false(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "data.csv").write_text("a,b,c")
        result = detect_technologies(tmp_path)
        assert _has_all_keys(result)
        assert _all_false(result)

    def test_one_detector_failure_does_not_affect_others(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/app")
        result = detect_technologies(tmp_path)
        assert result["go"] is True
        assert result["java"] is False
        assert _has_all_keys(result)
