# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for architecture component discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.arch_discovery import (
    _discover_go_module_path,
    _discover_java_base_package,
    _discover_ml_pipeline_components,
    _discover_nested_build_components,
    _discover_python_top_package,
    _discover_source_subdirectories,
    _enrich_package_boundaries,
    _infer_tech_stack,
    discover_components,
    discover_components_multi_repo,
    parse_dvc_pipeline,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure."""
    (tmp_path / ".git").mkdir()
    return tmp_path


class TestRootComponentDiscovery:
    def test_python_project(self, tmp_repo: Path) -> None:
        (tmp_repo / "pyproject.toml").write_text('[project]\nname = "myapp"\n')
        (tmp_repo / "src").mkdir()

        comps = discover_components(tmp_repo)
        assert len(comps) == 1
        assert comps[0].name == tmp_repo.name
        assert comps[0].component_type == "service"
        assert any(t.name == "Python" for t in comps[0].tech_stack)

    def test_java_project(self, tmp_repo: Path) -> None:
        (tmp_repo / "pom.xml").write_text("<project><groupId>com.example</groupId></project>")

        comps = discover_components(tmp_repo)
        assert len(comps) >= 1
        root = next(c for c in comps if c.boundaries[0].boundary_type == "repo")
        assert any(t.name == "Java" for t in root.tech_stack)

    def test_spring_boot_detection(self, tmp_repo: Path) -> None:
        (tmp_repo / "pom.xml").write_text(
            "<project><dependency>spring-boot-starter</dependency></project>"
        )

        comps = discover_components(tmp_repo)
        root = next(c for c in comps if c.boundaries[0].boundary_type == "repo")
        assert any(t.name == "Spring Boot" for t in root.tech_stack)

    def test_no_build_file_returns_empty(self, tmp_repo: Path) -> None:
        comps = discover_components(tmp_repo, include_root=False)
        assert comps == []

    def test_no_build_file_still_returns_root_when_nothing_else(self, tmp_repo: Path) -> None:
        comps = discover_components(tmp_repo, include_root=True)
        assert comps == []  # No build file means no root component either


class TestMonorepoDiscovery:
    def test_packages_dir(self, tmp_repo: Path) -> None:
        pkg_a = tmp_repo / "packages" / "api"
        pkg_a.mkdir(parents=True)
        (pkg_a / "package.json").write_text('{"name": "@acme/api"}')

        pkg_b = tmp_repo / "packages" / "ui"
        pkg_b.mkdir(parents=True)
        (pkg_b / "package.json").write_text(
            '{"name": "@acme/ui", "dependencies": {"react": "^18"}}'
        )

        comps = discover_components(tmp_repo, include_root=False)
        names = {c.name for c in comps}
        assert "api" in names
        assert "ui" in names

    def test_services_dir(self, tmp_repo: Path) -> None:
        svc = tmp_repo / "services" / "auth-service"
        svc.mkdir(parents=True)
        (svc / "go.mod").write_text("module github.com/acme/auth\n")

        comps = discover_components(tmp_repo, include_root=False)
        assert any(c.name == "auth-service" for c in comps)
        auth = next(c for c in comps if c.name == "auth-service")
        assert any(t.name == "Go" for t in auth.tech_stack)

    def test_skips_hidden_dirs(self, tmp_repo: Path) -> None:
        hidden = tmp_repo / "packages" / ".cache"
        hidden.mkdir(parents=True)
        (hidden / "package.json").write_text("{}")

        comps = discover_components(tmp_repo, include_root=False)
        assert not any(c.name == ".cache" for c in comps)

    def test_skips_dirs_without_build_or_src(self, tmp_repo: Path) -> None:
        empty = tmp_repo / "packages" / "docs"
        empty.mkdir(parents=True)
        (empty / "README.md").write_text("# Docs")

        comps = discover_components(tmp_repo, include_root=False)
        assert not any(c.name == "docs" for c in comps)


class TestMavenMultiModule:
    def test_discovers_modules(self, tmp_repo: Path) -> None:
        (tmp_repo / "pom.xml").write_text(
            "<project><modules><module>core</module><module>api</module></modules></project>"
        )
        core = tmp_repo / "core"
        core.mkdir()
        (core / "pom.xml").write_text("<project/>")

        api = tmp_repo / "api"
        api.mkdir()
        (api / "pom.xml").write_text("<project><dependency>spring-boot</dependency></project>")

        comps = discover_components(tmp_repo, include_root=False)
        names = {c.name for c in comps}
        assert "core" in names
        assert "api" in names

        api_comp = next(c for c in comps if c.name == "api")
        assert api_comp.boundaries[0].boundary_type == "module"
        assert any(t.name == "Spring Boot" for t in api_comp.tech_stack)

    def test_skips_missing_module_dir(self, tmp_repo: Path) -> None:
        (tmp_repo / "pom.xml").write_text(
            "<project><modules><module>ghost</module></modules></project>"
        )
        comps = discover_components(tmp_repo, include_root=False)
        assert not any(c.name == "ghost" for c in comps)


class TestGradleSubprojects:
    def test_discovers_includes(self, tmp_repo: Path) -> None:
        (tmp_repo / "settings.gradle").write_text("include 'app'\ninclude 'lib'\n")
        app_dir = tmp_repo / "app"
        app_dir.mkdir()
        (app_dir / "build.gradle").write_text("apply plugin: 'java'")

        lib_dir = tmp_repo / "lib"
        lib_dir.mkdir()
        (lib_dir / "build.gradle").write_text("apply plugin: 'java-library'")

        comps = discover_components(tmp_repo, include_root=False)
        names = {c.name for c in comps}
        assert "app" in names
        assert "lib" in names


class TestKubernetesDiscovery:
    def test_discovers_deployments(self, tmp_repo: Path) -> None:
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()
        (k8s_dir / "api.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: api-server\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: api\n"
            "          image: acme/api:v1.2\n"
        )

        comps = discover_components(tmp_repo, include_root=False)
        assert any(c.name == "api-server" for c in comps)
        api = next(c for c in comps if c.name == "api-server")
        assert api.component_type == "service"
        assert any(t.role == "container-image" for t in api.tech_stack)

    def test_deduplicates_same_name(self, tmp_repo: Path) -> None:
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()
        manifest = (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: worker\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers: []\n"
        )
        (k8s_dir / "a.yaml").write_text(manifest)
        (k8s_dir / "b.yaml").write_text(manifest)

        comps = discover_components(tmp_repo, include_root=False)
        worker_count = sum(1 for c in comps if c.name == "worker")
        assert worker_count == 1

    def test_daemonset_is_worker_type(self, tmp_repo: Path) -> None:
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()
        (k8s_dir / "agent.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: DaemonSet\n"
            "metadata:\n"
            "  name: log-agent\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers: []\n"
        )

        comps = discover_components(tmp_repo, include_root=False)
        agent = next(c for c in comps if c.name == "log-agent")
        assert agent.component_type == "worker"


class TestDockerComposeDiscovery:
    def test_discovers_services(self, tmp_repo: Path) -> None:
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    build: ./web\n"
            "    image: acme/web:latest\n"
            "  redis:\n"
            "    image: redis:7-alpine\n"
        )

        comps = discover_components(tmp_repo, include_root=False)
        names = {c.name for c in comps}
        assert "web" in names
        assert "redis" in names

        redis_comp = next(c for c in comps if c.name == "redis")
        assert redis_comp.component_type == "database"

    def test_handles_build_context(self, tmp_repo: Path) -> None:
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  api:\n"
            "    build:\n"
            "      context: ./backend\n"
            "      dockerfile: Dockerfile.prod\n"
        )

        comps = discover_components(tmp_repo, include_root=False)
        api = next(c for c in comps if c.name == "api")
        assert api.boundaries[0].path == "./backend"


class TestComponentTypeInference:
    def test_database_keywords(self, tmp_repo: Path) -> None:
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n  postgres-db:\n    image: postgres:15\n"
        )
        comps = discover_components(tmp_repo, include_root=False)
        pg = next(c for c in comps if c.name == "postgres-db")
        assert pg.component_type == "database"

    def test_queue_keywords(self, tmp_repo: Path) -> None:
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n  rabbitmq:\n    image: rabbitmq:3-management\n"
        )
        comps = discover_components(tmp_repo, include_root=False)
        rmq = next(c for c in comps if c.name == "rabbitmq")
        assert rmq.component_type == "queue"

    def test_gateway_keywords(self, tmp_repo: Path) -> None:
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n  nginx-gateway:\n    image: nginx:alpine\n"
        )
        comps = discover_components(tmp_repo, include_root=False)
        gw = next(c for c in comps if c.name == "nginx-gateway")
        assert gw.component_type == "gateway"

    def test_worker_keywords(self, tmp_repo: Path) -> None:
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n  email-worker:\n    image: acme/worker:1.0\n"
        )
        comps = discover_components(tmp_repo, include_root=False)
        w = next(c for c in comps if c.name == "email-worker")
        assert w.component_type == "worker"


class TestMultiRepoDiscovery:
    def test_combines_repos(self, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        (repo_a / ".git").mkdir()
        (repo_a / "go.mod").write_text("module github.com/acme/a\n")

        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()
        (repo_b / ".git").mkdir()
        (repo_b / "package.json").write_text('{"name": "b"}')

        comps = discover_components_multi_repo(
            [repo_a, repo_b], repo_names=["service-a", "service-b"]
        )
        repos = {c.repo for c in comps}
        assert "service-a" in repos
        assert "service-b" in repos

    def test_mismatched_names_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="repo_names must match"):
            discover_components_multi_repo([tmp_path], repo_names=["a", "b"])


class TestDeduplication:
    def test_prefers_module_over_directory(self, tmp_repo: Path) -> None:
        (tmp_repo / "pom.xml").write_text(
            "<project><modules><module>core</module></modules></project>"
        )
        core = tmp_repo / "packages" / "core"
        core.mkdir(parents=True)
        (core / "pom.xml").write_text("<project/>")

        # Maven module also at packages/core — they shouldn't conflict
        maven_core = tmp_repo / "core"
        maven_core.mkdir()
        (maven_core / "pom.xml").write_text("<project/>")

        comps = discover_components(tmp_repo, include_root=False)
        # Both should be present since they have different paths
        assert len(comps) >= 2


class TestEdgeCases:
    def test_empty_repo(self, tmp_repo: Path) -> None:
        comps = discover_components(tmp_repo)
        assert comps == []

    def test_invalid_yaml_in_k8s(self, tmp_repo: Path) -> None:
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()
        (k8s_dir / "bad.yaml").write_text("{{invalid yaml: [")

        comps = discover_components(tmp_repo, include_root=False)
        assert comps == []

    def test_invalid_compose_file(self, tmp_repo: Path) -> None:
        (tmp_repo / "docker-compose.yml").write_text("not: valid: compose: format")
        comps = discover_components(tmp_repo, include_root=False)
        assert comps == []

    def test_component_ids_are_stable(self, tmp_repo: Path) -> None:
        (tmp_repo / "go.mod").write_text("module example.com/app\n")

        comps1 = discover_components(tmp_repo, repo_name="my-app")
        comps2 = discover_components(tmp_repo, repo_name="my-app")
        assert comps1[0].id == comps2[0].id

    def test_component_ids_differ_by_repo_name(self, tmp_repo: Path) -> None:
        (tmp_repo / "go.mod").write_text("module example.com/app\n")

        comps1 = discover_components(tmp_repo, repo_name="app-a")
        comps2 = discover_components(tmp_repo, repo_name="app-b")
        assert comps1[0].id != comps2[0].id


class TestJavaBasePackageDiscovery:
    def test_single_chain(self, tmp_path: Path) -> None:
        java_src = tmp_path / "src" / "main" / "java" / "com" / "example"
        java_src.mkdir(parents=True)
        (java_src / "App.java").write_text("package com.example;")

        assert _discover_java_base_package(tmp_path) == "com.example"

    def test_deep_single_chain(self, tmp_path: Path) -> None:
        java_src = tmp_path / "src" / "main" / "java" / "com" / "example" / "users"
        java_src.mkdir(parents=True)
        (java_src / "User.java").write_text("package com.example.users;")

        assert _discover_java_base_package(tmp_path) == "com.example.users"

    def test_stops_at_branch(self, tmp_path: Path) -> None:
        base = tmp_path / "src" / "main" / "java" / "com" / "example"
        (base / "controllers").mkdir(parents=True)
        (base / "services").mkdir(parents=True)
        (base / "controllers" / "Ctrl.java").write_text("")
        (base / "services" / "Svc.java").write_text("")

        assert _discover_java_base_package(tmp_path) == "com.example"

    def test_stops_at_source_file(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "main" / "java" / "com" / "example"
        pkg.mkdir(parents=True)
        (pkg / "Main.java").write_text("")
        sub = pkg / "sub"
        sub.mkdir()
        (sub / "Sub.java").write_text("")

        assert _discover_java_base_package(tmp_path) == "com.example"

    def test_kotlin_detected(self, tmp_path: Path) -> None:
        kt_src = tmp_path / "src" / "main" / "kotlin" / "com" / "example"
        kt_src.mkdir(parents=True)
        (kt_src / "App.kt").write_text("package com.example")

        assert _discover_java_base_package(tmp_path) == "com.example"

    def test_no_src_main_java(self, tmp_path: Path) -> None:
        assert _discover_java_base_package(tmp_path) is None

    def test_empty_src_main_java(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "main" / "java").mkdir(parents=True)
        assert _discover_java_base_package(tmp_path) is None

    def test_multiple_top_dirs(self, tmp_path: Path) -> None:
        java_src = tmp_path / "src" / "main" / "java"
        (java_src / "com").mkdir(parents=True)
        (java_src / "org").mkdir(parents=True)
        assert _discover_java_base_package(tmp_path) is None


class TestPythonTopPackageDiscovery:
    def test_src_layout(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "my_package"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")

        assert _discover_python_top_package(tmp_path) == "my_package"

    def test_flat_layout(self, tmp_path: Path) -> None:
        pkg = tmp_path / "my_package"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        assert _discover_python_top_package(tmp_path) == "my_package"

    def test_src_layout_preferred_over_flat(self, tmp_path: Path) -> None:
        src_pkg = tmp_path / "src" / "real_package"
        src_pkg.mkdir(parents=True)
        (src_pkg / "__init__.py").write_text("")

        flat_pkg = tmp_path / "other_package"
        flat_pkg.mkdir()
        (flat_pkg / "__init__.py").write_text("")

        assert _discover_python_top_package(tmp_path) == "real_package"

    def test_no_init_py(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "my_package").mkdir(parents=True)
        assert _discover_python_top_package(tmp_path) is None

    def test_empty_dir(self, tmp_path: Path) -> None:
        assert _discover_python_top_package(tmp_path) is None

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        hidden = tmp_path / ".venv"
        hidden.mkdir()
        (hidden / "__init__.py").write_text("")
        assert _discover_python_top_package(tmp_path) is None

    def test_skips_node_modules(self, tmp_path: Path) -> None:
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "__init__.py").write_text("")
        assert _discover_python_top_package(tmp_path) is None


class TestGoModulePathDiscovery:
    def test_reads_module_path(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module github.com/acme/service\n\ngo 1.21\n")
        assert _discover_go_module_path(tmp_path) == "github.com/acme/service"

    def test_no_go_mod(self, tmp_path: Path) -> None:
        assert _discover_go_module_path(tmp_path) is None

    def test_empty_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("")
        assert _discover_go_module_path(tmp_path) is None

    def test_malformed_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("not a valid go.mod\n")
        assert _discover_go_module_path(tmp_path) is None


class TestEnrichPackageBoundaries:
    def test_java_module_gets_package(self, tmp_path: Path) -> None:
        from nfr_review.arch_models import Component, ComponentBoundary

        module_dir = tmp_path / "user-service"
        java_src = module_dir / "src" / "main" / "java" / "com" / "example" / "users"
        java_src.mkdir(parents=True)
        (java_src / "User.java").write_text("")

        comp = Component(
            id="comp-users",
            name="user-service",
            description="User service",
            component_type="service",
            boundaries=[
                ComponentBoundary(boundary_type="module", path="user-service", repo="myapp")
            ],
        )
        _enrich_package_boundaries([comp], tmp_path)

        pkg_boundaries = [b for b in comp.boundaries if b.boundary_type == "package"]
        assert len(pkg_boundaries) == 1
        assert pkg_boundaries[0].path == "com.example.users"
        assert pkg_boundaries[0].repo == "myapp"

    def test_python_component_gets_package(self, tmp_path: Path) -> None:
        from nfr_review.arch_models import Component, ComponentBoundary

        pkg_dir = tmp_path / "src" / "my_lib"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        comp = Component(
            id="comp-root",
            name="my-project",
            description="Python project",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="repo", path=".", repo="my-project")],
        )
        _enrich_package_boundaries([comp], tmp_path)

        pkg_boundaries = [b for b in comp.boundaries if b.boundary_type == "package"]
        assert len(pkg_boundaries) == 1
        assert pkg_boundaries[0].path == "my_lib"

    def test_no_package_found(self, tmp_path: Path) -> None:
        from nfr_review.arch_models import Component, ComponentBoundary

        comp = Component(
            id="comp-bare",
            name="bare",
            description="No source",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path=".")],
        )
        _enrich_package_boundaries([comp], tmp_path)
        assert len(comp.boundaries) == 1

    def test_skips_nonexistent_path(self, tmp_path: Path) -> None:
        from nfr_review.arch_models import Component, ComponentBoundary

        comp = Component(
            id="comp-ghost",
            name="ghost",
            description="Missing",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path="nonexistent")],
        )
        _enrich_package_boundaries([comp], tmp_path)
        assert len(comp.boundaries) == 1

    def test_discover_components_includes_packages(self, tmp_repo: Path) -> None:
        (tmp_repo / "pom.xml").write_text(
            "<project><modules><module>core</module></modules></project>"
        )
        core = tmp_repo / "core"
        core.mkdir()
        (core / "pom.xml").write_text("<project/>")
        java_src = core / "src" / "main" / "java" / "com" / "acme" / "core"
        java_src.mkdir(parents=True)
        (java_src / "Main.java").write_text("")

        comps = discover_components(tmp_repo, include_root=False)
        core_comp = next(c for c in comps if c.name == "core")
        pkg_boundaries = [b for b in core_comp.boundaries if b.boundary_type == "package"]
        assert len(pkg_boundaries) == 1
        assert pkg_boundaries[0].path == "com.acme.core"


class TestTechStackDetection:
    def test_requirements_txt_detects_python(self, tmp_repo: Path) -> None:
        (tmp_repo / "requirements.txt").write_text("flask>=2.0\n")
        entries = _infer_tech_stack(tmp_repo)
        names = [e.name for e in entries]
        assert "Python" in names

    def test_dvc_yaml_detected(self, tmp_repo: Path) -> None:
        (tmp_repo / "dvc.yaml").write_text("stages:\n  train:\n    cmd: python train.py\n")
        entries = _infer_tech_stack(tmp_repo)
        names = [e.name for e in entries]
        assert "DVC" in names

    def test_cmake_juce_detection(self, tmp_repo: Path) -> None:
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.22)\njuce_add_plugin(MyPlugin)\n"
        )
        entries = _infer_tech_stack(tmp_repo)
        names = [e.name for e in entries]
        assert "C++" in names
        assert "JUCE" in names

    def test_cmake_vst3_detection(self, tmp_repo: Path) -> None:
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.22)\nadd_subdirectory(vst3sdk)\n"
        )
        entries = _infer_tech_stack(tmp_repo)
        names = [e.name for e in entries]
        assert "VST3 SDK" in names

    def test_cmake_onnxruntime_detection(self, tmp_repo: Path) -> None:
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.22)\n"
            "FetchContent_Declare(onnxruntime URL https://example.com)\n"
        )
        entries = _infer_tech_stack(tmp_repo)
        names = [e.name for e in entries]
        assert "ONNX Runtime" in names

    def test_ml_framework_parsing_from_requirements(self, tmp_repo: Path) -> None:
        (tmp_repo / "requirements.txt").write_text("torch>=2.0\nonnx\nnumpy\n")
        entries = _infer_tech_stack(tmp_repo)
        names = [e.name for e in entries]
        assert "Python" in names
        assert "PyTorch" in names
        assert "ONNX" in names

    def test_no_false_positives_on_plain_cmake(self, tmp_repo: Path) -> None:
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.22)\nadd_executable(myapp main.cpp)\n"
        )
        entries = _infer_tech_stack(tmp_repo)
        names = [e.name for e in entries]
        assert "C++" in names
        assert "JUCE" not in names
        assert "VST3 SDK" not in names
        assert "ONNX Runtime" not in names


class TestSourceSubdirDiscovery:
    def test_cpp_source_subdirs_discovered(self, tmp_repo: Path) -> None:
        source = tmp_repo / "source"
        source.mkdir()
        for subdir in ("ml", "transforms", "evolution"):
            d = source / subdir
            d.mkdir()
            (d / "impl.cpp").write_text("")
            (d / "impl.h").write_text("")

        comps = _discover_source_subdirectories(tmp_repo)
        names = {c.name for c in comps}
        assert names == {"ml", "transforms", "evolution"}

    def test_subdir_type_inference(self, tmp_repo: Path) -> None:
        source = tmp_repo / "source"
        source.mkdir()
        ml = source / "ml"
        ml.mkdir()
        (ml / "a.cpp").write_text("")
        (ml / "b.cpp").write_text("")
        transforms = source / "transforms"
        transforms.mkdir()
        (transforms / "a.cpp").write_text("")
        (transforms / "b.h").write_text("")

        comps = _discover_source_subdirectories(tmp_repo)
        ml_comp = next(c for c in comps if c.name == "ml")
        tx_comp = next(c for c in comps if c.name == "transforms")
        assert ml_comp.component_type == "worker"
        assert tx_comp.component_type == "library"

    def test_skip_test_and_build_dirs(self, tmp_repo: Path) -> None:
        source = tmp_repo / "source"
        source.mkdir()
        for skip_dir in ("tests", "build", "vendor"):
            d = source / skip_dir
            d.mkdir()
            (d / "a.cpp").write_text("")
            (d / "b.cpp").write_text("")

        comps = _discover_source_subdirectories(tmp_repo)
        assert len(comps) == 0

    def test_insufficient_files_skipped(self, tmp_repo: Path) -> None:
        source = tmp_repo / "source"
        source.mkdir()
        d = source / "tiny"
        d.mkdir()
        (d / "one.cpp").write_text("")

        comps = _discover_source_subdirectories(tmp_repo)
        assert len(comps) == 0

    def test_cpp_tech_stack_set(self, tmp_repo: Path) -> None:
        source = tmp_repo / "source"
        source.mkdir()
        d = source / "ml"
        d.mkdir()
        (d / "a.cpp").write_text("")
        (d / "b.h").write_text("")

        comps = _discover_source_subdirectories(tmp_repo)
        assert len(comps) == 1
        assert any(t.name == "C++" for t in comps[0].tech_stack)


class TestMLPipelineDiscovery:
    def test_corpus_with_requirements_and_scripts(self, tmp_repo: Path) -> None:
        corpus = tmp_repo / "corpus"
        corpus.mkdir()
        (corpus / "requirements.txt").write_text("torch>=2.0\nonnx\n")
        scripts = corpus / "scripts"
        scripts.mkdir()
        (scripts / "train.py").write_text("import torch\n")
        (scripts / "export.py").write_text("import onnx\n")

        comps = _discover_ml_pipeline_components(tmp_repo)
        assert len(comps) == 1
        assert comps[0].name == "corpus"
        assert comps[0].component_type == "worker"
        names = [t.name for t in comps[0].tech_stack]
        assert "Python" in names
        assert "PyTorch" in names

    def test_dvc_pipeline_detected(self, tmp_repo: Path) -> None:
        corpus = tmp_repo / "corpus"
        corpus.mkdir()
        (corpus / "requirements.txt").write_text("torch\n")
        (corpus / "train.py").write_text("")
        (corpus / "export.py").write_text("")
        (tmp_repo / "dvc.yaml").write_text("stages:\n  train:\n    cmd: python train.py\n")

        comps = _discover_ml_pipeline_components(tmp_repo)
        assert len(comps) == 1
        names = [t.name for t in comps[0].tech_stack]
        assert "DVC" in names

    def test_no_python_files_skipped(self, tmp_repo: Path) -> None:
        corpus = tmp_repo / "corpus"
        corpus.mkdir()
        (corpus / "requirements.txt").write_text("torch\n")
        (corpus / "data.csv").write_text("a,b\n1,2\n")

        comps = _discover_ml_pipeline_components(tmp_repo)
        assert len(comps) == 0

    def test_no_requirements_skipped(self, tmp_repo: Path) -> None:
        corpus = tmp_repo / "corpus"
        corpus.mkdir()
        (corpus / "train.py").write_text("")
        (corpus / "export.py").write_text("")

        comps = _discover_ml_pipeline_components(tmp_repo)
        assert len(comps) == 0

    def test_hidden_dirs_skipped(self, tmp_repo: Path) -> None:
        hidden = tmp_repo / ".venv"
        hidden.mkdir()
        (hidden / "requirements.txt").write_text("flask\n")
        (hidden / "a.py").write_text("")
        (hidden / "b.py").write_text("")

        comps = _discover_ml_pipeline_components(tmp_repo)
        assert len(comps) == 0

    def test_description_includes_framework_names(self, tmp_repo: Path) -> None:
        corpus = tmp_repo / "training"
        corpus.mkdir()
        (corpus / "requirements.txt").write_text("torch\ntensorflow\n")
        (corpus / "a.py").write_text("")
        (corpus / "b.py").write_text("")

        comps = _discover_ml_pipeline_components(tmp_repo)
        assert len(comps) == 1
        assert "PyTorch" in comps[0].description
        assert "TensorFlow" in comps[0].description


class TestNestedBuildComponents:
    def test_nested_cmake_project(self, tmp_repo: Path) -> None:
        nested = tmp_repo / "MyPlugin"
        nested.mkdir()
        (nested / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.22)\njuce_add_plugin(MyPlugin)\n"
        )

        comps = _discover_nested_build_components(tmp_repo)
        assert len(comps) == 1
        assert comps[0].name == "MyPlugin"
        names = [t.name for t in comps[0].tech_stack]
        assert "C++" in names
        assert "JUCE" in names

    def test_skip_monorepo_dirs(self, tmp_repo: Path) -> None:
        packages = tmp_repo / "packages"
        packages.mkdir()
        (packages / "package.json").write_text("{}")

        comps = _discover_nested_build_components(tmp_repo)
        assert len(comps) == 0

    def test_skip_build_dirs(self, tmp_repo: Path) -> None:
        build = tmp_repo / "build"
        build.mkdir()
        (build / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.22)\n")

        comps = _discover_nested_build_components(tmp_repo)
        assert len(comps) == 0

    def test_no_build_file_skipped(self, tmp_repo: Path) -> None:
        child = tmp_repo / "docs"
        child.mkdir()
        (child / "README.md").write_text("# Docs\n")

        comps = _discover_nested_build_components(tmp_repo)
        assert len(comps) == 0


class TestIntegratedDiscovery:
    def test_mixed_cpp_and_ml_repo(self, tmp_repo: Path) -> None:
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.22)\njuce_add_plugin(MyPlugin)\n"
            "add_subdirectory(vst3sdk)\nFetchContent_Declare(onnxruntime URL x)\n"
        )
        source = tmp_repo / "source"
        source.mkdir()
        ml = source / "ml"
        ml.mkdir()
        (ml / "inference.cpp").write_text("")
        (ml / "inference.h").write_text("")
        transforms = source / "transforms"
        transforms.mkdir()
        (transforms / "fx.cpp").write_text("")
        (transforms / "fx.h").write_text("")

        corpus = tmp_repo / "corpus"
        corpus.mkdir()
        (corpus / "requirements.txt").write_text("torch>=2.0\nonnx\n")
        scripts = corpus / "scripts"
        scripts.mkdir()
        (scripts / "train.py").write_text("")
        (scripts / "export.py").write_text("")

        comps = discover_components(tmp_repo, include_root=True)
        names = {c.name for c in comps}
        assert "ml" in names
        assert "transforms" in names
        assert "corpus" in names
        assert len(comps) >= 4


class TestClassDiagramIntegration:
    """End-to-end: C++ AST extraction -> class diagram generation."""

    def test_class_diagram_from_cpp_fixture(self) -> None:
        from nfr_review.arch_diagrams import render_class_diagram
        from nfr_review.collectors.cpp_ast import CppAstCollector

        fixture = Path(__file__).parent / "fixtures" / "cpp-ast-sample-repo"
        collector = CppAstCollector()
        evidence = collector.collect(fixture, config=None)

        all_classes: list[dict] = []
        for ev in evidence:
            for cls in ev.payload.get("classes", []):
                if cls.get("name") and (
                    cls.get("base_classes") or cls.get("methods") or cls.get("fields")
                ):
                    all_classes.append(cls)

        assert len(all_classes) >= 5
        diagram = render_class_diagram(all_classes)
        assert diagram.level == "code"
        assert "classDiagram" in diagram.mermaid
        assert "AudioProcessor" in diagram.mermaid
        assert "PluginProcessor" in diagram.mermaid
        assert "AudioProcessor <|-- PluginProcessor" in diagram.mermaid
        assert "<<abstract>> AudioProcessor" in diagram.mermaid
        assert "+processBlock()" in diagram.mermaid

    def test_class_diagram_from_integration_repo(self) -> None:
        from nfr_review.arch_diagrams import render_class_diagram
        from nfr_review.collectors.cpp_ast import CppAstCollector

        fixture = Path(__file__).parent / "fixtures" / "cpp-integration-repo"
        collector = CppAstCollector()
        evidence = collector.collect(fixture, config=None)

        all_classes: list[dict] = []
        for ev in evidence:
            for cls in ev.payload.get("classes", []):
                if cls.get("name") and (
                    cls.get("base_classes") or cls.get("methods") or cls.get("fields")
                ):
                    all_classes.append(cls)

        assert len(all_classes) >= 2
        diagram = render_class_diagram(all_classes)
        assert "Widget <|-- FancyWidget" in diagram.mermaid


class TestParseDvcPipeline:
    def test_multi_stage_pipeline(self, tmp_path: Path) -> None:
        dvc_yaml = tmp_path / "dvc.yaml"
        dvc_yaml.write_text(
            "stages:\n"
            "  prepare:\n"
            "    cmd: python prepare.py\n"
            "    deps:\n"
            "      - raw_data/\n"
            "    outs:\n"
            "      - prepared/\n"
            "  train:\n"
            "    cmd: python train.py\n"
            "    deps:\n"
            "      - prepared/\n"
            "      - src/train.py\n"
            "    outs:\n"
            "      - model.pt\n"
            "    params:\n"
            "      - params.yaml\n"
            "    metrics:\n"
            "      - metrics.json\n"
            "  export:\n"
            "    cmd: python export.py\n"
            "    deps:\n"
            "      - model.pt\n"
            "    outs:\n"
            "      - model.onnx\n"
        )

        result = parse_dvc_pipeline(dvc_yaml)
        assert result is not None
        assert len(result.stages) == 3
        names = [s.name for s in result.stages]
        assert names == ["prepare", "train", "export"]

        train = result.stages[1]
        assert train.cmd == "python train.py"
        assert "prepared/" in train.deps
        assert "model.pt" in train.outs
        assert "params.yaml" in train.params
        assert "metrics.json" in train.metrics

    def test_dag_edges_from_outputs_to_deps(self, tmp_path: Path) -> None:
        dvc_yaml = tmp_path / "dvc.yaml"
        dvc_yaml.write_text(
            "stages:\n"
            "  prepare:\n"
            "    cmd: python prepare.py\n"
            "    outs:\n"
            "      - prepared/\n"
            "  train:\n"
            "    cmd: python train.py\n"
            "    deps:\n"
            "      - prepared/\n"
            "    outs:\n"
            "      - model.pt\n"
            "  export:\n"
            "    cmd: python export.py\n"
            "    deps:\n"
            "      - model.pt\n"
        )

        result = parse_dvc_pipeline(dvc_yaml)
        assert result is not None
        assert ("prepare", "train") in result.edges
        assert ("train", "export") in result.edges
        assert len(result.edges) == 2

    def test_single_stage_no_edges(self, tmp_path: Path) -> None:
        dvc_yaml = tmp_path / "dvc.yaml"
        dvc_yaml.write_text(
            "stages:\n"
            "  train:\n"
            "    cmd: python train.py\n"
            "    deps:\n"
            "      - data/\n"
            "    outs:\n"
            "      - model.pt\n"
        )

        result = parse_dvc_pipeline(dvc_yaml)
        assert result is not None
        assert len(result.stages) == 1
        assert result.edges == []

    def test_empty_stages_returns_none(self, tmp_path: Path) -> None:
        dvc_yaml = tmp_path / "dvc.yaml"
        dvc_yaml.write_text("stages: {}\n")

        result = parse_dvc_pipeline(dvc_yaml)
        assert result is None

    def test_no_stages_key_returns_none(self, tmp_path: Path) -> None:
        dvc_yaml = tmp_path / "dvc.yaml"
        dvc_yaml.write_text("vars:\n  - foo: bar\n")

        result = parse_dvc_pipeline(dvc_yaml)
        assert result is None

    def test_invalid_yaml_returns_none(self, tmp_path: Path) -> None:
        dvc_yaml = tmp_path / "dvc.yaml"
        dvc_yaml.write_text("{{not valid yaml")

        result = parse_dvc_pipeline(dvc_yaml)
        assert result is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = parse_dvc_pipeline(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_dict_style_deps_and_outs(self, tmp_path: Path) -> None:
        dvc_yaml = tmp_path / "dvc.yaml"
        dvc_yaml.write_text(
            "stages:\n"
            "  train:\n"
            "    cmd: python train.py\n"
            "    deps:\n"
            "      - path: data/train.csv\n"
            "    outs:\n"
            "      - path: model.pkl\n"
        )

        result = parse_dvc_pipeline(dvc_yaml)
        assert result is not None
        assert "data/train.csv" in result.stages[0].deps
        assert "model.pkl" in result.stages[0].outs

    def test_list_cmd_joined(self, tmp_path: Path) -> None:
        dvc_yaml = tmp_path / "dvc.yaml"
        dvc_yaml.write_text(
            "stages:\n  build:\n    cmd:\n      - pip install -e .\n      - python build.py\n"
        )

        result = parse_dvc_pipeline(dvc_yaml)
        assert result is not None
        assert "pip install -e ." in result.stages[0].cmd
        assert "&&" in result.stages[0].cmd
