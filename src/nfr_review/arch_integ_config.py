# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Config-file connection string discovery.

Scans application config files (Spring Boot YAML/properties, .env, appsettings,
etc.) to discover infrastructure integration points -- databases, message
brokers, caches, and HTTP endpoints -- from connection strings and property
patterns.

Strategy extracted from ``arch_integrations``:

* **Strategy 4** -- Config-file connection string discovery
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from nfr_review.arch_models import (
    Component,
    IntegrationPoint,
    IntegrationStyle,
)
from nfr_review.arch_utils import (
    component_by_name,
    find_or_create_infra_id,
    infer_environment,
    is_comment_line,
    is_ignorable_host,
    make_id,
    safe_read_text,
    safe_yaml_load,
)
from nfr_review.path_filter import should_exclude_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants and regex patterns
# ---------------------------------------------------------------------------

EMBEDDED_DB_TYPES = frozenset({"h2", "hsqldb", "derby", "sqlite"})

# Patterns for connection strings in config files
_JDBC_PATTERN = re.compile(r"jdbc:(\w+)://([^/\s:?]+)", re.IGNORECASE)
_REDIS_PATTERN = re.compile(r"redis(?:s)?://([^/\s:?]+)", re.IGNORECASE)
_AMQP_PATTERN = re.compile(r"amqp(?:s)?://([^/\s:?]+)", re.IGNORECASE)
_HTTP_ENDPOINT_PATTERN = re.compile(
    r"https?://([a-zA-Z][a-zA-Z0-9._-]+)(?::\d+)?(?:/\S*)?",
    re.IGNORECASE,
)
_MONGO_PATTERN = re.compile(r"mongodb(?:\+srv)?://([^/\s:?]+)", re.IGNORECASE)
_KAFKA_PATTERN = re.compile(
    r"(?:bootstrap[._-]servers|KAFKA_BROKER\w*)\s*[=:]\s*([a-zA-Z][a-zA-Z0-9._-]+(?::\d+)?)",
    re.IGNORECASE,
)
# Non-JDBC database connection URLs (postgresql://, postgres://, mysql://)
_NATIVE_PG_PATTERN = re.compile(r"postgres(?:ql)?://([^/\s:?@]+)", re.IGNORECASE)
_NATIVE_MYSQL_PATTERN = re.compile(r"mysql://([^/\s:?@]+)", re.IGNORECASE)

# Spring Boot property patterns that imply infrastructure connections
_SPRING_PROPERTY_PATTERNS: list[tuple[re.Pattern[str], str, str, IntegrationStyle]] = [
    (
        re.compile(r"spring\.(?:data\.)?redis\.host\s*[=:]\s*(\S+)", re.IGNORECASE),
        "redis",
        "redis",
        "shared_database",
    ),
    (
        re.compile(r"spring\.kafka\.bootstrap-servers\s*[=:]\s*(\S+)", re.IGNORECASE),
        "kafka",
        "kafka",
        "message_queue",
    ),
    (
        re.compile(r"spring\.rabbitmq\.host\s*[=:]\s*(\S+)", re.IGNORECASE),
        "rabbitmq",
        "amqp",
        "message_queue",
    ),
    (
        re.compile(r"spring\.data\.mongodb\.(?:uri|host)\s*[=:]\s*(\S+)", re.IGNORECASE),
        "mongodb",
        "mongodb",
        "shared_database",
    ),
    (
        re.compile(r"spring\.elasticsearch\.uris?\s*[=:]\s*(\S+)", re.IGNORECASE),
        "elasticsearch",
        "http",
        "api_call",
    ),
    (
        re.compile(r"spring\.mail\.host\s*[=:]\s*(\S+)", re.IGNORECASE),
        "mail-server",
        "smtp",
        "api_call",
    ),
    (
        re.compile(
            r"spring\.data\.cassandra\.contact-points\s*[=:]\s*(\S+)",
            re.IGNORECASE,
        ),
        "cassandra",
        "cql",
        "shared_database",
    ),
    (
        re.compile(r"spring\.neo4j\.uri\s*[=:]\s*(\S+)", re.IGNORECASE),
        "neo4j",
        "bolt",
        "shared_database",
    ),
]

_CONFIG_FILENAMES = (
    "application.yml",
    "application.yaml",
    "application.properties",
    "application-*.yml",
    "application-*.yaml",
    "application-*.properties",
    ".env",
    ".env.*",
    "appsettings.json",
    "appsettings.*.json",
    "config.yml",
    "config.yaml",
    "config.toml",
    "settings.toml",
    "datasources.yml",
    "datasources.yaml",
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_host_from_value(value: str) -> str | None:
    """Extract hostname from a property value (URL, host:port, or plain host)."""
    if value.startswith("${"):
        return None
    for prefix in ("redis://", "rediss://", "http://", "https://", "bolt://"):
        if value.lower().startswith(prefix):
            rest = value[len(prefix) :]
            host_part = rest.split("/")[0].split(":")[0].split("@")[-1]
            return host_part if host_part else None
    host_part = value.split(",")[0].split(":")[0]
    return host_part if host_part else None


def _flatten_yaml_to_properties(data: Any, prefix: str = "") -> str:
    """Flatten a parsed YAML dict into Java-properties-style lines.

    Enables Spring property regex patterns to match YAML config files.
    """
    lines: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                lines.append(_flatten_yaml_to_properties(value, full_key))
            elif isinstance(value, list):
                lines.append(f"{full_key}={','.join(str(v) for v in value)}")
            else:
                lines.append(f"{full_key}={value}")
    return "\n".join(lines)


def _find_owning_component(
    config_file: Path,
    repo_path: Path,
    components: list[Component],
) -> Component | None:
    """Find the component that owns a config file based on path proximity."""
    rel = config_file.relative_to(repo_path)

    # Walk up from the config file's directory to find an owning component
    # by matching against non-root boundary paths.
    for comp in components:
        for boundary in comp.boundaries:
            bp = boundary.path
            if bp == ".":
                continue
            if str(rel).startswith(bp.rstrip("/") + "/") or str(rel.parent) == bp:
                return comp

    # Fallback: pick the root-level repo component regardless of file depth.
    # Spring Boot configs live at src/main/resources/ (depth 4) but belong
    # to the root component, not a Docker Compose infrastructure service.
    for comp in components:
        for boundary in comp.boundaries:
            if boundary.boundary_type == "repo" and boundary.path == ".":
                return comp

    return components[0] if components else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_config_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Scan config files for connection strings and endpoint URLs."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name
    seen_keys: set[str] = set()

    # Gather config files
    config_files: list[Path] = []
    for pattern in _CONFIG_FILENAMES:
        try:
            config_files.extend(repo_path.rglob(pattern))
        except OSError:
            continue

    for config_file in config_files:
        rel_path = str(config_file.relative_to(repo_path))
        if should_exclude_path(rel_path, exclude_test_paths=True):
            continue

        content = safe_read_text(config_file)
        if not content:
            continue

        # Find the owning component for this config file
        owner_comp = _find_owning_component(config_file, repo_path, components)

        # Infer environment from the config filename/path
        env = infer_environment(config_file, repo_path)

        # JDBC connections
        for match in _JDBC_PATTERN.finditer(content):
            db_type = match.group(1).lower()
            host = match.group(2)
            if is_ignorable_host(host):
                host = db_type  # Use DB type as identifier for localhost
            jdbc_env = env
            if jdbc_env is None and db_type in EMBEDDED_DB_TYPES:
                jdbc_env = "dev"
            dedup_key = f"jdbc:{db_type}:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = component_by_name(components, host)
            target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = make_id("intg", f"{effective_name}/config/jdbc/{db_type}/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol=f"jdbc:{db_type}",
                    description=f"JDBC connection to {db_type} at '{host}'",
                    data_flow="bidirectional",
                    environment=jdbc_env,
                )
            )

        # Redis connections
        for match in _REDIS_PATTERN.finditer(content):
            host = match.group(1)
            if is_ignorable_host(host):
                host = "redis"
            dedup_key = f"redis:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = component_by_name(components, host)
            target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = make_id("intg", f"{effective_name}/config/redis/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol="redis",
                    description=f"Redis connection to '{host}'",
                    data_flow="bidirectional",
                    environment=env,
                )
            )

        # AMQP connections
        for match in _AMQP_PATTERN.finditer(content):
            host = match.group(1)
            if is_ignorable_host(host):
                host = "rabbitmq"
            dedup_key = f"amqp:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = component_by_name(components, host)
            target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = make_id("intg", f"{effective_name}/config/amqp/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="message_queue",
                    protocol="amqp",
                    description=f"AMQP connection to '{host}'",
                    data_flow="bidirectional",
                    environment=env,
                )
            )

        # MongoDB connections
        for match in _MONGO_PATTERN.finditer(content):
            host = match.group(1)
            if is_ignorable_host(host):
                host = "mongodb"
            dedup_key = f"mongo:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = component_by_name(components, host)
            target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = make_id("intg", f"{effective_name}/config/mongo/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol="mongodb",
                    description=f"MongoDB connection to '{host}'",
                    data_flow="bidirectional",
                    environment=env,
                )
            )

        # Kafka broker connections
        for match in _KAFKA_PATTERN.finditer(content):
            host = match.group(1)
            if is_ignorable_host(host):
                host = "kafka"
            dedup_key = f"kafka:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = component_by_name(components, host)
            target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = make_id("intg", f"{effective_name}/config/kafka/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="message_queue",
                    protocol="kafka",
                    description=f"Kafka broker at '{host}'",
                    data_flow="bidirectional",
                    environment=env,
                )
            )

        # Native PostgreSQL connections (postgresql:// or postgres://)
        for match in _NATIVE_PG_PATTERN.finditer(content):
            host = match.group(1)
            if is_ignorable_host(host):
                host = "postgresql"
            dedup_key = f"pg:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = component_by_name(components, host)
            target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = make_id("intg", f"{effective_name}/config/pg/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol="postgresql",
                    description=f"PostgreSQL connection to '{host}'",
                    data_flow="bidirectional",
                    environment=env,
                )
            )

        # Native MySQL connections (mysql://)
        for match in _NATIVE_MYSQL_PATTERN.finditer(content):
            host = match.group(1)
            if is_ignorable_host(host):
                host = "mysql"
            dedup_key = f"mysql-native:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = component_by_name(components, host)
            target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = make_id("intg", f"{effective_name}/config/mysql/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol="mysql",
                    description=f"MySQL connection to '{host}'",
                    data_flow="bidirectional",
                    environment=env,
                )
            )

        # Spring Boot property-based connections
        # For YAML files, also flatten to properties format so regexes match
        search_content = content
        if config_file.suffix in (".yml", ".yaml"):
            parsed = safe_yaml_load(content)
            if isinstance(parsed, dict):
                flattened = _flatten_yaml_to_properties(parsed)
                search_content = content + "\n" + flattened
        for pat, infra_name, protocol, style in _SPRING_PROPERTY_PATTERNS:
            for match in pat.finditer(search_content):
                raw_val = match.group(1).strip()
                host = _extract_host_from_value(raw_val)
                if not host or is_ignorable_host(host):
                    host = infra_name
                dedup_key = f"spring-prop:{infra_name}:{host}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                target_comp = component_by_name(components, host)
                target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
                source_id = (
                    owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)
                )

                if source_id == target_id:
                    continue

                intg_id = make_id(
                    "intg",
                    f"{effective_name}/config/spring/{infra_name}/{host}",
                )
                integrations.append(
                    IntegrationPoint(
                        id=intg_id,
                        source_component_id=source_id,
                        target_component_id=target_id,
                        style=style,
                        protocol=protocol,
                        description=(
                            f"Spring property implies connection to {infra_name} at '{host}'"
                        ),
                        data_flow="bidirectional"
                        if style in ("shared_database", "message_queue")
                        else None,
                        environment=env,
                    )
                )

        # HTTP endpoint connections (only for meaningful hosts)
        for match in _HTTP_ENDPOINT_PATTERN.finditer(content):
            host = match.group(1)
            if is_ignorable_host(host):
                continue
            # Skip matches inside comment lines
            if is_comment_line(content, match.start()):
                continue
            # Skip schema/namespace URLs
            full_url = match.group(0)
            if any(
                skip in full_url.lower()
                for skip in (
                    "schema",
                    "xmlns",
                    "w3.org",
                    "xmlsoap",
                    ".xsd",
                    "dtd",
                )
            ):
                continue

            dedup_key = f"http:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = component_by_name(components, host)
            target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = make_id("intg", f"{effective_name}/config/http/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="api_call",
                    protocol="http",
                    description=f"HTTP endpoint at '{host}'",
                    environment=env,
                )
            )

    if integrations:
        logger.info("Found %d config-file connection integrations", len(integrations))
    return integrations
