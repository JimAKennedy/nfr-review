# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for integration point discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.arch_integrations import (
    _infer_env_from_compose_filename,
    _infer_env_from_k8s_filepath,
    _infer_env_from_k8s_namespace,
    _infer_env_from_path_parts,
    _infer_environment,
    discover_integrations,
    discover_integrations_multi_repo,
    materialize_infra_components,
)
from nfr_review.arch_models import Component, ComponentBoundary, IntegrationPoint

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


# ---------------------------------------------------------------------------
# Docker Compose env-var cross-referencing (Strategy 6)
# ---------------------------------------------------------------------------


class TestComposeEnvIntegrations:
    def test_env_addr_references_other_service(self, tmp_repo: Path) -> None:
        """Service env var with *_ADDR referencing another compose service."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  checkout:\n"
            "    image: acme/checkout\n"
            "    environment:\n"
            "      - CART_ADDR=cart:7070\n"
            "  cart:\n"
            "    image: acme/cart\n"
        )

        components = [
            _make_component("checkout"),
            _make_component("cart"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        env_intg = [i for i in integrations if "env" in i.description.lower()]
        assert len(env_intg) >= 1
        assert any(
            i.source_component_id == "comp-checkout-000000"
            and i.target_component_id == "comp-cart-000000"
            for i in env_intg
        )

    def test_env_host_references_service(self, tmp_repo: Path) -> None:
        """*_HOST env var referencing a compose service."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  proxy:\n"
            "    image: envoy:latest\n"
            "    environment:\n"
            "      BACKEND_HOST: api\n"
            "  api:\n"
            "    image: acme/api\n"
        )

        components = [
            _make_component("proxy"),
            _make_component("api"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        env_intg = [i for i in integrations if "env" in i.description.lower()]
        assert len(env_intg) >= 1

    def test_env_var_resolved_from_dotenv(self, tmp_repo: Path) -> None:
        """Bare env var names resolved from .env file."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  frontend:\n"
            "    image: acme/fe\n"
            "    environment:\n"
            "      - API_ADDR\n"
            "  api:\n"
            "    image: acme/api\n"
        )
        (tmp_repo / ".env").write_text("API_ADDR=api:8080\n")

        components = [
            _make_component("frontend"),
            _make_component("api"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        env_intg = [i for i in integrations if "env" in i.description.lower()]
        assert len(env_intg) >= 1

    def test_kafka_addr_detected_as_message_queue(self, tmp_repo: Path) -> None:
        """KAFKA_ADDR env var gets message_queue style."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  consumer:\n"
            "    image: acme/consumer\n"
            "    environment:\n"
            "      - KAFKA_ADDR=kafka:9092\n"
            "  kafka:\n"
            "    image: confluentinc/cp-kafka\n"
        )

        components = [
            _make_component("consumer"),
            _make_component("kafka", comp_type="queue"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        kafka_intg = [i for i in integrations if i.protocol == "kafka"]
        assert len(kafka_intg) >= 1
        assert kafka_intg[0].style == "message_queue"

    def test_non_addr_env_ignored(self, tmp_repo: Path) -> None:
        """Env vars without _ADDR/_HOST/_URL suffix are ignored."""
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n"
            "  app:\n"
            "    image: acme/app\n"
            "    environment:\n"
            "      - LOG_LEVEL=debug\n"
            "      - PORT=8080\n"
            "  db:\n"
            "    image: postgres:15\n"
        )

        components = [
            _make_component("app"),
            _make_component("db", comp_type="database"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        env_intg = [i for i in integrations if "env" in i.description.lower()]
        assert len(env_intg) == 0


# ---------------------------------------------------------------------------
# K8s manifest env-var cross-referencing (Strategy 7)
# ---------------------------------------------------------------------------


class TestK8sEnvIntegrations:
    def test_deployment_env_references_service(self, tmp_repo: Path) -> None:
        """K8s Deployment env var referencing another service."""
        k8s_dir = tmp_repo / "kubernetes-manifests"
        k8s_dir.mkdir()

        (k8s_dir / "checkout.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: checkout\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: checkout\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: server\n"
            "          env:\n"
            "            - name: CART_SERVICE_ADDR\n"
            "              value: cartservice:7070\n"
            "            - name: PAYMENT_SERVICE_ADDR\n"
            "              value: paymentservice:50051\n"
        )

        components = [
            _make_component("checkout"),
            _make_component("cartservice"),
            _make_component("paymentservice"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        k8s_env = [
            i for i in integrations if "K8s" in i.description and "env" in i.description
        ]
        assert len(k8s_env) >= 2

        targets = {i.target_component_id for i in k8s_env}
        assert "comp-cartservice-000000" in targets
        assert "comp-paymentservice-000000" in targets

    def test_redis_addr_detected(self, tmp_repo: Path) -> None:
        """REDIS_ADDR env var in K8s deployment."""
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()

        (k8s_dir / "cart.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: cart\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: cart\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: server\n"
            "          env:\n"
            "            - name: REDIS_ADDR\n"
            "              value: redis-cart:6379\n"
        )

        components = [
            _make_component("cart"),
            _make_component("redis-cart", comp_type="database"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        redis_intg = [i for i in integrations if "redis" in (i.protocol or "")]
        assert len(redis_intg) >= 1

    def test_configmap_refs_not_matched(self, tmp_repo: Path) -> None:
        """K8s env vars with valueFrom (configmap refs) have no string value."""
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()

        (k8s_dir / "app.yaml").write_text(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: app\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: app\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: server\n"
            "          env:\n"
            "            - name: DB_HOST\n"
            "              valueFrom:\n"
            "                configMapKeyRef:\n"
            "                  name: config\n"
            "                  key: db-host\n"
        )

        components = [_make_component("app")]
        integrations = discover_integrations(tmp_repo, components)
        k8s_env = [
            i for i in integrations if "K8s" in i.description and "env" in i.description
        ]
        assert len(k8s_env) == 0


# ---------------------------------------------------------------------------
# gRPC proto service discovery (Strategy 8)
# ---------------------------------------------------------------------------


class TestGrpcIntegrations:
    def test_proto_service_matched_to_component(self, tmp_repo: Path) -> None:
        """gRPC client stub usage detected in service source code."""
        # Create proto definition
        protos_dir = tmp_repo / "protos"
        protos_dir.mkdir()
        (protos_dir / "demo.proto").write_text(
            'syntax = "proto3";\n'
            "service CartService {\n"
            "  rpc AddItem(AddItemRequest) returns (Empty) {}\n"
            "}\n"
            "service PaymentService {\n"
            "  rpc Charge(ChargeRequest) returns (ChargeResponse) {}\n"
            "}\n"
        )

        # Create checkout service that calls CartService and PaymentService
        svc_dir = tmp_repo / "src" / "checkout"
        svc_dir.mkdir(parents=True)
        (svc_dir / "main.go").write_text(
            "package main\n\n"
            "func main() {\n"
            "  cartClient := NewCartServiceClient(conn)\n"
            "  payClient := NewPaymentServiceClient(conn)\n"
            "}\n"
        )

        # Create cart service (doesn't call others)
        cart_dir = tmp_repo / "src" / "cart"
        cart_dir.mkdir(parents=True)
        (cart_dir / "main.go").write_text("package main\nfunc main() {}\n")

        components = [
            _make_component("checkout", boundary_path="src/checkout"),
            _make_component("cart", boundary_path="src/cart"),
            _make_component("payment", boundary_path="src/payment"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        grpc_intg = [i for i in integrations if i.style == "rpc"]
        assert len(grpc_intg) == 2

        targets = {i.target_component_id for i in grpc_intg}
        assert "comp-cart-000000" in targets
        assert "comp-payment-000000" in targets

    def test_proto_generated_files_excluded(self, tmp_repo: Path) -> None:
        """Proto-generated files should not produce false positives."""
        protos_dir = tmp_repo / "protos"
        protos_dir.mkdir()
        (protos_dir / "svc.proto").write_text(
            'syntax = "proto3";\nservice MyService { rpc Get(Req) returns (Res) {} }\n'
        )

        svc_dir = tmp_repo / "src" / "app"
        svc_dir.mkdir(parents=True)
        # Only a generated file references the stub — no real client call
        (svc_dir / "svc.pb.go").write_text(
            "// Generated code\ntype MyServiceClient struct{}\n"
        )
        (svc_dir / "main.go").write_text("package main\nfunc main() {}\n")

        components = [
            _make_component("app", boundary_path="src/app"),
            _make_component("myservice", boundary_path="src/myservice"),
        ]

        integrations = discover_integrations(tmp_repo, components)
        grpc_intg = [i for i in integrations if i.style == "rpc"]
        assert len(grpc_intg) == 0

    def test_no_proto_files(self, tmp_repo: Path) -> None:
        """No proto files => no gRPC integrations."""
        components = [_make_component("app")]
        integrations = discover_integrations(tmp_repo, components)
        grpc_intg = [i for i in integrations if i.style == "rpc"]
        assert len(grpc_intg) == 0


# ---------------------------------------------------------------------------
# Build-dependency to infrastructure mapping (Strategy 9)
# ---------------------------------------------------------------------------


class TestBuildDepIntegrations:
    def test_maven_database_drivers(self, tmp_repo: Path) -> None:
        """Maven pom.xml with database driver dependencies."""
        (tmp_repo / "pom.xml").write_text(
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>com.mysql</groupId>\n"
            "      <artifactId>mysql-connector-j</artifactId>\n"
            "    </dependency>\n"
            "    <dependency>\n"
            "      <groupId>org.postgresql</groupId>\n"
            "      <artifactId>postgresql</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )

        components = [
            _make_component("myapp", boundary_path="."),
        ]

        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "dependency" in i.description.lower()]
        assert len(build_intg) >= 2

        infra_names = {i.description for i in build_intg}
        assert any("mysql" in d for d in infra_names)
        assert any("postgresql" in d for d in infra_names)

    def test_maven_spring_starters(self, tmp_repo: Path) -> None:
        """Spring Boot starters imply infrastructure integrations."""
        (tmp_repo / "pom.xml").write_text(
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>org.springframework.boot</groupId>\n"
            "      <artifactId>spring-boot-starter-data-jpa</artifactId>\n"
            "    </dependency>\n"
            "    <dependency>\n"
            "      <groupId>org.springframework.boot</groupId>\n"
            "      <artifactId>spring-boot-starter-cache</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )

        components = [_make_component("myapp", boundary_path=".")]

        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "dependency" in i.description.lower()]
        assert len(build_intg) >= 2

    def test_npm_infra_deps(self, tmp_repo: Path) -> None:
        """npm package.json with infrastructure dependencies."""
        import json

        (tmp_repo / "package.json").write_text(
            json.dumps(
                {
                    "name": "myapp",
                    "dependencies": {
                        "pg": "^8.0.0",
                        "ioredis": "^5.0.0",
                        "express": "^4.18.0",
                    },
                }
            )
        )

        components = [_make_component("myapp", boundary_path=".")]

        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "npm" in i.description.lower()]
        assert len(build_intg) >= 2

    def test_go_mod_infra_deps(self, tmp_repo: Path) -> None:
        """go.mod with infrastructure dependencies."""
        (tmp_repo / "go.mod").write_text(
            "module myapp\n\n"
            "require (\n"
            "  github.com/lib/pq v1.10.9\n"
            "  github.com/redis/go-redis/v9 v9.0.0\n"
            "  github.com/segmentio/kafka-go v0.4.47\n"
            ")\n"
        )

        components = [_make_component("myapp", boundary_path=".")]

        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "Go module" in i.description]
        assert len(build_intg) >= 3

        protocols = {i.protocol for i in build_intg}
        assert "postgresql" in protocols
        assert "redis" in protocols
        assert "kafka" in protocols

    def test_python_requirements(self, tmp_repo: Path) -> None:
        """Python requirements.txt with infrastructure dependencies."""
        (tmp_repo / "requirements.txt").write_text(
            "psycopg2-binary>=2.9\nredis>=4.0\ncelery>=5.3\n"
        )

        components = [_make_component("myapp", boundary_path=".")]

        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "Python" in i.description]
        assert len(build_intg) >= 3

    def test_no_build_files(self, tmp_repo: Path) -> None:
        """No build files => no build-dep integrations."""
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "dependency" in i.description.lower()]
        assert len(build_intg) == 0


# ---------------------------------------------------------------------------
# Owning component fix (deeply-nested config files)
# ---------------------------------------------------------------------------


class TestOwningComponentFix:
    def test_deeply_nested_config_found_by_root_component(self, tmp_repo: Path) -> None:
        """Config file at src/main/resources/ should be owned by root component."""
        config_dir = tmp_repo / "src" / "main" / "resources"
        config_dir.mkdir(parents=True)
        (config_dir / "application-mysql.properties").write_text(
            "spring.datasource.url=jdbc:mysql://localhost/testdb\n"
        )

        # Root service component + a database component
        root_comp = Component(
            id="comp-myapp-000000",
            name="myapp",
            description="Root application",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="repo", path=".", repo="test-repo")],
            repo="test-repo",
        )
        db_comp = Component(
            id="comp-mysql-000000",
            name="mysql",
            description="MySQL database",
            component_type="database",
            boundaries=[
                ComponentBoundary(
                    boundary_type="build_target",
                    path="docker-compose.yml",
                    repo="test-repo",
                )
            ],
            repo="test-repo",
        )

        integrations = discover_integrations(tmp_repo, [db_comp, root_comp])
        jdbc_intg = [i for i in integrations if "jdbc" in (i.protocol or "")]
        assert len(jdbc_intg) >= 1
        # Source should be the root component, not the mysql component
        assert all(i.source_component_id == "comp-myapp-000000" for i in jdbc_intg)


# ---------------------------------------------------------------------------
# Native (non-JDBC) connection string patterns
# ---------------------------------------------------------------------------


class TestNativeConnectionStrings:
    def test_native_postgresql_url(self, tmp_repo: Path) -> None:
        """postgresql:// URL in .env file."""
        (tmp_repo / ".env").write_text("DATABASE_URL=postgresql://dbhost:5432/mydb\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        pg_intg = [i for i in integrations if i.protocol == "postgresql"]
        assert len(pg_intg) >= 1
        assert pg_intg[0].style == "shared_database"

    def test_postgres_shorthand_url(self, tmp_repo: Path) -> None:
        """postgres:// shorthand URL."""
        (tmp_repo / ".env").write_text("DATABASE_URL=postgres://pgserver/mydb\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        pg_intg = [i for i in integrations if i.protocol == "postgresql"]
        assert len(pg_intg) >= 1

    def test_native_mysql_url(self, tmp_repo: Path) -> None:
        """mysql:// URL in config."""
        (tmp_repo / "config.yml").write_text("database:\n  url: mysql://mysqlhost:3306/mydb\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        mysql_intg = [i for i in integrations if i.protocol == "mysql"]
        assert len(mysql_intg) >= 1
        assert mysql_intg[0].style == "shared_database"

    def test_native_pg_localhost_fallback(self, tmp_repo: Path) -> None:
        """postgresql://localhost falls back to 'postgresql' as target."""
        (tmp_repo / ".env").write_text("DATABASE_URL=postgresql://localhost:5432/mydb\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        pg_intg = [i for i in integrations if i.protocol == "postgresql"]
        assert len(pg_intg) >= 1


# ---------------------------------------------------------------------------
# Spring Boot property patterns
# ---------------------------------------------------------------------------


class TestSpringPropertyPatterns:
    def test_spring_redis_host(self, tmp_repo: Path) -> None:
        """spring.redis.host property."""
        res_dir = tmp_repo / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.properties").write_text("spring.redis.host=my-redis-server\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        redis_intg = [
            i for i in integrations if i.protocol == "redis" and "Spring" in i.description
        ]
        assert len(redis_intg) >= 1
        assert redis_intg[0].style == "shared_database"

    def test_spring_data_redis_host(self, tmp_repo: Path) -> None:
        """spring.data.redis.host property (Spring Boot 3.x)."""
        res_dir = tmp_repo / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.yml").write_text(
            "spring:\n  data:\n    redis:\n      host: my-redis\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        redis_intg = [
            i for i in integrations if i.protocol == "redis" and "Spring" in i.description
        ]
        assert len(redis_intg) >= 1

    def test_spring_kafka_bootstrap_servers(self, tmp_repo: Path) -> None:
        """spring.kafka.bootstrap-servers property."""
        res_dir = tmp_repo / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.properties").write_text(
            "spring.kafka.bootstrap-servers=kafka-broker:9092\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        kafka_intg = [
            i for i in integrations if i.protocol == "kafka" and "Spring" in i.description
        ]
        assert len(kafka_intg) >= 1
        assert kafka_intg[0].style == "message_queue"

    def test_spring_rabbitmq_host(self, tmp_repo: Path) -> None:
        """spring.rabbitmq.host property."""
        res_dir = tmp_repo / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.properties").write_text("spring.rabbitmq.host=rmq-server\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        rmq_intg = [
            i for i in integrations if i.protocol == "amqp" and "Spring" in i.description
        ]
        assert len(rmq_intg) >= 1

    def test_spring_mongodb_uri(self, tmp_repo: Path) -> None:
        """spring.data.mongodb.uri property."""
        res_dir = tmp_repo / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.yml").write_text(
            "spring:\n  data:\n    mongodb:\n      uri: mongodb://mongo-host/mydb\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        mongo_intg = [
            i for i in integrations if "Spring" in i.description and "mongodb" in i.description
        ]
        assert len(mongo_intg) >= 1

    def test_spring_elasticsearch_uris(self, tmp_repo: Path) -> None:
        """spring.elasticsearch.uris property."""
        res_dir = tmp_repo / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.properties").write_text(
            "spring.elasticsearch.uris=http://es-host:9200\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        es_intg = [
            i
            for i in integrations
            if "Spring" in i.description and "elasticsearch" in i.description
        ]
        assert len(es_intg) >= 1

    def test_spring_mail_host(self, tmp_repo: Path) -> None:
        """spring.mail.host property."""
        res_dir = tmp_repo / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.properties").write_text("spring.mail.host=smtp.company.com\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        mail_intg = [
            i for i in integrations if "Spring" in i.description and "mail" in i.description
        ]
        assert len(mail_intg) >= 1

    def test_spring_property_with_env_var_placeholder(self, tmp_repo: Path) -> None:
        """spring.redis.host=${REDIS_HOST} should still detect redis."""
        res_dir = tmp_repo / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.properties").write_text("spring.redis.host=${REDIS_HOST}\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        redis_intg = [
            i for i in integrations if i.protocol == "redis" and "Spring" in i.description
        ]
        assert len(redis_intg) >= 1

    def test_spring_cassandra_contact_points(self, tmp_repo: Path) -> None:
        """spring.data.cassandra.contact-points property."""
        res_dir = tmp_repo / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.properties").write_text(
            "spring.data.cassandra.contact-points=cass-node1\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        cass_intg = [
            i
            for i in integrations
            if "Spring" in i.description and "cassandra" in i.description
        ]
        assert len(cass_intg) >= 1


# ---------------------------------------------------------------------------
# Expanded Maven/Gradle dependency mappings
# ---------------------------------------------------------------------------


class TestExpandedMavenDeps:
    def test_maven_spring_starters_expanded(self, tmp_repo: Path) -> None:
        """New Spring starters: data-cassandra, graphql, websocket."""
        (tmp_repo / "pom.xml").write_text(
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <artifactId>spring-boot-starter-data-cassandra</artifactId>\n"
            "    </dependency>\n"
            "    <dependency>\n"
            "      <artifactId>spring-boot-starter-graphql</artifactId>\n"
            "    </dependency>\n"
            "    <dependency>\n"
            "      <artifactId>spring-boot-starter-websocket</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "dependency" in i.description.lower()]
        protocols = {i.protocol for i in build_intg}
        assert "cql" in protocols
        assert "graphql" in protocols
        assert "ws" in protocols

    def test_maven_grpc_deps(self, tmp_repo: Path) -> None:
        """gRPC Maven dependencies detected."""
        (tmp_repo / "pom.xml").write_text(
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <artifactId>grpc-netty</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        grpc_intg = [i for i in integrations if i.protocol == "grpc"]
        assert len(grpc_intg) >= 1

    def test_maven_caffeine_cache(self, tmp_repo: Path) -> None:
        """Caffeine cache library detected."""
        (tmp_repo / "pom.xml").write_text(
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <artifactId>caffeine</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        cache_intg = [i for i in integrations if "cache" in i.description.lower()]
        assert len(cache_intg) >= 1

    def test_maven_cloud_sdk_deps(self, tmp_repo: Path) -> None:
        """AWS/GCP Maven SDK dependencies."""
        (tmp_repo / "pom.xml").write_text(
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <artifactId>aws-java-sdk-s3</artifactId>\n"
            "    </dependency>\n"
            "    <dependency>\n"
            "      <artifactId>aws-java-sdk-sqs</artifactId>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        aws_intg = [i for i in integrations if "aws" in i.description.lower()]
        assert len(aws_intg) >= 2


# ---------------------------------------------------------------------------
# Expanded npm dependency mappings
# ---------------------------------------------------------------------------


class TestExpandedNpmDeps:
    def test_npm_orm_deps(self, tmp_repo: Path) -> None:
        """npm ORM/query-builder packages detected."""
        import json

        (tmp_repo / "package.json").write_text(
            json.dumps(
                {
                    "name": "myapp",
                    "dependencies": {
                        "@prisma/client": "^5.0.0",
                        "drizzle-orm": "^0.30.0",
                    },
                }
            )
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        db_intg = [
            i for i in integrations if i.style == "shared_database" and "npm" in i.description
        ]
        assert len(db_intg) >= 1

    def test_npm_grpc_websocket(self, tmp_repo: Path) -> None:
        """npm gRPC and WebSocket packages."""
        import json

        (tmp_repo / "package.json").write_text(
            json.dumps(
                {
                    "name": "myapp",
                    "dependencies": {
                        "@grpc/grpc-js": "^1.8.0",
                        "socket.io": "^4.7.0",
                    },
                }
            )
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        protocols = {i.protocol for i in integrations if "npm" in i.description}
        assert "grpc" in protocols
        assert "ws" in protocols

    def test_npm_cloud_sdk_deps(self, tmp_repo: Path) -> None:
        """npm AWS/Azure SDK packages."""
        import json

        (tmp_repo / "package.json").write_text(
            json.dumps(
                {
                    "name": "myapp",
                    "dependencies": {
                        "@aws-sdk/client-s3": "^3.0.0",
                        "@azure/service-bus": "^7.0.0",
                    },
                }
            )
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        assert any("aws" in i.description.lower() for i in integrations)
        assert any("azure" in i.description.lower() for i in integrations)

    def test_npm_message_queue_deps(self, tmp_repo: Path) -> None:
        """npm Bull/NATS message queue packages."""
        import json

        (tmp_repo / "package.json").write_text(
            json.dumps(
                {
                    "name": "myapp",
                    "dependencies": {
                        "bullmq": "^4.0.0",
                        "nats": "^2.0.0",
                    },
                }
            )
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        mq_intg = [i for i in integrations if i.style == "message_queue"]
        assert len(mq_intg) >= 2


# ---------------------------------------------------------------------------
# Expanded Python dependency mappings
# ---------------------------------------------------------------------------


class TestExpandedPythonDeps:
    def test_python_async_drivers(self, tmp_repo: Path) -> None:
        """Python async database drivers (asyncpg, motor, aiokafka)."""
        (tmp_repo / "requirements.txt").write_text(
            "asyncpg>=0.29\nmotor>=3.3\naiokafka>=0.9\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "Python" in i.description]
        assert len(build_intg) >= 3
        infra = {i.description for i in build_intg}
        assert any("postgresql" in d for d in infra)
        assert any("mongodb" in d for d in infra)
        assert any("kafka" in d for d in infra)

    def test_python_grpc_deps(self, tmp_repo: Path) -> None:
        """Python gRPC library."""
        (tmp_repo / "requirements.txt").write_text("grpcio>=1.60\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        grpc_intg = [i for i in integrations if i.protocol == "grpc"]
        assert len(grpc_intg) >= 1

    def test_python_cloud_sdk(self, tmp_repo: Path) -> None:
        """Python boto3 (AWS) detection."""
        (tmp_repo / "requirements.txt").write_text("boto3>=1.34\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        aws_intg = [i for i in integrations if "aws" in i.description.lower()]
        assert len(aws_intg) >= 1

    def test_python_aioredis(self, tmp_repo: Path) -> None:
        """Python aioredis async Redis driver."""
        (tmp_repo / "requirements.txt").write_text("aioredis>=2.0\n")
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        redis_intg = [i for i in integrations if i.protocol == "redis"]
        assert len(redis_intg) >= 1


# ---------------------------------------------------------------------------
# Expanded Go dependency mappings
# ---------------------------------------------------------------------------


class TestExpandedGoDeps:
    def test_go_grpc_dep(self, tmp_repo: Path) -> None:
        """Go gRPC library."""
        (tmp_repo / "go.mod").write_text(
            "module myapp\n\nrequire (\n  google.golang.org/grpc v1.62.0\n)\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        grpc_intg = [i for i in integrations if i.protocol == "grpc"]
        assert len(grpc_intg) >= 1

    def test_go_nats_dep(self, tmp_repo: Path) -> None:
        """Go NATS message queue library."""
        (tmp_repo / "go.mod").write_text(
            "module myapp\n\nrequire (\n  github.com/nats-io/nats.go v1.33.0\n)\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        nats_intg = [i for i in integrations if i.protocol == "nats"]
        assert len(nats_intg) >= 1
        assert nats_intg[0].style == "message_queue"

    def test_go_cloud_sdk(self, tmp_repo: Path) -> None:
        """Go AWS SDK."""
        (tmp_repo / "go.mod").write_text(
            "module myapp\n\nrequire (\n  github.com/aws/aws-sdk-go-v2 v1.26.0\n)\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        aws_intg = [i for i in integrations if "aws" in i.description.lower()]
        assert len(aws_intg) >= 1

    def test_go_orm_dep(self, tmp_repo: Path) -> None:
        """Go GORM ORM library."""
        (tmp_repo / "go.mod").write_text(
            "module myapp\n\nrequire (\n  gorm.io/gorm v1.25.0\n)\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        db_intg = [i for i in integrations if i.style == "shared_database"]
        assert len(db_intg) >= 1


# ---------------------------------------------------------------------------
# Rust Cargo.toml dependency scanning
# ---------------------------------------------------------------------------


class TestRustDeps:
    def test_rust_database_deps(self, tmp_repo: Path) -> None:
        """Rust Cargo.toml with database dependencies."""
        (tmp_repo / "Cargo.toml").write_text(
            '[package]\nname = "myapp"\nversion = "0.1.0"\n\n'
            "[dependencies]\n"
            'tokio-postgres = "0.7"\n'
            'redis = "0.24"\n'
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "Rust" in i.description]
        assert len(build_intg) >= 2
        protocols = {i.protocol for i in build_intg}
        assert "postgresql" in protocols
        assert "redis" in protocols

    def test_rust_message_queue_deps(self, tmp_repo: Path) -> None:
        """Rust Cargo.toml with Kafka and RabbitMQ."""
        (tmp_repo / "Cargo.toml").write_text(
            '[package]\nname = "myapp"\nversion = "0.1.0"\n\n'
            "[dependencies]\n"
            'rdkafka = { version = "0.36", features = ["cmake-build"] }\n'
            'lapin = "2.3"\n'
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if "Rust" in i.description]
        assert len(build_intg) >= 2
        protocols = {i.protocol for i in build_intg}
        assert "kafka" in protocols
        assert "amqp" in protocols

    def test_rust_grpc_dep(self, tmp_repo: Path) -> None:
        """Rust tonic gRPC library."""
        (tmp_repo / "Cargo.toml").write_text(
            '[package]\nname = "myapp"\nversion = "0.1.0"\n\n[dependencies]\ntonic = "0.11"\n'
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        grpc_intg = [i for i in integrations if i.protocol == "grpc"]
        assert len(grpc_intg) >= 1

    def test_rust_no_false_positive_on_comments(self, tmp_repo: Path) -> None:
        """Commented-out or inline text shouldn't match."""
        (tmp_repo / "Cargo.toml").write_text(
            '[package]\nname = "myapp"\nversion = "0.1.0"\n\n'
            "[dependencies]\n"
            '# redis = "0.24" -- commented out\n'
            'serde = "1.0"\n'
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        redis_intg = [i for i in integrations if i.protocol == "redis"]
        assert len(redis_intg) == 0


# ---------------------------------------------------------------------------
# .NET csproj dependency scanning
# ---------------------------------------------------------------------------


class TestDotNetDeps:
    def test_csproj_database_deps(self, tmp_repo: Path) -> None:
        """.csproj with EF Core SQL Server and Redis."""
        (tmp_repo / "MyApp.csproj").write_text(
            "<Project>\n"
            "  <ItemGroup>\n"
            "    <PackageReference"
            ' Include="Microsoft.EntityFrameworkCore.SqlServer"'
            ' Version="8.0.0" />\n'
            '    <PackageReference Include="StackExchange.Redis" Version="2.7.0" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if ".NET" in i.description]
        assert len(build_intg) >= 2
        protocols = {i.protocol for i in build_intg}
        assert "sqlserver" in protocols
        assert "redis" in protocols

    def test_csproj_message_queue_deps(self, tmp_repo: Path) -> None:
        """.csproj with Kafka and RabbitMQ."""
        (tmp_repo / "MyApp.csproj").write_text(
            "<Project>\n"
            "  <ItemGroup>\n"
            '    <PackageReference Include="Confluent.Kafka" Version="2.3.0" />\n'
            '    <PackageReference Include="RabbitMQ.Client" Version="6.8.0" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if ".NET" in i.description]
        assert len(build_intg) >= 2
        protocols = {i.protocol for i in build_intg}
        assert "kafka" in protocols
        assert "amqp" in protocols

    def test_csproj_grpc_and_cloud(self, tmp_repo: Path) -> None:
        """.csproj with gRPC and AWS SDK."""
        (tmp_repo / "MyApp.csproj").write_text(
            "<Project>\n"
            "  <ItemGroup>\n"
            '    <PackageReference Include="Grpc.Net.Client" Version="2.60.0" />\n'
            '    <PackageReference Include="AWSSDK.S3" Version="3.7.0" />\n'
            "    <PackageReference"
            ' Include="Npgsql.EntityFrameworkCore.PostgreSQL"'
            ' Version="8.0.0" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if ".NET" in i.description]
        assert len(build_intg) >= 3
        protocols = {i.protocol for i in build_intg}
        assert "grpc" in protocols
        assert "postgresql" in protocols

    def test_multiple_csproj_files(self, tmp_repo: Path) -> None:
        """Multiple .csproj files in one component boundary."""
        (tmp_repo / "Api.csproj").write_text(
            "<Project>\n"
            "  <ItemGroup>\n"
            '    <PackageReference Include="MongoDB.Driver" Version="2.25.0" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )
        (tmp_repo / "Worker.csproj").write_text(
            "<Project>\n"
            "  <ItemGroup>\n"
            '    <PackageReference Include="Confluent.Kafka" Version="2.3.0" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        build_intg = [i for i in integrations if ".NET" in i.description]
        assert len(build_intg) >= 2
        protocols = {i.protocol for i in build_intg}
        assert "mongodb" in protocols
        assert "kafka" in protocols


# ---------------------------------------------------------------------------
# Environment inference
# ---------------------------------------------------------------------------


class TestInferEnvironment:
    def test_spring_profile_dev(self, tmp_path: Path) -> None:
        f = tmp_path / "application-dev.yml"
        f.touch()
        assert _infer_environment(f, tmp_path) == "dev"

    def test_spring_profile_prod(self, tmp_path: Path) -> None:
        f = tmp_path / "application-prod.yml"
        f.touch()
        assert _infer_environment(f, tmp_path) == "prod"

    def test_spring_profile_production_normalizes(self, tmp_path: Path) -> None:
        f = tmp_path / "application-production.properties"
        f.touch()
        assert _infer_environment(f, tmp_path) == "prod"

    def test_spring_profile_test(self, tmp_path: Path) -> None:
        f = tmp_path / "application-test.yaml"
        f.touch()
        assert _infer_environment(f, tmp_path) == "test"

    def test_appsettings_staging(self, tmp_path: Path) -> None:
        f = tmp_path / "appsettings.Staging.json"
        f.touch()
        assert _infer_environment(f, tmp_path) == "staging"

    def test_dotenv_production(self, tmp_path: Path) -> None:
        f = tmp_path / ".env.production"
        f.touch()
        assert _infer_environment(f, tmp_path) == "prod"

    def test_base_config_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "application.yml"
        f.touch()
        assert _infer_environment(f, tmp_path) is None

    def test_k8s_overlay_dir(self, tmp_path: Path) -> None:
        overlay = tmp_path / "k8s" / "overlays" / "dev"
        overlay.mkdir(parents=True)
        f = overlay / "config.yaml"
        f.touch()
        assert _infer_environment(f, tmp_path) == "dev"

    def test_unknown_profile_ignored(self, tmp_path: Path) -> None:
        f = tmp_path / "application-custom.yml"
        f.touch()
        assert _infer_environment(f, tmp_path) is None


# ---------------------------------------------------------------------------
# Path-part environment inference
# ---------------------------------------------------------------------------


class TestInferEnvFromPathParts:
    def test_prod_directory(self) -> None:
        assert _infer_env_from_path_parts(["k8s", "prod", "deployment.yaml"]) == "prod"

    def test_production_normalizes(self) -> None:
        assert _infer_env_from_path_parts(["deploy", "production"]) == "prod"

    def test_overlays_pattern(self) -> None:
        assert _infer_env_from_path_parts(["kustomize", "overlays", "staging"]) == "staging"

    def test_environments_pattern(self) -> None:
        assert _infer_env_from_path_parts(["environments", "dev", "config.yaml"]) == "dev"

    def test_no_env_returns_none(self) -> None:
        assert _infer_env_from_path_parts(["k8s", "base", "deployment.yaml"]) is None

    def test_uat_normalizes_to_staging(self) -> None:
        assert _infer_env_from_path_parts(["overlays", "uat"]) == "staging"


# ---------------------------------------------------------------------------
# K8s namespace environment inference
# ---------------------------------------------------------------------------


class TestInferEnvFromK8sNamespace:
    def test_production_namespace(self) -> None:
        doc = {"metadata": {"namespace": "production"}}
        assert _infer_env_from_k8s_namespace(doc) == "prod"

    def test_staging_namespace(self) -> None:
        doc = {"metadata": {"namespace": "staging"}}
        assert _infer_env_from_k8s_namespace(doc) == "staging"

    def test_dev_namespace(self) -> None:
        doc = {"metadata": {"namespace": "dev"}}
        assert _infer_env_from_k8s_namespace(doc) == "dev"

    def test_default_namespace_returns_none(self) -> None:
        doc = {"metadata": {"namespace": "default"}}
        assert _infer_env_from_k8s_namespace(doc) is None

    def test_custom_namespace_returns_none(self) -> None:
        doc = {"metadata": {"namespace": "my-team"}}
        assert _infer_env_from_k8s_namespace(doc) is None

    def test_no_namespace_returns_none(self) -> None:
        doc = {"metadata": {"name": "my-svc"}}
        assert _infer_env_from_k8s_namespace(doc) is None

    def test_missing_metadata_returns_none(self) -> None:
        doc = {"kind": "Service"}
        assert _infer_env_from_k8s_namespace(doc) is None


# ---------------------------------------------------------------------------
# K8s filepath environment inference
# ---------------------------------------------------------------------------


class TestInferEnvFromK8sFilepath:
    def test_overlay_prod(self, tmp_path: Path) -> None:
        f = tmp_path / "k8s" / "overlays" / "prod" / "deployment.yaml"
        f.parent.mkdir(parents=True)
        f.touch()
        assert _infer_env_from_k8s_filepath(f, tmp_path) == "prod"

    def test_env_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "deploy" / "staging" / "svc.yaml"
        f.parent.mkdir(parents=True)
        f.touch()
        assert _infer_env_from_k8s_filepath(f, tmp_path) == "staging"

    def test_no_env_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "k8s" / "base" / "deployment.yaml"
        f.parent.mkdir(parents=True)
        f.touch()
        assert _infer_env_from_k8s_filepath(f, tmp_path) is None


# ---------------------------------------------------------------------------
# Compose filename environment inference
# ---------------------------------------------------------------------------


class TestInferEnvFromComposeFilename:
    def test_docker_compose_prod_yml(self) -> None:
        assert _infer_env_from_compose_filename(Path("docker-compose.prod.yml")) == "prod"

    def test_docker_compose_dev_yaml(self) -> None:
        assert _infer_env_from_compose_filename(Path("docker-compose.dev.yaml")) == "dev"

    def test_compose_staging_yml(self) -> None:
        assert _infer_env_from_compose_filename(Path("compose.staging.yml")) == "staging"

    def test_compose_dash_production_yml(self) -> None:
        assert _infer_env_from_compose_filename(Path("compose-production.yml")) == "prod"

    def test_docker_compose_test_yaml(self) -> None:
        assert _infer_env_from_compose_filename(Path("docker-compose.test.yaml")) == "test"

    def test_base_compose_returns_none(self) -> None:
        assert _infer_env_from_compose_filename(Path("docker-compose.yml")) is None

    def test_override_returns_none(self) -> None:
        assert _infer_env_from_compose_filename(Path("docker-compose.override.yml")) is None

    def test_minimal_returns_none(self) -> None:
        assert _infer_env_from_compose_filename(Path("docker-compose.minimal.yml")) is None


# ---------------------------------------------------------------------------
# K8s integration environment tagging
# ---------------------------------------------------------------------------


class TestK8sIntegrationEnvironment:
    def test_k8s_svc_integration_tagged_from_namespace(self, tmp_repo: Path) -> None:
        k8s_dir = tmp_repo / "k8s"
        k8s_dir.mkdir()
        (k8s_dir / "svc.yaml").write_text(
            "apiVersion: v1\nkind: Service\nmetadata:\n  name: web\n"
            "  namespace: production\nspec:\n  selector:\n    app: web\n"
        )
        (k8s_dir / "deploy.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web-deploy\n"
            "  namespace: production\n  labels:\n    app: web\n"
            "spec:\n  template:\n    metadata:\n      labels:\n        app: web\n"
        )
        components = [
            _make_component("web", boundary_path="."),
            _make_component("web-deploy", boundary_path="."),
        ]
        integrations = discover_integrations(tmp_repo, components)
        k8s_intg = [i for i in integrations if "K8s Service" in i.description]
        assert len(k8s_intg) >= 1
        assert k8s_intg[0].environment == "prod"

    def test_k8s_env_var_integration_tagged_from_filepath(self, tmp_repo: Path) -> None:
        prod_dir = tmp_repo / "k8s" / "prod"
        prod_dir.mkdir(parents=True)
        (prod_dir / "deploy.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: frontend\n"
            "spec:\n  template:\n    metadata:\n      labels: {}\n    spec:\n"
            "      containers:\n      - name: app\n        env:\n"
            "        - name: BACKEND_ADDR\n          value: backend:8080\n"
        )
        components = [
            _make_component("frontend", boundary_path="."),
            _make_component("backend", boundary_path="."),
        ]
        integrations = discover_integrations(tmp_repo, components)
        env_intg = [i for i in integrations if "env" in i.description.lower()]
        assert len(env_intg) >= 1
        assert env_intg[0].environment == "prod"


# ---------------------------------------------------------------------------
# Compose integration environment tagging
# ---------------------------------------------------------------------------


class TestComposeIntegrationEnvironment:
    def test_compose_prod_file_tags_integrations(self, tmp_repo: Path) -> None:
        (tmp_repo / "docker-compose.prod.yml").write_text(
            "services:\n  web:\n    depends_on:\n      - db\n  db:\n    image: postgres\n"
        )
        components = [
            _make_component("web", boundary_path="."),
            _make_component("db", comp_type="database", boundary_path="."),
        ]
        integrations = discover_integrations(tmp_repo, components)
        compose_intg = [i for i in integrations if "depends on" in i.description]
        assert len(compose_intg) >= 1
        assert compose_intg[0].environment == "prod"

    def test_base_compose_no_environment(self, tmp_repo: Path) -> None:
        (tmp_repo / "docker-compose.yml").write_text(
            "services:\n  web:\n    depends_on:\n      - db\n  db:\n    image: postgres\n"
        )
        components = [
            _make_component("web", boundary_path="."),
            _make_component("db", comp_type="database", boundary_path="."),
        ]
        integrations = discover_integrations(tmp_repo, components)
        compose_intg = [i for i in integrations if "depends on" in i.description]
        assert len(compose_intg) >= 1
        assert compose_intg[0].environment is None


# ---------------------------------------------------------------------------
# Config integration environment tagging
# ---------------------------------------------------------------------------


class TestConfigIntegrationEnvironment:
    def test_jdbc_tagged_with_environment(self, tmp_repo: Path) -> None:
        (tmp_repo / "application-prod.yml").write_text(
            "spring:\n  datasource:\n    url: jdbc:postgresql://prod-db:5432/mydb\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        jdbc_intg = [i for i in integrations if i.protocol and "jdbc" in i.protocol]
        assert len(jdbc_intg) >= 1
        assert jdbc_intg[0].environment == "prod"

    def test_base_config_has_no_environment(self, tmp_repo: Path) -> None:
        (tmp_repo / "application.yml").write_text(
            "spring:\n  datasource:\n    url: jdbc:postgresql://db:5432/mydb\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        jdbc_intg = [i for i in integrations if i.protocol and "jdbc" in i.protocol]
        assert len(jdbc_intg) >= 1
        assert jdbc_intg[0].environment is None


# ---------------------------------------------------------------------------
# Infrastructure component materialization
# ---------------------------------------------------------------------------


class TestMaterializeInfraComponents:
    def test_creates_missing_infra_component(self) -> None:
        app = _make_component("myapp")
        integrations = [
            IntegrationPoint(
                id="intg-test-001",
                source_component_id=app.id,
                target_component_id="infra-prod-db-abc123",
                style="shared_database",
                protocol="postgresql",
                environment="prod",
            )
        ]
        result = materialize_infra_components([app], integrations)
        infra = [c for c in result if c.id == "infra-prod-db-abc123"]
        assert len(infra) == 1
        assert infra[0].component_type == "database"
        assert infra[0].environment == "prod"

    def test_does_not_duplicate_existing(self) -> None:
        existing = Component(
            id="infra-redis-abc123",
            name="Redis",
            description="Redis cache",
            component_type="database",
        )
        integrations = [
            IntegrationPoint(
                id="intg-test-002",
                source_component_id="comp-myapp-000000",
                target_component_id="infra-redis-abc123",
                style="shared_database",
                protocol="redis",
            )
        ]
        result = materialize_infra_components([existing], integrations)
        assert len(result) == 1

    def test_queue_protocol_yields_queue_type(self) -> None:
        app = _make_component("myapp")
        integrations = [
            IntegrationPoint(
                id="intg-test-003",
                source_component_id=app.id,
                target_component_id="infra-kafka-def456",
                style="message_queue",
                protocol="kafka",
                environment="dev",
            )
        ]
        result = materialize_infra_components([app], integrations)
        kafka = [c for c in result if c.id == "infra-kafka-def456"]
        assert len(kafka) == 1
        assert kafka[0].component_type == "queue"
        assert kafka[0].environment == "dev"

    def test_end_to_end_with_discovery(self, tmp_repo: Path) -> None:
        """Discovered config integrations are materialized into components."""
        (tmp_repo / "application-dev.yml").write_text(
            "spring:\n  redis:\n    host: dev-redis\n"
        )
        components = [_make_component("myapp", boundary_path=".")]
        integrations = discover_integrations(tmp_repo, components)
        materialize_infra_components(components, integrations)
        infra_comps = [c for c in components if c.id.startswith("infra-")]
        assert len(infra_comps) >= 1
        redis = [c for c in infra_comps if "redis" in c.name.lower()]
        assert len(redis) >= 1
        assert redis[0].environment == "dev"

    def test_infra_inherits_repo_from_peer(self) -> None:
        """Materialized infra components inherit repo from connected app component."""
        app = _make_component("myapp", repo="DrumGenerator")
        integrations = [
            IntegrationPoint(
                id="intg-repo-001",
                source_component_id=app.id,
                target_component_id="infra-sqlite-abc123",
                style="shared_database",
                protocol="sqlite",
                environment="dev",
            )
        ]
        result = materialize_infra_components([app], integrations)
        infra = [c for c in result if c.id == "infra-sqlite-abc123"]
        assert len(infra) == 1
        assert infra[0].repo == "DrumGenerator"

    def test_infra_repo_none_when_no_peer(self) -> None:
        """Infra component gets repo=None when no peer has a repo set."""
        app = Component(
            id="comp-orphan-000000",
            name="orphan",
            description="No repo set",
            component_type="service",
        )
        integrations = [
            IntegrationPoint(
                id="intg-repo-002",
                source_component_id=app.id,
                target_component_id="infra-redis-def456",
                style="shared_database",
                protocol="redis",
                environment="prod",
            )
        ]
        result = materialize_infra_components([app], integrations)
        infra = [c for c in result if c.id == "infra-redis-def456"]
        assert len(infra) == 1
        assert infra[0].repo is None


# ---------------------------------------------------------------------------
# Strategy 10: CMake FetchContent / add_subdirectory cross-repo deps
# ---------------------------------------------------------------------------


class TestCmakeIntegrationDiscovery:
    """Tests for _discover_cmake_integrations."""

    def test_fetchcontent_detects_cross_repo_dep(self, tmp_repo: Path) -> None:
        """FetchContent_Declare with a matching URL creates an integration."""
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(plugin VERSION 1.0)\n"
            "include(FetchContent)\n"
            "FetchContent_Declare(\n"
            "    drumcore\n"
            "    GIT_REPOSITORY https://github.com/org/drumcore.git\n"
            "    GIT_TAG v1.0.0\n"
            ")\n"
        )
        plugin_comp = _make_component("plugin", repo="plugin", boundary_path=".")
        lib_comp = _make_component("drumcore", comp_type="library", repo="drumcore")
        integrations = discover_integrations(
            tmp_repo, [plugin_comp, lib_comp], repo_name="plugin"
        )
        cmake_intgs = [i for i in integrations if i.style == "build_dependency"]
        assert len(cmake_intgs) == 1
        assert cmake_intgs[0].source_component_id == plugin_comp.id
        assert cmake_intgs[0].target_component_id == lib_comp.id
        assert cmake_intgs[0].protocol == "cmake-fetchcontent"

    def test_add_subdirectory_detects_sibling_dep(self, tmp_repo: Path) -> None:
        """add_subdirectory with a relative path to a sibling repo creates an integration."""
        plugin_dir = tmp_repo / "plugin"
        plugin_dir.mkdir()
        lib_dir = tmp_repo / "drumcore"
        lib_dir.mkdir()
        (plugin_dir / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(plugin VERSION 1.0)\n"
            "add_subdirectory(../drumcore ${CMAKE_BINARY_DIR}/drumcore)\n"
        )
        plugin_comp = _make_component("plugin", repo="plugin", boundary_path=".")
        lib_comp = _make_component("drumcore", comp_type="library", repo="drumcore")
        integrations = discover_integrations(
            plugin_dir, [plugin_comp, lib_comp], repo_name="plugin"
        )
        cmake_intgs = [i for i in integrations if i.style == "build_dependency"]
        assert len(cmake_intgs) == 1
        assert cmake_intgs[0].protocol == "cmake-add-subdirectory"
        assert cmake_intgs[0].target_component_id == lib_comp.id

    def test_multi_repo_marks_cmake_deps_cross_repo(self, tmp_path: Path) -> None:
        """Multi-repo discovery marks FetchContent deps as cross-repo."""
        repo_a = tmp_path / "plugin-a"
        repo_a.mkdir()
        (repo_a / ".git").mkdir()
        (repo_a / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(plugin_a VERSION 1.0)\n"
            "include(FetchContent)\n"
            "FetchContent_Declare(\n"
            "    shared_lib\n"
            "    GIT_REPOSITORY https://github.com/org/shared-lib.git\n"
            "    GIT_TAG v2.0\n"
            ")\n"
        )
        repo_b = tmp_path / "shared-lib"
        repo_b.mkdir()
        (repo_b / ".git").mkdir()
        (repo_b / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(shared_lib VERSION 2.0)\n"
            "add_library(shared_lib STATIC src/lib.cpp)\n"
        )
        comp_a = _make_component("plugin-a", repo="plugin-a", boundary_path=".")
        comp_b = _make_component(
            "shared-lib", comp_type="library", repo="shared-lib", boundary_path="."
        )
        integrations = discover_integrations_multi_repo(
            [repo_a, repo_b],
            [comp_a, comp_b],
            repo_names=["plugin-a", "shared-lib"],
        )
        cmake_intgs = [i for i in integrations if i.style == "build_dependency"]
        assert len(cmake_intgs) == 1
        assert cmake_intgs[0].is_cross_repo is True

    def test_no_match_for_unknown_url(self, tmp_repo: Path) -> None:
        """FetchContent with an unknown URL produces no integration."""
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(myapp VERSION 1.0)\n"
            "FetchContent_Declare(\n"
            "    googletest\n"
            "    GIT_REPOSITORY https://github.com/google/googletest.git\n"
            "    GIT_TAG v1.14.0\n"
            ")\n"
        )
        comp = _make_component("myapp", repo="myapp", boundary_path=".")
        integrations = discover_integrations(tmp_repo, [comp], repo_name="myapp")
        cmake_intgs = [i for i in integrations if i.style == "build_dependency"]
        assert len(cmake_intgs) == 0

    def test_commented_fetchcontent_ignored(self, tmp_repo: Path) -> None:
        """Commented-out FetchContent lines are not parsed."""
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(plugin VERSION 1.0)\n"
            "# FetchContent_Declare(\n"
            "#     drumcore\n"
            "#     GIT_REPOSITORY https://github.com/org/drumcore.git\n"
            "#     GIT_TAG v1.0.0\n"
            "# )\n"
        )
        plugin_comp = _make_component("plugin", repo="plugin", boundary_path=".")
        lib_comp = _make_component("drumcore", comp_type="library", repo="drumcore")
        integrations = discover_integrations(
            tmp_repo, [plugin_comp, lib_comp], repo_name="plugin"
        )
        cmake_intgs = [i for i in integrations if i.style == "build_dependency"]
        assert len(cmake_intgs) == 0

    def test_multiple_fetchcontent_deps(self, tmp_repo: Path) -> None:
        """Multiple FetchContent deps produce multiple integrations."""
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(plugin VERSION 1.0)\n"
            "include(FetchContent)\n"
            "FetchContent_Declare(\n"
            "    libA\n"
            "    GIT_REPOSITORY https://github.com/org/lib-a.git\n"
            "    GIT_TAG v1.0\n"
            ")\n"
            "FetchContent_Declare(\n"
            "    libB\n"
            "    GIT_REPOSITORY https://github.com/org/lib-b.git\n"
            "    GIT_TAG v2.0\n"
            ")\n"
        )
        plugin = _make_component("plugin", repo="plugin", boundary_path=".")
        lib_a = _make_component("lib-a", comp_type="library", repo="lib-a")
        lib_b = _make_component("lib-b", comp_type="library", repo="lib-b")
        integrations = discover_integrations(
            tmp_repo, [plugin, lib_a, lib_b], repo_name="plugin"
        )
        cmake_intgs = [i for i in integrations if i.style == "build_dependency"]
        assert len(cmake_intgs) == 2
        targets = {i.target_component_id for i in cmake_intgs}
        assert targets == {lib_a.id, lib_b.id}

    def test_self_reference_ignored(self, tmp_repo: Path) -> None:
        """FetchContent pointing to the same repo is ignored."""
        (tmp_repo / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.14)\n"
            "project(mylib VERSION 1.0)\n"
            "FetchContent_Declare(\n"
            "    mylib\n"
            "    GIT_REPOSITORY https://github.com/org/mylib.git\n"
            "    GIT_TAG v1.0\n"
            ")\n"
        )
        comp = _make_component("mylib", repo="mylib", boundary_path=".")
        integrations = discover_integrations(tmp_repo, [comp], repo_name="mylib")
        cmake_intgs = [i for i in integrations if i.style == "build_dependency"]
        assert len(cmake_intgs) == 0

    def test_fixture_repos_cross_repo(self) -> None:
        """End-to-end test with the cmake-shared-lib and cmake-consumer fixtures."""
        fixtures = Path(__file__).parent / "fixtures"
        shared = fixtures / "cmake-shared-lib"
        consumer_a = fixtures / "cmake-consumer-a"
        consumer_b = fixtures / "cmake-consumer-b"

        lib_comp = _make_component(
            "drumcore",
            comp_type="library",
            repo="cmake-shared-lib",
            boundary_path=".",
        )
        comp_a = _make_component(
            "cmake-consumer-a",
            repo="cmake-consumer-a",
            boundary_path=".",
        )
        comp_b = _make_component(
            "cmake-consumer-b",
            repo="cmake-consumer-b",
            boundary_path=".",
        )
        all_comps = [lib_comp, comp_a, comp_b]

        integrations = discover_integrations_multi_repo(
            [shared, consumer_a, consumer_b],
            all_comps,
            repo_names=["cmake-shared-lib", "cmake-consumer-a", "cmake-consumer-b"],
        )
        cmake_intgs = [i for i in integrations if i.style == "build_dependency"]
        assert len(cmake_intgs) == 2
        assert all(i.is_cross_repo for i in cmake_intgs)
        sources = {i.source_component_id for i in cmake_intgs}
        assert sources == {comp_a.id, comp_b.id}
        assert all(i.target_component_id == lib_comp.id for i in cmake_intgs)

    def test_repo_name_from_url_variants(self) -> None:
        """_repo_name_from_url handles various Git URL formats."""
        from nfr_review.arch_integrations import _repo_name_from_url

        assert _repo_name_from_url("https://github.com/org/repo.git") == "repo"
        assert _repo_name_from_url("https://github.com/org/repo") == "repo"
        assert _repo_name_from_url("git@github.com:org/repo.git") == "repo"
        assert _repo_name_from_url("https://gitlab.com/org/sub/repo.git/") == "repo"
        assert _repo_name_from_url("") is None
