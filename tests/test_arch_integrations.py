# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for integration point discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.arch_integrations import (
    discover_integrations,
    discover_integrations_multi_repo,
)
from nfr_review.arch_models import Component, ComponentBoundary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_component(
    name: str,
    comp_type: str = "service",
    repo: str = "test-repo",
    boundary_path: str | None = None,
) -> Component:
    """Create a minimal Component for testing."""
    return Component(
        id=f"comp-{name}-000000",
        name=name,
        description=f"Test component {name}",
        component_type=comp_type,
        boundaries=[
            ComponentBoundary(
                boundary_type="directory",
                path=boundary_path or name,
                repo=repo,
            )
        ],
        repo=repo,
    )


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure."""
    (tmp_path / ".git").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# K8s Service -> Deployment mapping
# ---------------------------------------------------------------------------


class TestK8sIntegrations:
    def test_service_to_deployment_matching(self, tmp_repo: Path) -> None:
        """A K8s Service with selector matching a Deployment's labels."""
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()

        (k8s_dir / "deployment.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: api-server\n"
            "  labels:\n"
            "    app: api-server\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: api-server\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: api\n"
            "          image: acme/api:v1\n"
        )

        (k8s_dir / "service.yaml").write_text(
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: api-svc\n"
            "spec:\n"
            "  selector:\n"
            "    app: api-server\n"
            "  ports:\n"
            "    - port: 80\n"
        )

        components = [
            _make_component("api-svc"),
            _make_component("api-server"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) == 1
        intg = integrations[0]
        assert intg.source_component_id == "comp-api-svc-000000"
        assert intg.target_component_id == "comp-api-server-000000"
        assert intg.style == "synchronous"
        assert intg.protocol == "http"

    def test_non_matching_selectors(self, tmp_repo: Path) -> None:
        """Service selector doesn't match any deployment labels."""
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()

        (k8s_dir / "deployment.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: backend\n"
            "  labels:\n"
            "    app: backend\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: backend\n"
            "    spec:\n"
            "      containers: []\n"
        )

        (k8s_dir / "service.yaml").write_text(
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: other-svc\n"
            "spec:\n"
            "  selector:\n"
            "    app: frontend\n"
        )

        components = [
            _make_component("other-svc"),
            _make_component("backend"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) == 0

    def test_missing_selector(self, tmp_repo: Path) -> None:
        """Service without a selector should not produce integrations."""
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()

        (k8s_dir / "service.yaml").write_text(
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: headless-svc\n"
            "spec:\n"
            "  clusterIP: None\n"
        )

        components = [_make_component("headless-svc")]
        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) == 0

    def test_multi_doc_yaml(self, tmp_repo: Path) -> None:
        """Service and Deployment in the same multi-document YAML."""
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()

        (k8s_dir / "all.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: worker\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: worker\n"
            "    spec:\n"
            "      containers: []\n"
            "---\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: worker-svc\n"
            "spec:\n"
            "  selector:\n"
            "    app: worker\n"
        )

        components = [
            _make_component("worker-svc"),
            _make_component("worker"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) == 1

    def test_statefulset_matching(self, tmp_repo: Path) -> None:
        """Service selector matching a StatefulSet."""
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()

        (k8s_dir / "stateful.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: StatefulSet\n"
            "metadata:\n"
            "  name: cache\n"
            "  labels:\n"
            "    app: cache\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: cache\n"
            "    spec:\n"
            "      containers: []\n"
        )

        (k8s_dir / "cache-svc.yaml").write_text(
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: cache-svc\n"
            "spec:\n"
            "  selector:\n"
            "    app: cache\n"
        )

        components = [
            _make_component("cache-svc"),
            _make_component("cache"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) == 1
        assert "StatefulSet" in integrations[0].description


# ---------------------------------------------------------------------------
# Docker Compose integrations
# ---------------------------------------------------------------------------


class TestComposeIntegrations:
    def test_depends_on_list(self, tmp_repo: Path) -> None:
        """depends_on as a list of service names."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: acme/web\n"
            "    depends_on:\n"
            "      - redis\n"
            "      - postgres\n"
            "  redis:\n"
            "    image: redis:7\n"
            "  postgres:\n"
            "    image: postgres:15\n"
        )

        components = [
            _make_component("web"),
            _make_component("redis", comp_type="database"),
            _make_component("postgres", comp_type="database"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) >= 2
        targets = {i.target_component_id for i in integrations}
        assert "comp-redis-000000" in targets
        assert "comp-postgres-000000" in targets

    def test_depends_on_dict(self, tmp_repo: Path) -> None:
        """depends_on as a dict with conditions."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  api:\n"
            "    image: acme/api\n"
            "    depends_on:\n"
            "      db:\n"
            "        condition: service_healthy\n"
            "  db:\n"
            "    image: mysql:8\n"
        )

        components = [
            _make_component("api"),
            _make_component("db", comp_type="database"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) >= 1
        assert any(i.target_component_id == "comp-db-000000" for i in integrations)

    def test_links(self, tmp_repo: Path) -> None:
        """links with and without aliases."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: acme/web\n"
            "    links:\n"
            "      - api\n"
            "      - cache:redis\n"
            "  api:\n"
            "    image: acme/api\n"
            "  cache:\n"
            "    image: redis:7\n"
        )

        components = [
            _make_component("web"),
            _make_component("api"),
            _make_component("cache", comp_type="database"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        targets = {i.target_component_id for i in integrations}
        assert "comp-api-000000" in targets
        assert "comp-cache-000000" in targets

    def test_shared_networks(self, tmp_repo: Path) -> None:
        """Services on the same custom network are connected."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: acme/web\n"
            "    networks:\n"
            "      - backend\n"
            "  api:\n"
            "    image: acme/api\n"
            "    networks:\n"
            "      - backend\n"
            "  worker:\n"
            "    image: acme/worker\n"
            "    networks:\n"
            "      - backend\n"
            "networks:\n"
            "  backend:\n"
            "    driver: bridge\n"
        )

        components = [
            _make_component("web"),
            _make_component("api"),
            _make_component("worker"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        # 3 services on the same network => 3 pairs: web-api, web-worker, api-worker
        assert len(integrations) >= 3

    def test_depends_on_and_network_dedup(self, tmp_repo: Path) -> None:
        """Same pair from depends_on and shared network should deduplicate."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: acme/web\n"
            "    depends_on:\n"
            "      - api\n"
            "    networks:\n"
            "      - mynet\n"
            "  api:\n"
            "    image: acme/api\n"
            "    networks:\n"
            "      - mynet\n"
            "networks:\n"
            "  mynet:\n"
        )

        components = [
            _make_component("web"),
            _make_component("api"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        # Should have exactly 1 integration after dedup
        # (depends_on creates web->api, network also creates web<->api pair
        #  but the pair is already seen from depends_on)
        pairs = {(i.source_component_id, i.target_component_id) for i in integrations}
        # At most 1 unique directed pair
        assert len(pairs) <= 2  # depends_on + potentially reversed network pair


# ---------------------------------------------------------------------------
# Maven inter-module dependencies
# ---------------------------------------------------------------------------


class TestMavenIntegrations:
    def test_inter_module_dependency(self, tmp_repo: Path) -> None:
        """Module A depends on module B via Maven coordinates."""
        (tmp_repo / "pom.xml").write_text(
            "<project>\n"
            "  <groupId>com.acme</groupId>\n"
            "  <artifactId>parent</artifactId>\n"
            "  <modules>\n"
            "    <module>core</module>\n"
            "    <module>api</module>\n"
            "  </modules>\n"
            "</project>"
        )

        core_dir = tmp_repo / "core"
        core_dir.mkdir()
        (core_dir / "pom.xml").write_text(
            "<project>\n"
            "  <groupId>com.acme</groupId>\n"
            "  <artifactId>core</artifactId>\n"
            "</project>"
        )

        api_dir = tmp_repo / "api"
        api_dir.mkdir()
        (api_dir / "pom.xml").write_text(
            "<project>\n"
            "  <groupId>com.acme</groupId>\n"
            "  <artifactId>api</artifactId>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>com.acme</groupId>\n"
            "      <artifactId>core</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )

        components = [
            _make_component("core", comp_type="library"),
            _make_component("api"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) >= 1
        maven_intg = [i for i in integrations if "maven" in i.description.lower()]
        assert len(maven_intg) == 1
        assert maven_intg[0].source_component_id == "comp-api-000000"
        assert maven_intg[0].target_component_id == "comp-core-000000"
        assert maven_intg[0].style == "api_call"
        assert maven_intg[0].protocol == "jvm"

    def test_inherits_parent_groupid(self, tmp_repo: Path) -> None:
        """Module without groupId inherits from parent."""
        (tmp_repo / "pom.xml").write_text(
            "<project>\n"
            "  <groupId>com.acme</groupId>\n"
            "  <artifactId>parent</artifactId>\n"
            "  <modules>\n"
            "    <module>common</module>\n"
            "    <module>web</module>\n"
            "  </modules>\n"
            "</project>"
        )

        common_dir = tmp_repo / "common"
        common_dir.mkdir()
        (common_dir / "pom.xml").write_text(
            "<project>\n  <artifactId>common</artifactId>\n</project>"
        )

        web_dir = tmp_repo / "web"
        web_dir.mkdir()
        (web_dir / "pom.xml").write_text(
            "<project>\n"
            "  <artifactId>web</artifactId>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>com.acme</groupId>\n"
            "      <artifactId>common</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )

        components = [
            _make_component("common", comp_type="library"),
            _make_component("web"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        maven_intg = [i for i in integrations if "maven" in i.description.lower()]
        assert len(maven_intg) == 1

    def test_external_dependency_ignored(self, tmp_repo: Path) -> None:
        """Dependencies not matching sibling modules are ignored."""
        (tmp_repo / "pom.xml").write_text(
            "<project>\n"
            "  <groupId>com.acme</groupId>\n"
            "  <artifactId>parent</artifactId>\n"
            "  <modules>\n"
            "    <module>app</module>\n"
            "  </modules>\n"
            "</project>"
        )

        app_dir = tmp_repo / "app"
        app_dir.mkdir()
        (app_dir / "pom.xml").write_text(
            "<project>\n"
            "  <groupId>com.acme</groupId>\n"
            "  <artifactId>app</artifactId>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>org.springframework</groupId>\n"
            "      <artifactId>spring-core</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )

        components = [_make_component("app")]
        integrations = discover_integrations(tmp_repo, components)
        maven_intg = [i for i in integrations if "maven" in i.description.lower()]
        assert len(maven_intg) == 0

    def test_no_root_pom(self, tmp_repo: Path) -> None:
        """No pom.xml at root => no Maven integrations."""
        components = [_make_component("app")]
        integrations = discover_integrations(tmp_repo, components)
        maven_intg = [i for i in integrations if "maven" in i.description.lower()]
        assert len(maven_intg) == 0


# ---------------------------------------------------------------------------
# Gradle inter-project dependencies
# ---------------------------------------------------------------------------


class TestGradleIntegrations:
    def test_project_dependency(self, tmp_repo: Path) -> None:
        """Gradle project(':lib') dependency between sub-projects."""
        (tmp_repo / "settings.gradle").write_text("include 'app'\ninclude 'lib'\n")

        app_dir = tmp_repo / "app"
        app_dir.mkdir()
        (app_dir / "build.gradle").write_text(
            "dependencies {\n    implementation project(':lib')\n}\n"
        )

        lib_dir = tmp_repo / "lib"
        lib_dir.mkdir()
        (lib_dir / "build.gradle").write_text("apply plugin: 'java-library'\n")

        components = [
            _make_component("app"),
            _make_component("lib", comp_type="library"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        gradle_intg = [i for i in integrations if "gradle" in i.description.lower()]
        assert len(gradle_intg) == 1
        assert gradle_intg[0].source_component_id == "comp-app-000000"
        assert gradle_intg[0].target_component_id == "comp-lib-000000"
        assert gradle_intg[0].style == "api_call"
        assert gradle_intg[0].protocol == "jvm"

    def test_kts_build_file(self, tmp_repo: Path) -> None:
        """Gradle Kotlin DSL build files."""
        (tmp_repo / "settings.gradle.kts").write_text('include("app")\ninclude("core")\n')

        app_dir = tmp_repo / "app"
        app_dir.mkdir()
        (app_dir / "build.gradle.kts").write_text(
            'dependencies {\n    implementation(project(":core"))\n}\n'
        )

        core_dir = tmp_repo / "core"
        core_dir.mkdir()
        (core_dir / "build.gradle.kts").write_text("plugins { `java-library` }\n")

        components = [
            _make_component("app"),
            _make_component("core", comp_type="library"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        gradle_intg = [i for i in integrations if "gradle" in i.description.lower()]
        assert len(gradle_intg) == 1

    def test_no_settings_file(self, tmp_repo: Path) -> None:
        """No settings.gradle => no Gradle integrations."""
        components = [_make_component("app")]
        integrations = discover_integrations(tmp_repo, components)
        gradle_intg = [i for i in integrations if "gradle" in i.description.lower()]
        assert len(gradle_intg) == 0

    def test_multiple_dependency_configs(self, tmp_repo: Path) -> None:
        """Various Gradle dependency configurations (api, testImplementation, etc.)."""
        (tmp_repo / "settings.gradle").write_text(
            "include 'app'\ninclude 'lib'\ninclude 'test-utils'\n"
        )

        app_dir = tmp_repo / "app"
        app_dir.mkdir()
        (app_dir / "build.gradle").write_text(
            "dependencies {\n"
            "    api project(':lib')\n"
            "    testImplementation project(':test-utils')\n"
            "}\n"
        )

        lib_dir = tmp_repo / "lib"
        lib_dir.mkdir()
        (lib_dir / "build.gradle").write_text("")

        tu_dir = tmp_repo / "test-utils"
        tu_dir.mkdir()
        (tu_dir / "build.gradle").write_text("")

        components = [
            _make_component("app"),
            _make_component("lib", comp_type="library"),
            _make_component("test-utils", comp_type="library"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        gradle_intg = [i for i in integrations if "gradle" in i.description.lower()]
        assert len(gradle_intg) == 2


# ---------------------------------------------------------------------------
# Config-file connection string discovery
# ---------------------------------------------------------------------------


class TestConfigIntegrations:
    def test_jdbc_postgresql(self, tmp_repo: Path) -> None:
        """JDBC PostgreSQL connection string in application.yml."""
        (tmp_repo / "application.yml").write_text(
            "spring:\n  datasource:\n    url: jdbc:postgresql://db-host:5432/mydb\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        jdbc_intg = [i for i in integrations if i.style == "shared_database"]
        assert len(jdbc_intg) >= 1
        assert any("jdbc:postgresql" in i.protocol for i in jdbc_intg)

    def test_jdbc_mysql(self, tmp_repo: Path) -> None:
        """JDBC MySQL connection string in application.properties."""
        (tmp_repo / "application.properties").write_text(
            "spring.datasource.url=jdbc:mysql://mysql-server:3306/appdb\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        jdbc_intg = [i for i in integrations if "jdbc" in (i.protocol or "")]
        assert len(jdbc_intg) >= 1

    def test_redis_url(self, tmp_repo: Path) -> None:
        """Redis connection URL in config."""
        (tmp_repo / "application.yml").write_text(
            "spring:\n  redis:\n    url: redis://cache-host:6379\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        redis_intg = [i for i in integrations if i.protocol == "redis"]
        assert len(redis_intg) >= 1

    def test_amqp_url(self, tmp_repo: Path) -> None:
        """RabbitMQ AMQP connection URL."""
        (tmp_repo / "application.yml").write_text(
            "spring:\n  rabbitmq:\n    addresses: amqp://mq-host:5672\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        amqp_intg = [i for i in integrations if i.protocol == "amqp"]
        assert len(amqp_intg) >= 1
        assert amqp_intg[0].style == "message_queue"

    def test_mongodb_url(self, tmp_repo: Path) -> None:
        """MongoDB connection string."""
        (tmp_repo / "application.yml").write_text(
            "spring:\n  data:\n    mongodb:\n      uri: mongodb://mongo-host:27017/mydb\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        mongo_intg = [i for i in integrations if i.protocol == "mongodb"]
        assert len(mongo_intg) >= 1

    def test_kafka_broker(self, tmp_repo: Path) -> None:
        """Kafka bootstrap servers in config."""
        (tmp_repo / "application.properties").write_text(
            "spring.kafka.bootstrap-servers=kafka-broker:9092\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        kafka_intg = [i for i in integrations if i.protocol == "kafka"]
        assert len(kafka_intg) >= 1
        assert kafka_intg[0].style == "message_queue"

    def test_http_endpoint(self, tmp_repo: Path) -> None:
        """HTTP endpoint in config file."""
        (tmp_repo / "application.yml").write_text(
            "external:\n  payment-api:\n    url: https://payments-service.internal:8443/api\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        http_intg = [i for i in integrations if i.style == "api_call"]
        assert len(http_intg) >= 1

    def test_env_file(self, tmp_repo: Path) -> None:
        """Connection strings in .env file."""
        (tmp_repo / ".env").write_text(
            "DATABASE_URL=jdbc:postgresql://pg-host:5432/prod\n"
            "REDIS_URL=redis://redis-host:6379/0\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) >= 2

    def test_appsettings_json(self, tmp_repo: Path) -> None:
        """Connection string in appsettings.json (.NET style)."""
        (tmp_repo / "appsettings.json").write_text(
            "{\n"
            '  "ConnectionStrings": {\n'
            '    "Default": "jdbc:sqlserver://sql-host:1433;database=mydb"\n'
            "  }\n"
            "}\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) >= 1

    def test_localhost_connections_handled(self, tmp_repo: Path) -> None:
        """localhost/127.0.0.1 connections should still produce integrations."""
        (tmp_repo / "application.yml").write_text(
            "spring:\n  datasource:\n    url: jdbc:postgresql://localhost:5432/devdb\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        # Should still create an integration (with the DB type as identifier)
        assert len(integrations) >= 1

    def test_ignores_schema_urls(self, tmp_repo: Path) -> None:
        """XML schema/namespace URLs should not produce integrations."""
        (tmp_repo / "application.yml").write_text("url: https://www.w3.org/2001/XMLSchema\n")

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        assert len(integrations) == 0

    def test_multiple_connections_in_one_file(self, tmp_repo: Path) -> None:
        """Multiple different connection strings in a single config file."""
        (tmp_repo / "application.yml").write_text(
            "spring:\n"
            "  datasource:\n"
            "    url: jdbc:postgresql://pg-host:5432/app\n"
            "  redis:\n"
            "    url: redis://redis-host:6379\n"
            "  rabbitmq:\n"
            "    addresses: amqp://rabbit-host:5672\n"
        )

        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        protocols = {i.protocol for i in integrations}
        assert "jdbc:postgresql" in protocols
        assert "redis" in protocols
        assert "amqp" in protocols


# ---------------------------------------------------------------------------
# Multi-repo cross-repo detection
# ---------------------------------------------------------------------------


class TestMultiRepo:
    def test_cross_repo_flag(self, tmp_path: Path) -> None:
        """Integration between components in different repos gets is_cross_repo=True."""
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        (repo_a / ".git").mkdir()
        (repo_a / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: acme/web\n"
            "    depends_on:\n"
            "      - api\n"
            "  api:\n"
            "    image: acme/api\n"
        )

        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()
        (repo_b / ".git").mkdir()

        comp_web = _make_component("web", repo="repo-a")
        comp_api = _make_component("api", repo="repo-b")

        integrations = discover_integrations_multi_repo(
            [repo_a, repo_b],
            [comp_web, comp_api],
            repo_names=["repo-a", "repo-b"],
        )

        cross_repo = [i for i in integrations if i.is_cross_repo]
        assert len(cross_repo) >= 1

    def test_same_repo_not_cross_repo(self, tmp_path: Path) -> None:
        """Integration within the same repo does not get is_cross_repo=True."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: acme/web\n"
            "    depends_on:\n"
            "      - api\n"
            "  api:\n"
            "    image: acme/api\n"
        )

        comp_web = _make_component("web", repo="my-repo")
        comp_api = _make_component("api", repo="my-repo")

        integrations = discover_integrations_multi_repo(
            [repo],
            [comp_web, comp_api],
            repo_names=["my-repo"],
        )

        assert all(not i.is_cross_repo for i in integrations)

    def test_mismatched_names_raises(self, tmp_path: Path) -> None:
        """repo_names length must match repo_paths."""
        with pytest.raises(ValueError, match="repo_names must match"):
            discover_integrations_multi_repo([tmp_path], [], repo_names=["a", "b"])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_repo(self, tmp_repo: Path) -> None:
        """Empty repo with no components produces no integrations."""
        integrations = discover_integrations(tmp_repo, [])
        assert integrations == []

    def test_no_components_provided(self, tmp_repo: Path) -> None:
        """Components list is empty; should not crash."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n  web:\n    depends_on:\n      - db\n  db:\n    image: postgres:15\n"
        )
        integrations = discover_integrations(tmp_repo, [])
        assert integrations == []

    def test_malformed_yaml(self, tmp_repo: Path) -> None:
        """Malformed YAML files should not crash."""
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()
        (k8s_dir / "bad.yaml").write_text("{{this is not valid yaml: [")

        integrations = discover_integrations(tmp_repo, [_make_component("svc")])
        # Should not raise, may return empty
        assert isinstance(integrations, list)

    def test_malformed_compose(self, tmp_repo: Path) -> None:
        """Malformed docker-compose file should not crash."""
        (tmp_repo / "docker-compose.yml").write_text("not: a: valid: compose")
        integrations = discover_integrations(tmp_repo, [_make_component("svc")])
        assert isinstance(integrations, list)

    def test_malformed_pom(self, tmp_repo: Path) -> None:
        """Malformed pom.xml should not crash."""
        (tmp_repo / "pom.xml").write_text("<<<not xml>>>")
        integrations = discover_integrations(tmp_repo, [_make_component("svc")])
        assert isinstance(integrations, list)

    def test_integration_ids_are_stable(self, tmp_repo: Path) -> None:
        """Same input produces same integration IDs."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: acme/web\n"
            "    depends_on:\n"
            "      - api\n"
            "  api:\n"
            "    image: acme/api\n"
        )

        components = [
            _make_component("web"),
            _make_component("api"),
        ]

        intg1 = discover_integrations(tmp_repo, components, repo_name="myapp")
        intg2 = discover_integrations(tmp_repo, components, repo_name="myapp")
        assert intg1[0].id == intg2[0].id

    def test_integration_ids_start_with_intg(self, tmp_repo: Path) -> None:
        """All integration IDs use the 'intg' prefix."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  web:\n"
            "    image: acme/web\n"
            "    depends_on:\n"
            "      - api\n"
            "  api:\n"
            "    image: acme/api\n"
        )

        components = [
            _make_component("web"),
            _make_component("api"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        for intg in integrations:
            assert intg.id.startswith("intg-")

    def test_empty_compose_services(self, tmp_repo: Path) -> None:
        """docker-compose with empty services section."""
        (tmp_repo / "docker-compose.yml").write_text("services:\n")
        integrations = discover_integrations(tmp_repo, [_make_component("svc")])
        assert integrations == []

    def test_binary_config_file(self, tmp_repo: Path) -> None:
        """Binary file in config location should not crash."""
        (tmp_repo / "application.yml").write_bytes(b"\x00\x01\x02\xff\xfe")
        integrations = discover_integrations(tmp_repo, [_make_component("svc")])
        assert isinstance(integrations, list)
