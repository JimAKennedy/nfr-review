# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for manifest-based cross-repo dependency detection."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from nfr_review.arch_integ_manifest import (
    discover_manifest_cross_repo_integrations,
    extract_dotnet_deps,
    extract_go_deps,
    extract_gradle_deps,
    extract_maven_deps,
    extract_npm_deps,
    extract_python_deps,
    extract_rust_deps,
)
from nfr_review.arch_models import Component, ComponentBoundary

# ---------------------------------------------------------------------------
# Extractor unit tests
# ---------------------------------------------------------------------------


class TestExtractMavenDeps:
    def test_basic_dependency(self):
        pom = textwrap.dedent("""\
            <project>
              <dependencies>
                <dependency>
                  <groupId>org.springframework.boot</groupId>
                  <artifactId>spring-boot-starter-web</artifactId>
                  <version>3.2.0</version>
                </dependency>
              </dependencies>
            </project>
        """)
        deps = extract_maven_deps(pom)
        assert ("org.springframework.boot:spring-boot-starter-web", "3.2.0") in deps

    def test_dependency_without_version(self):
        pom = textwrap.dedent("""\
            <project>
              <dependencies>
                <dependency>
                  <groupId>com.example</groupId>
                  <artifactId>shared-lib</artifactId>
                </dependency>
              </dependencies>
            </project>
        """)
        deps = extract_maven_deps(pom)
        assert ("com.example:shared-lib", "") in deps

    def test_parent_pom(self):
        pom = textwrap.dedent("""\
            <project>
              <parent>
                <groupId>com.example</groupId>
                <artifactId>parent-pom</artifactId>
                <version>1.0.0</version>
              </parent>
            </project>
        """)
        deps = extract_maven_deps(pom)
        assert ("com.example:parent-pom", "1.0.0") in deps

    def test_module_refs(self):
        pom = textwrap.dedent("""\
            <project>
              <modules>
                <module>service-a</module>
                <module>service-b</module>
              </modules>
            </project>
        """)
        deps = extract_maven_deps(pom)
        assert ("service-a", "") in deps
        assert ("service-b", "") in deps

    def test_multiple_deps(self):
        pom = textwrap.dedent("""\
            <project>
              <dependencies>
                <dependency>
                  <groupId>com.example</groupId>
                  <artifactId>lib-a</artifactId>
                  <version>1.0</version>
                </dependency>
                <dependency>
                  <groupId>com.example</groupId>
                  <artifactId>lib-b</artifactId>
                  <version>2.0</version>
                </dependency>
              </dependencies>
            </project>
        """)
        deps = extract_maven_deps(pom)
        assert len(deps) == 2


class TestExtractGradleDeps:
    def test_basic_implementation(self):
        gradle = "implementation 'org.springframework:spring-core:5.3.0'"
        deps = extract_gradle_deps(gradle)
        assert ("org.springframework:spring-core", "5.3.0") in deps

    def test_kotlin_dsl(self):
        gradle = 'implementation("com.google.guava:guava:31.1-jre")'
        deps = extract_gradle_deps(gradle)
        assert ("com.google.guava:guava", "31.1-jre") in deps

    def test_various_configurations(self):
        gradle = textwrap.dedent("""\
            api 'com.example:api-lib:1.0'
            compileOnly 'com.example:compile-lib:2.0'
            runtimeOnly 'com.example:runtime-lib:3.0'
            testImplementation 'com.example:test-lib:4.0'
        """)
        deps = extract_gradle_deps(gradle)
        assert len(deps) == 4

    def test_no_version(self):
        gradle = "implementation 'com.example:lib'"
        deps = extract_gradle_deps(gradle)
        assert deps == [("com.example:lib", "")]


class TestExtractNpmDeps:
    def test_dependencies(self):
        pkg = json.dumps(
            {
                "dependencies": {"express": "^4.18.0", "lodash": "~4.17.21"},
            }
        )
        deps = extract_npm_deps(pkg)
        assert ("express", "^4.18.0") in deps
        assert ("lodash", "~4.17.21") in deps

    def test_dev_dependencies(self):
        pkg = json.dumps(
            {
                "devDependencies": {"jest": "^29.0.0"},
            }
        )
        deps = extract_npm_deps(pkg)
        assert ("jest", "^29.0.0") in deps

    def test_peer_dependencies(self):
        pkg = json.dumps(
            {
                "peerDependencies": {"react": ">=18.0.0"},
            }
        )
        deps = extract_npm_deps(pkg)
        assert ("react", ">=18.0.0") in deps

    def test_invalid_json(self):
        assert extract_npm_deps("not json") == []

    def test_empty_sections(self):
        pkg = json.dumps({"name": "test", "version": "1.0.0"})
        assert extract_npm_deps(pkg) == []


class TestExtractPythonDeps:
    def test_requirements_txt(self):
        reqs = textwrap.dedent("""\
            flask>=2.0.0
            requests==2.28.0
            pydantic[email]>=2.0
            # a comment
            -e git+https://example.com/repo.git
        """)
        deps = extract_python_deps(reqs, "requirements.txt")
        assert ("flask", ">=2.0.0") in deps
        assert ("requests", "==2.28.0") in deps
        assert ("pydantic", ">=2.0") in deps
        assert len(deps) == 3

    def test_pyproject_toml(self):
        toml = textwrap.dedent("""\
            [project]
            name = "myapp"
            dependencies = [
                "click>=8.1",
                "pydantic>=2.0",
            ]
        """)
        deps = extract_python_deps(toml, "pyproject.toml")
        assert ("click", ">=8.1") in deps
        assert ("pydantic", ">=2.0") in deps

    def test_name_normalization(self):
        reqs = "my_package.name>=1.0\nAnother-Package>=2.0"
        deps = extract_python_deps(reqs, "requirements.txt")
        names = [d[0] for d in deps]
        assert "my-package-name" in names
        assert "another-package" in names


class TestExtractGoDeps:
    def test_require_block(self):
        gomod = textwrap.dedent("""\
            module github.com/example/myapp

            go 1.21

            require (
                github.com/gin-gonic/gin v1.9.0
                github.com/lib/pq v1.10.9
            )
        """)
        deps = extract_go_deps(gomod)
        assert ("github.com/gin-gonic/gin", "v1.9.0") in deps
        assert ("github.com/lib/pq", "v1.10.9") in deps

    def test_single_require(self):
        gomod = textwrap.dedent("""\
            module github.com/example/tool

            require github.com/spf13/cobra v1.7.0
        """)
        deps = extract_go_deps(gomod)
        assert any(d[0] == "github.com/spf13/cobra" for d in deps)


class TestExtractRustDeps:
    def test_simple_version(self):
        cargo = textwrap.dedent("""\
            [package]
            name = "myapp"
            version = "0.1.0"

            [dependencies]
            serde = "1.0"
            tokio = { version = "1.28", features = ["full"] }

            [dev-dependencies]
            criterion = "0.5"
        """)
        deps = extract_rust_deps(cargo)
        assert ("serde", "1.0") in deps
        assert ("tokio", "1.28") in deps
        assert ("criterion", "0.5") in deps

    def test_no_deps_section(self):
        cargo = textwrap.dedent("""\
            [package]
            name = "mylib"
            version = "0.1.0"
        """)
        assert extract_rust_deps(cargo) == []


class TestExtractDotnetDeps:
    def test_package_references(self):
        csproj = textwrap.dedent("""\
            <Project Sdk="Microsoft.NET.Sdk.Web">
              <ItemGroup>
                <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
                <PackageReference Include="Serilog" Version="3.1.1" />
              </ItemGroup>
            </Project>
        """)
        deps = extract_dotnet_deps(csproj)
        assert ("Newtonsoft.Json", "13.0.3") in deps
        assert ("Serilog", "3.1.1") in deps

    def test_project_references(self):
        csproj = textwrap.dedent("""\
            <Project Sdk="Microsoft.NET.Sdk">
              <ItemGroup>
                <ProjectReference Include="..\\SharedLib\\SharedLib.csproj" />
              </ItemGroup>
            </Project>
        """)
        deps = extract_dotnet_deps(csproj)
        assert ("SharedLib", "") in deps

    def test_mixed_references(self):
        csproj = textwrap.dedent("""\
            <Project>
              <ItemGroup>
                <PackageReference Include="MediatR" Version="12.0.0" />
                <ProjectReference Include="..\\Core\\Core.csproj" />
              </ItemGroup>
            </Project>
        """)
        deps = extract_dotnet_deps(csproj)
        assert len(deps) == 2


# ---------------------------------------------------------------------------
# Strategy integration tests
# ---------------------------------------------------------------------------


def _make_component(
    name: str,
    repo: str | None = None,
    boundary_path: str = ".",
) -> Component:
    return Component(
        id=f"comp-{name.lower()}",
        name=name,
        description=f"Test component {name}",
        component_type="service",
        boundaries=[ComponentBoundary(boundary_type="directory", path=boundary_path)],
        repo=repo,
    )


class TestManifestCrossRepoStrategy:
    def test_npm_cross_repo_match(self, tmp_path: Path):
        """Two repos sharing an npm dependency should produce an IntegrationPoint."""
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        (repo_a / "package.json").write_text(
            json.dumps({"dependencies": {"shared-lib": "^1.0.0"}})
        )

        comp_a = _make_component("repo-a", repo="repo-a")
        comp_b = _make_component("shared-lib", repo="shared-lib")

        result = discover_manifest_cross_repo_integrations(repo_a, [comp_a, comp_b], "repo-a")
        assert len(result) == 1
        assert result[0].source_component_id == "comp-repo-a"
        assert result[0].target_component_id == "comp-shared-lib"
        assert result[0].style == "build_dependency"
        assert "manifest" in result[0].protocol

    def test_maven_cross_repo_match(self, tmp_path: Path):
        """Maven artifactId matching a component name produces an edge."""
        repo = tmp_path / "consumer"
        repo.mkdir()
        (repo / "pom.xml").write_text(
            textwrap.dedent("""\
            <project>
              <dependencies>
                <dependency>
                  <groupId>com.example</groupId>
                  <artifactId>payment-service</artifactId>
                  <version>1.0.0</version>
                </dependency>
              </dependencies>
            </project>
        """)
        )

        consumer = _make_component("consumer", repo="consumer")
        provider = _make_component("payment-service", repo="payment-service")

        result = discover_manifest_cross_repo_integrations(
            repo, [consumer, provider], "consumer"
        )
        assert len(result) == 1
        assert result[0].target_component_id == "comp-payment-service"

    def test_go_module_path_match(self, tmp_path: Path):
        """Go module path's last segment matching a component name."""
        repo = tmp_path / "api"
        repo.mkdir()
        (repo / "go.mod").write_text(
            textwrap.dedent("""\
            module github.com/org/api

            go 1.21

            require (
                github.com/org/shared-utils v0.5.0
            )
        """)
        )

        api = _make_component("api", repo="api")
        utils = _make_component("shared-utils", repo="shared-utils")

        result = discover_manifest_cross_repo_integrations(repo, [api, utils], "api")
        assert len(result) == 1
        assert result[0].target_component_id == "comp-shared-utils"

    def test_python_cross_repo_match(self, tmp_path: Path):
        """Python requirement matching a component name."""
        repo = tmp_path / "webapp"
        repo.mkdir()
        (repo / "requirements.txt").write_text("auth-service>=1.0\nflask>=2.0\n")

        webapp = _make_component("webapp", repo="webapp")
        auth = _make_component("auth-service", repo="auth-service")

        result = discover_manifest_cross_repo_integrations(repo, [webapp, auth], "webapp")
        assert len(result) == 1
        assert result[0].target_component_id == "comp-auth-service"

    def test_no_match_external_deps(self, tmp_path: Path):
        """Third-party deps that don't match any component produce no edges."""
        repo = tmp_path / "app"
        repo.mkdir()
        (repo / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^4.18.0", "lodash": "~4.17.21"}})
        )

        comp = _make_component("app", repo="app")
        result = discover_manifest_cross_repo_integrations(repo, [comp], "app")
        assert result == []

    def test_self_reference_excluded(self, tmp_path: Path):
        """A component referencing its own name should not produce an edge."""
        repo = tmp_path / "mylib"
        repo.mkdir()
        (repo / "package.json").write_text(json.dumps({"dependencies": {"mylib": "^1.0.0"}}))

        comp = _make_component("mylib", repo="mylib")
        result = discover_manifest_cross_repo_integrations(repo, [comp], "mylib")
        assert result == []

    def test_dedup_same_edge(self, tmp_path: Path):
        """Same dependency declared in two manifests produces one edge."""
        repo = tmp_path / "app"
        repo.mkdir()
        (repo / "package.json").write_text(
            json.dumps({"dependencies": {"core-lib": "^1.0.0"}})
        )
        (repo / "requirements.txt").write_text("core-lib>=1.0\n")

        app = _make_component("app", repo="app")
        core = _make_component("core-lib", repo="core-lib")

        result = discover_manifest_cross_repo_integrations(repo, [app, core], "app")
        assert len(result) == 1

    def test_malformed_manifest_returns_empty(self, tmp_path: Path):
        """Malformed manifest files should not raise."""
        repo = tmp_path / "broken"
        repo.mkdir()
        (repo / "package.json").write_text("{invalid json")

        comp = _make_component("broken", repo="broken")
        result = discover_manifest_cross_repo_integrations(repo, [comp], "broken")
        assert result == []

    def test_dotnet_project_reference_match(self, tmp_path: Path):
        """ProjectReference in .csproj matching a component."""
        repo = tmp_path / "webapi"
        repo.mkdir()
        (repo / "WebApi.csproj").write_text(
            textwrap.dedent("""\
            <Project Sdk="Microsoft.NET.Sdk.Web">
              <ItemGroup>
                <ProjectReference Include="..\\SharedLib\\SharedLib.csproj" />
              </ItemGroup>
            </Project>
        """)
        )

        webapi = _make_component("webapi", repo="webapi")
        shared = _make_component("SharedLib", repo="shared-lib")

        result = discover_manifest_cross_repo_integrations(repo, [webapi, shared], "webapi")
        assert len(result) == 1
        assert result[0].target_component_id == "comp-sharedlib"

    def test_rust_cross_repo_match(self, tmp_path: Path):
        """Rust crate matching a component name."""
        repo = tmp_path / "cli"
        repo.mkdir()
        (repo / "Cargo.toml").write_text(
            textwrap.dedent("""\
            [package]
            name = "cli"
            version = "0.1.0"

            [dependencies]
            core-engine = "0.5.0"
        """)
        )

        cli = _make_component("cli", repo="cli")
        engine = _make_component("core-engine", repo="core-engine")

        result = discover_manifest_cross_repo_integrations(repo, [cli, engine], "cli")
        assert len(result) == 1
        assert result[0].target_component_id == "comp-core-engine"


class TestStrategyRegistration:
    def test_manifest_strategy_in_registry(self):
        """The manifest strategy should be registered in arch_integrations."""
        from nfr_review.arch_integrations import _STRATEGIES

        names = [name for name, _ in _STRATEGIES]
        assert "manifest-cross-repo" in names
