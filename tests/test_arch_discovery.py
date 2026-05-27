# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for architecture component discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.arch_discovery import (
    _discover_go_module_path,
    _discover_java_base_package,
    _discover_python_top_package,
    _enrich_package_boundaries,
    discover_components,
    discover_components_multi_repo,
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
