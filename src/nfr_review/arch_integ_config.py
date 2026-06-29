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


def _try_add_connection(
    host: str,
    dedup_key: str,
    *,
    protocol: str,
    style: IntegrationStyle,
    description: str,
    id_path: str,
    components: list[Component],
    owner_comp: Component | None,
    effective_name: str,
    env: str | None,
    seen_keys: set[str],
    integrations: list[IntegrationPoint],
    data_flow: str | None = "bidirectional",
) -> None:
    """Shared dedup-resolve-append logic for all protocol matchers."""
    if dedup_key in seen_keys:
        return
    seen_keys.add(dedup_key)

    target_comp = component_by_name(components, host)
    target_id = target_comp.id if target_comp else find_or_create_infra_id(host)
    source_id = owner_comp.id if owner_comp else find_or_create_infra_id(effective_name)

    if source_id == target_id:
        return

    intg_id = make_id("intg", f"{effective_name}/config/{id_path}")
    integrations.append(
        IntegrationPoint(
            id=intg_id,
            source_component_id=source_id,
            target_component_id=target_id,
            style=style,
            protocol=protocol,
            description=description,
            data_flow=data_flow,
            environment=env,
        )
    )


_URL_PROTOCOL_SPECS: list[tuple[re.Pattern[str], str, str, IntegrationStyle, str, int]] = [
    (_REDIS_PATTERN, "redis", "redis", "shared_database", "Redis connection to '{host}'", 1),
    (_AMQP_PATTERN, "rabbitmq", "amqp", "message_queue", "AMQP connection to '{host}'", 1),
    (
        _MONGO_PATTERN,
        "mongodb",
        "mongodb",
        "shared_database",
        "MongoDB connection to '{host}'",
        1,
    ),
    (
        _NATIVE_PG_PATTERN,
        "postgresql",
        "postgresql",
        "shared_database",
        "PostgreSQL connection to '{host}'",
        1,
    ),
    (
        _NATIVE_MYSQL_PATTERN,
        "mysql",
        "mysql",
        "shared_database",
        "MySQL connection to '{host}'",
        1,
    ),
]

_KAFKA_SPEC: tuple[re.Pattern[str], str, str, IntegrationStyle, str, int] = (
    _KAFKA_PATTERN,
    "kafka",
    "kafka",
    "message_queue",
    "Kafka broker at '{host}'",
    1,
)


def _scan_url_protocols(
    content: str,
    *,
    components: list[Component],
    owner_comp: Component | None,
    effective_name: str,
    env: str | None,
    seen_keys: set[str],
    integrations: list[IntegrationPoint],
) -> None:
    """Scan for JDBC and simple URL-protocol connection strings."""
    for match in _JDBC_PATTERN.finditer(content):
        db_type = match.group(1).lower()
        host = match.group(2)
        if is_ignorable_host(host):
            host = db_type
        jdbc_env = env
        if jdbc_env is None and db_type in EMBEDDED_DB_TYPES:
            jdbc_env = "dev"
        _try_add_connection(
            host,
            f"jdbc:{db_type}:{host}",
            protocol=f"jdbc:{db_type}",
            style="shared_database",
            description=f"JDBC connection to {db_type} at '{host}'",
            id_path=f"jdbc/{db_type}/{host}",
            env=jdbc_env,
            components=components,
            owner_comp=owner_comp,
            effective_name=effective_name,
            seen_keys=seen_keys,
            integrations=integrations,
        )

    for pattern, default_host, protocol, style, desc_tpl, group_idx in (
        *_URL_PROTOCOL_SPECS,
        _KAFKA_SPEC,
    ):
        dedup_prefix = protocol
        if protocol == "mysql":
            dedup_prefix = "mysql-native"
        elif protocol == "postgresql":
            dedup_prefix = "pg"
        for match in pattern.finditer(content):
            host = match.group(group_idx)
            if is_ignorable_host(host):
                host = default_host
            _try_add_connection(
                host,
                f"{dedup_prefix}:{host}",
                protocol=protocol,
                style=style,
                description=desc_tpl.format(host=host),
                id_path=f"{protocol}/{host}",
                env=env,
                components=components,
                owner_comp=owner_comp,
                effective_name=effective_name,
                seen_keys=seen_keys,
                integrations=integrations,
            )


def _scan_spring_properties(
    content: str,
    config_file: Path,
    *,
    components: list[Component],
    owner_comp: Component | None,
    effective_name: str,
    env: str | None,
    seen_keys: set[str],
    integrations: list[IntegrationPoint],
) -> None:
    """Scan Spring Boot property patterns for infrastructure connections."""
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
            _try_add_connection(
                host,
                f"spring-prop:{infra_name}:{host}",
                protocol=protocol,
                style=style,
                description=f"Spring property implies connection to {infra_name} at '{host}'",
                id_path=f"spring/{infra_name}/{host}",
                data_flow="bidirectional"
                if style in ("shared_database", "message_queue")
                else None,
                components=components,
                owner_comp=owner_comp,
                effective_name=effective_name,
                env=env,
                seen_keys=seen_keys,
                integrations=integrations,
            )


_HTTP_SCHEMA_SKIP = ("schema", "xmlns", "w3.org", "xmlsoap", ".xsd", "dtd")


def _scan_http_endpoints(
    content: str,
    *,
    components: list[Component],
    owner_comp: Component | None,
    effective_name: str,
    env: str | None,
    seen_keys: set[str],
    integrations: list[IntegrationPoint],
) -> None:
    """Scan for HTTP endpoint URLs, filtering comments and schema URIs."""
    for match in _HTTP_ENDPOINT_PATTERN.finditer(content):
        host = match.group(1)
        if is_ignorable_host(host):
            continue
        if is_comment_line(content, match.start()):
            continue
        full_url = match.group(0)
        if any(skip in full_url.lower() for skip in _HTTP_SCHEMA_SKIP):
            continue
        _try_add_connection(
            host,
            f"http:{host}",
            protocol="http",
            style="api_call",
            description=f"HTTP endpoint at '{host}'",
            id_path=f"http/{host}",
            data_flow=None,
            components=components,
            owner_comp=owner_comp,
            effective_name=effective_name,
            env=env,
            seen_keys=seen_keys,
            integrations=integrations,
        )


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

        owner_comp = _find_owning_component(config_file, repo_path, components)
        env = infer_environment(config_file, repo_path)

        _scan_url_protocols(
            content,
            components=components,
            owner_comp=owner_comp,
            effective_name=effective_name,
            env=env,
            seen_keys=seen_keys,
            integrations=integrations,
        )
        _scan_spring_properties(
            content,
            config_file,
            components=components,
            owner_comp=owner_comp,
            effective_name=effective_name,
            env=env,
            seen_keys=seen_keys,
            integrations=integrations,
        )
        _scan_http_endpoints(
            content,
            components=components,
            owner_comp=owner_comp,
            effective_name=effective_name,
            env=env,
            seen_keys=seen_keys,
            integrations=integrations,
        )

    if integrations:
        logger.info("Found %d config-file connection integrations", len(integrations))
    return integrations
