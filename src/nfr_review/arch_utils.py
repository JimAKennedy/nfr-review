# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared utilities for the architecture analysis subsystem.

Consolidates safe-IO helpers, ID generation, component lookup, environment
inference, and build-dependency matching that were previously duplicated
across arch_integrations, arch_discovery, arch_domain_model, and detect.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.arch_models import (
    Component,
    IntegrationPoint,
    IntegrationStyle,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safe I/O
# ---------------------------------------------------------------------------


def safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


def safe_yaml_load(text: str) -> Any:
    _yaml = YAML(typ="safe")
    try:
        return _yaml.load(text)
    except YAMLError:
        return None


def safe_yaml_load_all(text: str) -> list[Any]:
    _yaml = YAML(typ="safe")
    try:
        return [doc for doc in _yaml.load_all(text) if doc is not None]
    except YAMLError:
        return []


def safe_json_load(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def is_comment_line(text: str, pos: int) -> bool:
    """Check whether *pos* sits on a comment line (``#`` or ``//``)."""
    line_start = text.rfind("\n", 0, pos) + 1
    prefix = text[line_start:pos].lstrip()
    return prefix.startswith("#") or prefix.startswith("//")


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def make_id(prefix: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    short_hash = hashlib.sha256(name.encode()).hexdigest()[:6]
    return f"{prefix}-{slug}-{short_hash}"


def find_or_create_infra_id(name: str) -> str:
    """Generate a stable ID for an inferred infrastructure component."""
    return make_id("infra", name)


# ---------------------------------------------------------------------------
# Component lookup
# ---------------------------------------------------------------------------


def component_by_name(components: list[Component], name: str) -> Component | None:
    """Find a component by exact name (case-insensitive)."""
    name_lower = name.lower()
    for comp in components:
        if comp.name.lower() == name_lower:
            return comp
    return None


def component_by_k8s_selector(
    components: list[Component], selector: dict[str, str]
) -> Component | None:
    """Find a component whose name matches a K8s label selector's 'app' label."""
    app_label = selector.get("app") or selector.get("app.kubernetes.io/name")
    if not app_label:
        return None
    return component_by_name(components, app_label)


def component_by_repo_name(components: list[Component], repo_name: str) -> Component | None:
    """Find a component whose repo attribute matches *repo_name*."""
    name_lower = repo_name.lower()
    for comp in components:
        if comp.repo and comp.repo.lower() == name_lower:
            return comp
        if comp.name.lower() == name_lower:
            return comp
    return None


# ---------------------------------------------------------------------------
# Environment inference
# ---------------------------------------------------------------------------

_ENV_PROFILE_RE = re.compile(r"application[-_](\w+)\.(?:yml|yaml|properties)$", re.IGNORECASE)
_APPSETTINGS_ENV_RE = re.compile(r"appsettings\.(\w+)\.json$", re.IGNORECASE)
_DOTENV_ENV_RE = re.compile(r"\.env\.(\w+)$", re.IGNORECASE)

KNOWN_ENVS = frozenset(
    {
        "dev",
        "development",
        "local",
        "test",
        "testing",
        "ci",
        "staging",
        "stage",
        "uat",
        "sit",
        "prod",
        "production",
        "demo",
        "sandbox",
        "perf",
        "qa",
    }
)

ENV_NORMALIZE: dict[str, str] = {
    "development": "dev",
    "local": "dev",
    "testing": "test",
    "ci": "test",
    "stage": "staging",
    "uat": "staging",
    "sit": "staging",
    "production": "prod",
}


def infer_environment(config_path: Path, repo_path: Path) -> str | None:
    """Infer the deployment environment from a config file path.

    Returns a normalized environment name (dev/test/staging/prod) or None
    if no environment can be determined (base config).
    """
    name = config_path.name

    for pattern in (_ENV_PROFILE_RE, _APPSETTINGS_ENV_RE, _DOTENV_ENV_RE):
        m = pattern.match(name)
        if m:
            profile = m.group(1).lower()
            if profile in KNOWN_ENVS:
                return ENV_NORMALIZE.get(profile, profile)

    rel = config_path.relative_to(repo_path)
    parts = [p.lower() for p in rel.parts]
    for part in parts:
        if part in KNOWN_ENVS:
            return ENV_NORMALIZE.get(part, part)
        if part == "overlays":
            idx = parts.index(part)
            if idx + 1 < len(parts) and parts[idx + 1] in KNOWN_ENVS:
                env = parts[idx + 1]
                return ENV_NORMALIZE.get(env, env)

    return None


def normalize_env(raw: str) -> str | None:
    """Normalize a raw environment token to a canonical name, or None if unknown."""
    lower = raw.lower()
    if lower in KNOWN_ENVS:
        return ENV_NORMALIZE.get(lower, lower)
    return None


def infer_env_from_path_parts(parts: list[str]) -> str | None:
    """Infer environment from directory path segments (e.g. 'overlays/prod')."""
    lower_parts = [p.lower() for p in parts]
    for part in lower_parts:
        if part in KNOWN_ENVS:
            return ENV_NORMALIZE.get(part, part)
        if part == "overlays":
            idx = lower_parts.index(part)
            if idx + 1 < len(lower_parts) and lower_parts[idx + 1] in KNOWN_ENVS:
                env = lower_parts[idx + 1]
                return ENV_NORMALIZE.get(env, env)
        if part == "environments":
            idx = lower_parts.index(part)
            if idx + 1 < len(lower_parts) and lower_parts[idx + 1] in KNOWN_ENVS:
                env = lower_parts[idx + 1]
                return ENV_NORMALIZE.get(env, env)
    return None


def infer_env_from_k8s_namespace(doc: dict[str, Any]) -> str | None:
    """Infer environment from a K8s manifest's metadata.namespace field."""
    metadata = doc.get("metadata", {})
    if not isinstance(metadata, dict):
        return None
    ns = metadata.get("namespace", "")
    if not ns or not isinstance(ns, str):
        return None
    return normalize_env(ns)


def infer_env_from_k8s_filepath(yaml_file: Path, repo_path: Path) -> str | None:
    """Infer environment from a K8s manifest's file path."""
    try:
        rel = yaml_file.relative_to(repo_path)
    except ValueError:
        return None
    return infer_env_from_path_parts(list(rel.parts))


_COMPOSE_ENV_RE = re.compile(
    r"(?:docker-)?compose[.-](\w+)\.(?:yml|yaml)$",
    re.IGNORECASE,
)


def infer_env_from_compose_filename(compose_file: Path) -> str | None:
    """Infer environment from compose filename variants."""
    m = _COMPOSE_ENV_RE.match(compose_file.name)
    if m:
        candidate = m.group(1).lower()
        return normalize_env(candidate)
    return None


# ---------------------------------------------------------------------------
# .env file loading
# ---------------------------------------------------------------------------


def load_dotenv(repo_path: Path) -> dict[str, str]:
    """Load key=value pairs from .env file if present."""
    env_vars: dict[str, str] = {}
    env_file = repo_path / ".env"
    if not env_file.is_file():
        return env_vars
    content = safe_read_text(env_file)
    if not content:
        return env_vars
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip()
    return env_vars


def resolve_env_refs(value: str, env_vars: dict[str, str], depth: int = 3) -> str:
    """Resolve ``${VAR}`` references in a string using env_vars dict."""
    if depth <= 0 or "${" not in value:
        return value

    def _replace(m: re.Match[str]) -> str:
        return env_vars.get(m.group(1), m.group(0))

    resolved = re.sub(r"\$\{([^}:]+)(?::[^}]*)?\}", _replace, value)
    if resolved != value:
        return resolve_env_refs(resolved, env_vars, depth - 1)
    return resolved


# ---------------------------------------------------------------------------
# Shared integration helpers
# ---------------------------------------------------------------------------

ADDR_ENV_SUFFIXES = ("_ADDR", "_HOST", "_URL", "_SERVICE_ADDR", "_ENDPOINT")

IGNORED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",  # nosec B104 — filter list, not a bind call
        "example.com",
        "example.org",
        "schemas.xmlsoap.org",
        "www.w3.org",
        "xmlns.jcp.org",
        "www.springframework.org",
        "maven.apache.org",
        "json-schema.org",
    }
)

IGNORED_DOMAINS = (
    ".example.com",
    ".example.org",
    ".example.net",
    ".test",
    ".invalid",
    ".localhost",
    ".local",
)


def is_ignorable_host(host: str) -> bool:
    """Return True if the host is a generic/non-meaningful target."""
    host_lower = host.lower()
    if host_lower in IGNORED_HOSTS or host_lower.startswith("$"):
        return True
    for suffix in IGNORED_DOMAINS:
        if host_lower.endswith(suffix):
            return True
    return False


def infer_style_from_protocol(protocol: str) -> IntegrationStyle:
    """Map a detected protocol to an integration style."""
    mapping: dict[str, IntegrationStyle] = {
        "jdbc": "shared_database",
        "postgresql": "shared_database",
        "mysql": "shared_database",
        "sqlserver": "shared_database",
        "oracle": "shared_database",
        "h2": "shared_database",
        "mongodb": "shared_database",
        "redis": "shared_database",
        "cassandra": "shared_database",
        "cql": "shared_database",
        "neo4j": "shared_database",
        "bolt": "shared_database",
        "amqp": "message_queue",
        "kafka": "message_queue",
        "nats": "message_queue",
        "http": "api_call",
        "https": "api_call",
        "grpc": "api_call",
        "smtp": "api_call",
    }
    return mapping.get(protocol.lower(), "api_call")


def guess_protocol_from_env(key: str, value: str) -> str:
    """Guess protocol from an env var name/value."""
    key_upper = key.upper()
    val_lower = value.lower()
    if "kafka" in key_upper.lower() or "kafka" in val_lower:
        return "kafka"
    if "redis" in key_upper.lower() or "valkey" in key_upper.lower():
        return "redis"
    if "amqp" in val_lower or "rabbit" in key_upper.lower():
        return "amqp"
    if "mongo" in key_upper.lower():
        return "mongodb"
    if val_lower.startswith("http://") or val_lower.startswith("https://"):
        return "http"
    return "grpc"


# ---------------------------------------------------------------------------
# Table-driven build-dependency matching
# ---------------------------------------------------------------------------

InfraDepTable = dict[str, tuple[str, str, IntegrationStyle]]

MAVEN_INFRA_DEPS: InfraDepTable = {
    "mysql-connector": ("mysql", "jdbc:mysql", "shared_database"),
    "postgresql": ("postgresql", "jdbc:postgresql", "shared_database"),
    "mssql-jdbc": ("sqlserver", "jdbc:sqlserver", "shared_database"),
    "ojdbc": ("oracle", "jdbc:oracle", "shared_database"),
    "h2": ("h2-database", "jdbc:h2", "shared_database"),
    "mariadb-java-client": ("mariadb", "jdbc:mariadb", "shared_database"),
    "sqlite-jdbc": ("sqlite", "jdbc:sqlite", "shared_database"),
    "mongo-java-driver": ("mongodb", "mongodb", "shared_database"),
    "mongodb-driver": ("mongodb", "mongodb", "shared_database"),
    "jedis": ("redis", "redis", "shared_database"),
    "lettuce-core": ("redis", "redis", "shared_database"),
    "redisson": ("redis", "redis", "shared_database"),
    "kafka-clients": ("kafka", "kafka", "message_queue"),
    "amqp-client": ("rabbitmq", "amqp", "message_queue"),
    "nats-client": ("nats", "nats", "message_queue"),
    "jnats": ("nats", "nats", "message_queue"),
    "pulsar-client": ("pulsar", "pulsar", "message_queue"),
    "activemq-client": ("activemq", "jms", "message_queue"),
    "artemis-jms-client": ("artemis", "jms", "message_queue"),
    "spring-boot-starter-data-jpa": ("database", "jpa", "shared_database"),
    "spring-boot-starter-data-mongodb": ("mongodb", "mongodb", "shared_database"),
    "spring-boot-starter-data-redis": ("redis", "redis", "shared_database"),
    "spring-boot-starter-data-cassandra": ("cassandra", "cql", "shared_database"),
    "spring-boot-starter-data-elasticsearch": ("elasticsearch", "http", "api_call"),
    "spring-boot-starter-data-neo4j": ("neo4j", "bolt", "shared_database"),
    "spring-boot-starter-amqp": ("rabbitmq", "amqp", "message_queue"),
    "spring-kafka": ("kafka", "kafka", "message_queue"),
    "spring-boot-starter-cache": ("cache", "cache", "api_call"),
    "spring-boot-starter-mail": ("mail-server", "smtp", "api_call"),
    "spring-boot-starter-graphql": ("graphql", "graphql", "api_call"),
    "spring-boot-starter-websocket": ("websocket", "ws", "api_call"),
    "spring-boot-starter-oauth2-client": ("oauth2-provider", "oauth2", "api_call"),
    "spring-boot-starter-oauth2-resource-server": ("oauth2-provider", "oauth2", "api_call"),
    "spring-cloud-starter-openfeign": ("feign-target", "http", "api_call"),
    "spring-cloud-starter-stream-kafka": ("kafka", "kafka", "message_queue"),
    "spring-cloud-starter-stream-rabbit": ("rabbitmq", "amqp", "message_queue"),
    "elasticsearch-rest-client": ("elasticsearch", "http", "api_call"),
    "elasticsearch-rest-high-level-client": ("elasticsearch", "http", "api_call"),
    "opensearch-java": ("opensearch", "http", "api_call"),
    "grpc-netty": ("grpc-server", "grpc", "api_call"),
    "grpc-stub": ("grpc-server", "grpc", "api_call"),
    "caffeine": ("cache", "cache", "api_call"),
    "ehcache": ("cache", "cache", "api_call"),
    "hazelcast": ("hazelcast", "hazelcast", "shared_database"),
    "aws-java-sdk-s3": ("aws-s3", "http", "api_call"),
    "aws-java-sdk-sqs": ("aws-sqs", "http", "message_queue"),
    "aws-java-sdk-sns": ("aws-sns", "http", "message_queue"),
    "aws-java-sdk-dynamodb": ("aws-dynamodb", "http", "shared_database"),
    "google-cloud-storage": ("gcs", "http", "api_call"),
    "google-cloud-pubsub": ("gcp-pubsub", "http", "message_queue"),
}

NPM_INFRA_DEPS: InfraDepTable = {
    "pg": ("postgresql", "postgresql", "shared_database"),
    "mysql2": ("mysql", "mysql", "shared_database"),
    "mysql": ("mysql", "mysql", "shared_database"),
    "mongodb": ("mongodb", "mongodb", "shared_database"),
    "mongoose": ("mongodb", "mongodb", "shared_database"),
    "better-sqlite3": ("sqlite", "sqlite", "shared_database"),
    "mssql": ("sqlserver", "sqlserver", "shared_database"),
    "tedious": ("sqlserver", "sqlserver", "shared_database"),
    "oracledb": ("oracle", "oracle", "shared_database"),
    "cassandra-driver": ("cassandra", "cql", "shared_database"),
    "neo4j-driver": ("neo4j", "bolt", "shared_database"),
    "typeorm": ("database", "sql", "shared_database"),
    "prisma": ("database", "sql", "shared_database"),
    "@prisma/client": ("database", "sql", "shared_database"),
    "sequelize": ("database", "sql", "shared_database"),
    "knex": ("database", "sql", "shared_database"),
    "drizzle-orm": ("database", "sql", "shared_database"),
    "redis": ("redis", "redis", "shared_database"),
    "ioredis": ("redis", "redis", "shared_database"),
    "memcached": ("memcached", "memcached", "shared_database"),
    "kafkajs": ("kafka", "kafka", "message_queue"),
    "amqplib": ("rabbitmq", "amqp", "message_queue"),
    "nats": ("nats", "nats", "message_queue"),
    "bull": ("redis-queue", "redis", "message_queue"),
    "bullmq": ("redis-queue", "redis", "message_queue"),
    "@google-cloud/pubsub": ("gcp-pubsub", "http", "message_queue"),
    "@elastic/elasticsearch": ("elasticsearch", "http", "api_call"),
    "@opensearch-project/opensearch": ("opensearch", "http", "api_call"),
    "@grpc/grpc-js": ("grpc-server", "grpc", "api_call"),
    "graphql": ("graphql", "graphql", "api_call"),
    "apollo-server": ("graphql", "graphql", "api_call"),
    "@apollo/server": ("graphql", "graphql", "api_call"),
    "socket.io": ("websocket", "ws", "api_call"),
    "ws": ("websocket", "ws", "api_call"),
    "@aws-sdk/client-s3": ("aws-s3", "http", "api_call"),
    "@aws-sdk/client-sqs": ("aws-sqs", "http", "message_queue"),
    "@aws-sdk/client-sns": ("aws-sns", "http", "message_queue"),
    "@aws-sdk/client-dynamodb": ("aws-dynamodb", "http", "shared_database"),
    "@google-cloud/storage": ("gcs", "http", "api_call"),
    "@azure/storage-blob": ("azure-blob", "http", "api_call"),
    "@azure/service-bus": ("azure-servicebus", "amqp", "message_queue"),
}

PYTHON_INFRA_DEPS: InfraDepTable = {
    "psycopg2": ("postgresql", "postgresql", "shared_database"),
    "psycopg2-binary": ("postgresql", "postgresql", "shared_database"),
    "psycopg": ("postgresql", "postgresql", "shared_database"),
    "asyncpg": ("postgresql", "postgresql", "shared_database"),
    "mysqlclient": ("mysql", "mysql", "shared_database"),
    "pymysql": ("mysql", "mysql", "shared_database"),
    "aiomysql": ("mysql", "mysql", "shared_database"),
    "pymongo": ("mongodb", "mongodb", "shared_database"),
    "motor": ("mongodb", "mongodb", "shared_database"),
    "pymssql": ("sqlserver", "sqlserver", "shared_database"),
    "cx-oracle": ("oracle", "oracle", "shared_database"),
    "oracledb": ("oracle", "oracle", "shared_database"),
    "cassandra-driver": ("cassandra", "cql", "shared_database"),
    "neo4j": ("neo4j", "bolt", "shared_database"),
    "sqlalchemy": ("database", "sql", "shared_database"),
    "django": ("database", "sql", "shared_database"),
    "tortoise-orm": ("database", "sql", "shared_database"),
    "peewee": ("database", "sql", "shared_database"),
    "databases": ("database", "sql", "shared_database"),
    "redis": ("redis", "redis", "shared_database"),
    "aioredis": ("redis", "redis", "shared_database"),
    "pymemcache": ("memcached", "memcached", "shared_database"),
    "celery": ("message-broker", "amqp", "message_queue"),
    "kafka-python": ("kafka", "kafka", "message_queue"),
    "confluent-kafka": ("kafka", "kafka", "message_queue"),
    "aiokafka": ("kafka", "kafka", "message_queue"),
    "pika": ("rabbitmq", "amqp", "message_queue"),
    "aio-pika": ("rabbitmq", "amqp", "message_queue"),
    "nats-py": ("nats", "nats", "message_queue"),
    "kombu": ("message-broker", "amqp", "message_queue"),
    "elasticsearch": ("elasticsearch", "http", "api_call"),
    "opensearch-py": ("opensearch", "http", "api_call"),
    "grpcio": ("grpc-server", "grpc", "api_call"),
    "grpcio-tools": ("grpc-server", "grpc", "api_call"),
    "boto3": ("aws", "http", "api_call"),
    "google-cloud-storage": ("gcs", "http", "api_call"),
    "google-cloud-pubsub": ("gcp-pubsub", "http", "message_queue"),
    "azure-storage-blob": ("azure-blob", "http", "api_call"),
    "azure-servicebus": ("azure-servicebus", "amqp", "message_queue"),
    "httpx": ("http-service", "http", "api_call"),
    "aiohttp": ("http-service", "http", "api_call"),
}

GO_INFRA_DEPS: InfraDepTable = {
    "github.com/lib/pq": ("postgresql", "postgresql", "shared_database"),
    "github.com/jackc/pgx": ("postgresql", "postgresql", "shared_database"),
    "github.com/go-sql-driver/mysql": ("mysql", "mysql", "shared_database"),
    "go.mongodb.org/mongo-driver": ("mongodb", "mongodb", "shared_database"),
    "github.com/mattn/go-sqlite3": ("sqlite", "sqlite", "shared_database"),
    "github.com/denisenkom/go-mssqldb": ("sqlserver", "sqlserver", "shared_database"),
    "github.com/microsoft/go-mssqldb": ("sqlserver", "sqlserver", "shared_database"),
    "github.com/gocql/gocql": ("cassandra", "cql", "shared_database"),
    "github.com/neo4j/neo4j-go-driver": ("neo4j", "bolt", "shared_database"),
    "gorm.io/gorm": ("database", "sql", "shared_database"),
    "github.com/uptrace/bun": ("database", "sql", "shared_database"),
    "entgo.io/ent": ("database", "sql", "shared_database"),
    "github.com/redis/go-redis": ("redis", "redis", "shared_database"),
    "github.com/go-redis/redis": ("redis", "redis", "shared_database"),
    "github.com/bradfitz/gomemcache": ("memcached", "memcached", "shared_database"),
    "github.com/segmentio/kafka-go": ("kafka", "kafka", "message_queue"),
    "github.com/IBM/sarama": ("kafka", "kafka", "message_queue"),
    "github.com/Shopify/sarama": ("kafka", "kafka", "message_queue"),
    "github.com/twmb/franz-go": ("kafka", "kafka", "message_queue"),
    "github.com/streadway/amqp": ("rabbitmq", "amqp", "message_queue"),
    "github.com/rabbitmq/amqp091-go": ("rabbitmq", "amqp", "message_queue"),
    "github.com/nats-io/nats.go": ("nats", "nats", "message_queue"),
    "cloud.google.com/go/pubsub": ("gcp-pubsub", "http", "message_queue"),
    "github.com/olivere/elastic": ("elasticsearch", "http", "api_call"),
    "github.com/elastic/go-elasticsearch": ("elasticsearch", "http", "api_call"),
    "github.com/opensearch-project/opensearch-go": ("opensearch", "http", "api_call"),
    "google.golang.org/grpc": ("grpc-server", "grpc", "api_call"),
    "github.com/aws/aws-sdk-go": ("aws", "http", "api_call"),
    "github.com/aws/aws-sdk-go-v2": ("aws", "http", "api_call"),
    "cloud.google.com/go/storage": ("gcs", "http", "api_call"),
    "github.com/Azure/azure-sdk-for-go": ("azure", "http", "api_call"),
    "github.com/minio/minio-go": ("minio-s3", "http", "api_call"),
}

RUST_INFRA_DEPS: InfraDepTable = {
    "tokio-postgres": ("postgresql", "postgresql", "shared_database"),
    "sqlx": ("database", "sql", "shared_database"),
    "diesel": ("database", "sql", "shared_database"),
    "sea-orm": ("database", "sql", "shared_database"),
    "mongodb": ("mongodb", "mongodb", "shared_database"),
    "rusqlite": ("sqlite", "sqlite", "shared_database"),
    "redis": ("redis", "redis", "shared_database"),
    "deadpool-redis": ("redis", "redis", "shared_database"),
    "memcache": ("memcached", "memcached", "shared_database"),
    "rdkafka": ("kafka", "kafka", "message_queue"),
    "kafka": ("kafka", "kafka", "message_queue"),
    "lapin": ("rabbitmq", "amqp", "message_queue"),
    "async-nats": ("nats", "nats", "message_queue"),
    "elasticsearch": ("elasticsearch", "http", "api_call"),
    "tonic": ("grpc-server", "grpc", "api_call"),
    "aws-sdk-s3": ("aws-s3", "http", "api_call"),
    "aws-sdk-sqs": ("aws-sqs", "http", "message_queue"),
    "aws-sdk-dynamodb": ("aws-dynamodb", "http", "shared_database"),
}

DOTNET_INFRA_DEPS: InfraDepTable = {
    "Npgsql": ("postgresql", "postgresql", "shared_database"),
    "Npgsql.EntityFrameworkCore.PostgreSQL": ("postgresql", "postgresql", "shared_database"),
    "Microsoft.EntityFrameworkCore.SqlServer": ("sqlserver", "sqlserver", "shared_database"),
    "Microsoft.EntityFrameworkCore.Sqlite": ("sqlite", "sqlite", "shared_database"),
    "MySql.EntityFrameworkCore": ("mysql", "mysql", "shared_database"),
    "Pomelo.EntityFrameworkCore.MySql": ("mysql", "mysql", "shared_database"),
    "MySqlConnector": ("mysql", "mysql", "shared_database"),
    "MongoDB.Driver": ("mongodb", "mongodb", "shared_database"),
    "Oracle.EntityFrameworkCore": ("oracle", "oracle", "shared_database"),
    "CassandraCSharpDriver": ("cassandra", "cql", "shared_database"),
    "Neo4j.Driver": ("neo4j", "bolt", "shared_database"),
    "StackExchange.Redis": ("redis", "redis", "shared_database"),
    "Microsoft.Extensions.Caching.StackExchangeRedis": ("redis", "redis", "shared_database"),
    "Confluent.Kafka": ("kafka", "kafka", "message_queue"),
    "RabbitMQ.Client": ("rabbitmq", "amqp", "message_queue"),
    "MassTransit": ("message-broker", "amqp", "message_queue"),
    "MassTransit.RabbitMQ": ("rabbitmq", "amqp", "message_queue"),
    "MassTransit.Kafka": ("kafka", "kafka", "message_queue"),
    "NATS.Client": ("nats", "nats", "message_queue"),
    "NEST": ("elasticsearch", "http", "api_call"),
    "Elastic.Clients.Elasticsearch": ("elasticsearch", "http", "api_call"),
    "Grpc.Net.Client": ("grpc-server", "grpc", "api_call"),
    "Grpc.AspNetCore": ("grpc-server", "grpc", "api_call"),
    "AWSSDK.S3": ("aws-s3", "http", "api_call"),
    "AWSSDK.SQS": ("aws-sqs", "http", "message_queue"),
    "AWSSDK.DynamoDBv2": ("aws-dynamodb", "http", "shared_database"),
    "Azure.Storage.Blobs": ("azure-blob", "http", "api_call"),
    "Azure.Messaging.ServiceBus": ("azure-servicebus", "amqp", "message_queue"),
    "Google.Cloud.Storage.V1": ("gcs", "http", "api_call"),
    "Google.Cloud.PubSub.V1": ("gcp-pubsub", "http", "message_queue"),
}


# ---------------------------------------------------------------------------
# Table-driven build-dependency matching
# ---------------------------------------------------------------------------


def _match_content_contains(
    dep_table: InfraDepTable,
    content: str,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
    label: str,
    *,
    case_insensitive: bool = False,
    include_dep_in_label: bool = True,
) -> list[IntegrationPoint]:
    """Generic content-substring matcher shared by Gradle, Python, and Go."""
    results: list[IntegrationPoint] = []
    search_content = content.lower() if case_insensitive else content
    for dep_key, (infra_name, protocol, style) in dep_table.items():
        check_key = dep_key.lower() if case_insensitive else dep_key
        if check_key in search_content:
            desc_label = f"{label} '{dep_key}'" if include_dep_in_label else label
            hit = _emit_build_dep(
                comp,
                effective_name,
                seen_keys,
                infra_name,
                protocol,
                style,
                desc_label,
                dep_key,
            )
            if hit:
                results.append(hit)
    return results


def _match_maven_content(
    content: str,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    """Maven matcher — checks artifactId XML tags."""
    results: list[IntegrationPoint] = []
    for artifact_pattern, (infra_name, protocol, style) in MAVEN_INFRA_DEPS.items():
        if f"<artifactId>{artifact_pattern}" in content or (
            artifact_pattern in content
            and re.search(
                rf"<artifactId>[^<]*{re.escape(artifact_pattern)}[^<]*</artifactId>",
                content,
            )
        ):
            hit = _emit_build_dep(
                comp,
                effective_name,
                seen_keys,
                infra_name,
                protocol,
                style,
                "Maven dependency",
                artifact_pattern,
            )
            if hit:
                results.append(hit)
    return results


def _match_npm_json(
    data: dict[str, Any],
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    """npm matcher — checks parsed package.json dependency keys."""
    results: list[IntegrationPoint] = []
    all_deps: set[str] = set()
    for dep_key in ("dependencies", "devDependencies", "peerDependencies"):
        deps = data.get(dep_key, {})
        if isinstance(deps, dict):
            all_deps.update(deps.keys())

    for pkg_name, (infra_name, protocol, style) in NPM_INFRA_DEPS.items():
        if pkg_name in all_deps:
            hit = _emit_build_dep(
                comp,
                effective_name,
                seen_keys,
                infra_name,
                protocol,
                style,
                f"npm dependency '{pkg_name}'",
                pkg_name,
            )
            if hit:
                results.append(hit)
    return results


def _match_regex(
    dep_table: InfraDepTable,
    content: str,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
    label: str,
    *,
    pattern_fn: Any,
) -> list[IntegrationPoint]:
    """Regex-based matcher shared by Rust (Cargo.toml) and .NET (csproj)."""
    results: list[IntegrationPoint] = []
    for dep_key, (infra_name, protocol, style) in dep_table.items():
        if re.search(pattern_fn(dep_key), content, re.MULTILINE | re.IGNORECASE):
            desc_label = f"{label} '{dep_key}'"
            hit = _emit_build_dep(
                comp,
                effective_name,
                seen_keys,
                infra_name,
                protocol,
                style,
                desc_label,
                dep_key,
            )
            if hit:
                results.append(hit)
    return results


def _emit_build_dep(
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
    infra_name: str,
    protocol: str,
    style: IntegrationStyle,
    label: str,
    dep_key: str,
) -> IntegrationPoint | None:
    """Dedup-and-emit helper for all build-dep matchers."""
    key = f"build:{comp.id}:{infra_name}"
    if key in seen_keys:
        return None
    seen_keys.add(key)

    target_id = find_or_create_infra_id(infra_name)
    if target_id == comp.id:
        return None

    intg_id = make_id(
        "intg",
        f"{effective_name}/build-dep/{comp.name}->{infra_name}",
    )
    return IntegrationPoint(
        id=intg_id,
        source_component_id=comp.id,
        target_component_id=target_id,
        style=style,
        protocol=protocol,
        description=f"{label} implies {comp.name} connects to {infra_name}",
        data_flow="bidirectional" if style == "shared_database" else None,
    )


def scan_component_build_deps(
    repo_path: Path,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    """Scan a single component's build files for infrastructure deps."""
    results: list[IntegrationPoint] = []

    for boundary in comp.boundaries:
        comp_dir = repo_path / boundary.path
        if not comp_dir.is_dir() and boundary.path != ".":
            continue
        if boundary.path == ".":
            comp_dir = repo_path

        # Maven
        pom = comp_dir / "pom.xml"
        if pom.is_file():
            content = safe_read_text(pom)
            if content:
                results.extend(_match_maven_content(content, comp, effective_name, seen_keys))

        # Gradle (reuses Maven dep table)
        for gradle_name in ("build.gradle", "build.gradle.kts"):
            gradle = comp_dir / gradle_name
            if gradle.is_file():
                content = safe_read_text(gradle)
                if content:
                    results.extend(
                        _match_content_contains(
                            MAVEN_INFRA_DEPS,
                            content,
                            comp,
                            effective_name,
                            seen_keys,
                            "Gradle dependency",
                            include_dep_in_label=False,
                        )
                    )

        # package.json (npm)
        pkg_json = comp_dir / "package.json"
        if pkg_json.is_file():
            content = safe_read_text(pkg_json)
            if content:
                data = safe_json_load(content)
                if isinstance(data, dict):
                    results.extend(_match_npm_json(data, comp, effective_name, seen_keys))

        # Python
        for py_file in ("pyproject.toml", "requirements.txt", "setup.cfg"):
            pf = comp_dir / py_file
            if pf.is_file():
                content = safe_read_text(pf)
                if content:
                    results.extend(
                        _match_content_contains(
                            PYTHON_INFRA_DEPS,
                            content,
                            comp,
                            effective_name,
                            seen_keys,
                            "Python dependency",
                            case_insensitive=True,
                        )
                    )

        # Go
        gomod = comp_dir / "go.mod"
        if gomod.is_file():
            content = safe_read_text(gomod)
            if content:
                results.extend(
                    _match_content_contains(
                        GO_INFRA_DEPS,
                        content,
                        comp,
                        effective_name,
                        seen_keys,
                        "Go module",
                    )
                )

        # Rust
        cargo = comp_dir / "Cargo.toml"
        if cargo.is_file():
            content = safe_read_text(cargo)
            if content:
                results.extend(
                    _match_regex(
                        RUST_INFRA_DEPS,
                        content,
                        comp,
                        effective_name,
                        seen_keys,
                        "Rust crate",
                        pattern_fn=lambda k: rf"^{re.escape(k)}\s*=",
                    )
                )

        # .NET
        try:
            csproj_files = list(comp_dir.glob("*.csproj"))
        except OSError:
            csproj_files = []
        for csproj in csproj_files:
            content = safe_read_text(csproj)
            if content:
                results.extend(
                    _match_regex(
                        DOTNET_INFRA_DEPS,
                        content,
                        comp,
                        effective_name,
                        seen_keys,
                        ".NET package",
                        pattern_fn=lambda k: rf'Include="{re.escape(k)}"',
                    )
                )

    return results


def discover_build_dep_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Infer infrastructure integrations from build-file dependencies."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name
    seen_keys: set[str] = set()

    for comp in components:
        comp_integrations = scan_component_build_deps(
            repo_path, comp, effective_name, seen_keys
        )
        integrations.extend(comp_integrations)

    if integrations:
        logger.info("Found %d build-dependency integrations", len(integrations))
    return integrations
