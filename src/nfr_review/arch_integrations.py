# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration point and scenario discovery for architecture documentation.

Scans K8s manifests, Docker Compose files, build configs, and application
config files to discover integration points between components. Operates
without LLM — pure structural inference.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.arch_models import Component, IntegrationPoint, IntegrationStyle
from nfr_review.path_filter import should_exclude_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (mirror arch_discovery patterns)
# ---------------------------------------------------------------------------


def _safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


def _safe_yaml_load(text: str) -> Any:
    _yaml = YAML(typ="safe")
    try:
        return _yaml.load(text)
    except YAMLError:
        return None


def _safe_yaml_load_all(text: str) -> list[Any]:
    _yaml = YAML(typ="safe")
    try:
        return [doc for doc in _yaml.load_all(text) if doc is not None]
    except YAMLError:
        return []


def _safe_json_load(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _make_id(prefix: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    short_hash = hashlib.sha256(name.encode()).hexdigest()[:6]
    return f"{prefix}-{slug}-{short_hash}"


# ---------------------------------------------------------------------------
# Component lookup helpers
# ---------------------------------------------------------------------------


def _component_by_name(components: list[Component], name: str) -> Component | None:
    """Find a component by exact name (case-insensitive)."""
    name_lower = name.lower()
    for comp in components:
        if comp.name.lower() == name_lower:
            return comp
    return None


def _component_by_k8s_selector(
    components: list[Component], selector: dict[str, str]
) -> Component | None:
    """Find a component whose name matches a K8s label selector's 'app' label."""
    app_label = selector.get("app") or selector.get("app.kubernetes.io/name")
    if not app_label:
        return None
    return _component_by_name(components, app_label)


def _find_or_create_infra_id(name: str) -> str:
    """Generate a stable ID for an inferred infrastructure component."""
    return _make_id("infra", name)


# ---------------------------------------------------------------------------
# Strategy 1: K8s Service -> Deployment mapping
# ---------------------------------------------------------------------------

_K8S_DIRS = ("k8s", "kubernetes", "deploy", "manifests", "helm")


def _discover_k8s_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Parse K8s Service manifests to find Service->Deployment integrations."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    search_dirs = [repo_path / d for d in _K8S_DIRS if (repo_path / d).is_dir()]
    search_dirs.append(repo_path)

    # Collect services and deployments from manifests
    k8s_services: list[dict[str, Any]] = []  # [{name, selector, namespace}]
    k8s_workloads: list[dict[str, Any]] = []  # [{name, labels, kind}]

    for search_dir in search_dirs:
        try:
            yaml_files = list(search_dir.rglob("*.yaml")) + list(search_dir.rglob("*.yml"))
        except OSError:
            continue

        for yaml_file in yaml_files:
            rel_path = str(yaml_file.relative_to(repo_path))
            if should_exclude_path(rel_path):
                continue

            content = _safe_read_text(yaml_file)
            if not content:
                continue

            docs = _safe_yaml_load_all(content)
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                kind = doc.get("kind", "")
                metadata = doc.get("metadata", {})
                if not isinstance(metadata, dict):
                    continue
                name = metadata.get("name", "")
                if not name:
                    continue

                if kind == "Service":
                    spec = doc.get("spec", {}) or {}
                    selector = spec.get("selector", {}) or {}
                    if isinstance(selector, dict):
                        k8s_services.append(
                            {
                                "name": name,
                                "selector": selector,
                                "namespace": metadata.get("namespace", "default"),
                            }
                        )
                elif kind in ("Deployment", "StatefulSet", "DaemonSet"):
                    labels = metadata.get("labels", {}) or {}
                    # Also check pod template labels
                    spec = doc.get("spec", {}) or {}
                    template = spec.get("template", {}) or {}
                    tmpl_metadata = template.get("metadata", {}) or {}
                    pod_labels = tmpl_metadata.get("labels", {}) or {}
                    merged_labels = {**labels, **pod_labels}

                    k8s_workloads.append({"name": name, "labels": merged_labels, "kind": kind})

    # Match services to workloads via selector
    for svc in k8s_services:
        selector = svc["selector"]
        if not selector:
            continue

        for workload in k8s_workloads:
            # All selector labels must match workload labels
            if all(workload["labels"].get(k) == v for k, v in selector.items()):
                # Find the corresponding components
                svc_comp = _component_by_name(components, svc["name"])
                wl_comp = _component_by_name(components, workload["name"])

                if wl_comp is None:
                    # Try matching by app label
                    wl_comp = _component_by_k8s_selector(components, workload["labels"])

                if svc_comp and wl_comp and svc_comp.id != wl_comp.id:
                    intg_id = _make_id(
                        "intg",
                        f"{effective_name}/k8s/{svc['name']}->{workload['name']}",
                    )
                    integrations.append(
                        IntegrationPoint(
                            id=intg_id,
                            source_component_id=svc_comp.id,
                            target_component_id=wl_comp.id,
                            style="synchronous",
                            protocol="http",
                            description=(
                                f"K8s Service '{svc['name']}' routes to "
                                f"{workload['kind']} '{workload['name']}'"
                            ),
                        )
                    )
                elif svc_comp is None and wl_comp:
                    # Service exists in manifest but not as a component —
                    # create integration from the workload perspective
                    pass
                elif svc_comp and wl_comp is None:
                    # Workload not found as a component
                    pass

    if integrations:
        logger.info("Found %d K8s service-to-workload integrations", len(integrations))
    return integrations


# ---------------------------------------------------------------------------
# Strategy 2: Docker Compose network links
# ---------------------------------------------------------------------------

_COMPOSE_FILENAMES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)


def _discover_compose_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Parse docker-compose depends_on, links, and shared networks."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    for compose_name in _COMPOSE_FILENAMES:
        compose_file = repo_path / compose_name
        if not compose_file.is_file():
            continue

        content = _safe_read_text(compose_file)
        if not content:
            continue

        data = _safe_yaml_load(content)
        if not isinstance(data, dict):
            continue

        services = data.get("services", {})
        if not isinstance(services, dict):
            continue

        seen_pairs: set[tuple[str, str]] = set()

        for svc_name, svc_config in services.items():
            if not isinstance(svc_config, dict):
                continue

            source_comp = _component_by_name(components, svc_name)
            if source_comp is None:
                continue

            # depends_on
            depends_on = svc_config.get("depends_on", [])
            dep_names: list[str] = []
            if isinstance(depends_on, list):
                dep_names = [d for d in depends_on if isinstance(d, str)]
            elif isinstance(depends_on, dict):
                dep_names = list(depends_on.keys())

            for dep_name in dep_names:
                target_comp = _component_by_name(components, dep_name)
                if target_comp is None or target_comp.id == source_comp.id:
                    continue
                pair = (source_comp.id, target_comp.id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                intg_id = _make_id(
                    "intg",
                    f"{effective_name}/compose/depends/{svc_name}->{dep_name}",
                )
                integrations.append(
                    IntegrationPoint(
                        id=intg_id,
                        source_component_id=source_comp.id,
                        target_component_id=target_comp.id,
                        style="synchronous",
                        description=(f"Compose service '{svc_name}' depends on '{dep_name}'"),
                    )
                )

            # links
            links = svc_config.get("links", [])
            if isinstance(links, list):
                for link in links:
                    if not isinstance(link, str):
                        continue
                    # links can be "service" or "service:alias"
                    link_target = link.split(":")[0]
                    target_comp = _component_by_name(components, link_target)
                    if target_comp is None or target_comp.id == source_comp.id:
                        continue
                    pair = (source_comp.id, target_comp.id)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)

                    intg_id = _make_id(
                        "intg",
                        f"{effective_name}/compose/link/{svc_name}->{link_target}",
                    )
                    integrations.append(
                        IntegrationPoint(
                            id=intg_id,
                            source_component_id=source_comp.id,
                            target_component_id=target_comp.id,
                            style="synchronous",
                            description=(f"Compose link from '{svc_name}' to '{link_target}'"),
                        )
                    )

        # Shared networks — services on the same non-default network
        networks_section = data.get("networks", {})
        if isinstance(networks_section, dict):
            network_members: dict[str, list[str]] = {}
            for svc_name, svc_config in services.items():
                if not isinstance(svc_config, dict):
                    continue
                svc_networks = svc_config.get("networks", [])
                if isinstance(svc_networks, list):
                    for net in svc_networks:
                        if isinstance(net, str):
                            network_members.setdefault(net, []).append(svc_name)
                elif isinstance(svc_networks, dict):
                    for net in svc_networks:
                        network_members.setdefault(net, []).append(svc_name)

            for net_name, members in network_members.items():
                if len(members) < 2:
                    continue
                for i, src_name in enumerate(members):
                    for tgt_name in members[i + 1 :]:
                        src_comp = _component_by_name(components, src_name)
                        tgt_comp = _component_by_name(components, tgt_name)
                        if src_comp is None or tgt_comp is None or src_comp.id == tgt_comp.id:
                            continue
                        pair = (src_comp.id, tgt_comp.id)
                        reverse_pair = (tgt_comp.id, src_comp.id)
                        if pair in seen_pairs or reverse_pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)

                        intg_id = _make_id(
                            "intg",
                            f"{effective_name}/compose/network/{net_name}/{src_name}<->{tgt_name}",
                        )
                        integrations.append(
                            IntegrationPoint(
                                id=intg_id,
                                source_component_id=src_comp.id,
                                target_component_id=tgt_comp.id,
                                style="synchronous",
                                protocol="tcp",
                                description=(
                                    f"Shared Compose network '{net_name}' "
                                    f"connects '{src_name}' and '{tgt_name}'"
                                ),
                            )
                        )

        break  # Only process first compose file found

    if integrations:
        logger.info("Found %d Docker Compose integrations", len(integrations))
    return integrations


# ---------------------------------------------------------------------------
# Strategy 3: Maven / Gradle inter-module dependencies
# ---------------------------------------------------------------------------


def _parse_maven_coordinates(pom_text: str) -> dict[str, str]:
    """Extract groupId and artifactId from a POM file."""
    result: dict[str, str] = {}
    gid_match = re.search(r"<groupId>([^<]+)</groupId>", pom_text)
    aid_match = re.search(r"<artifactId>([^<]+)</artifactId>", pom_text)
    if gid_match:
        result["groupId"] = gid_match.group(1).strip()
    if aid_match:
        result["artifactId"] = aid_match.group(1).strip()
    return result


def _discover_maven_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Find inter-module Maven dependencies (sibling module references)."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    root_pom = repo_path / "pom.xml"
    if not root_pom.is_file():
        return []

    root_content = _safe_read_text(root_pom)
    if not root_content:
        return []

    # Find declared modules
    module_pattern = re.compile(r"<module>([^<]+)</module>")
    modules = module_pattern.findall(root_content)
    if not modules:
        return []

    # Build a map of groupId:artifactId -> component for sibling modules
    module_coords: dict[str, str] = {}  # "groupId:artifactId" -> module_name
    # Also extract root groupId as default
    root_coords = _parse_maven_coordinates(root_content)
    root_gid = root_coords.get("groupId", "")

    for module_name in modules:
        module_pom = repo_path / module_name / "pom.xml"
        if not module_pom.is_file():
            continue
        mod_content = _safe_read_text(module_pom)
        if not mod_content:
            continue

        coords = _parse_maven_coordinates(mod_content)
        gid = coords.get("groupId", root_gid)
        aid = coords.get("artifactId", module_name)
        module_coords[f"{gid}:{aid}"] = module_name

    # Now scan each module's dependencies for references to siblings
    dep_pattern = re.compile(
        r"<dependency>\s*"
        r"<groupId>([^<]+)</groupId>\s*"
        r"<artifactId>([^<]+)</artifactId>",
        re.DOTALL,
    )

    for module_name in modules:
        module_pom = repo_path / module_name / "pom.xml"
        if not module_pom.is_file():
            continue
        mod_content = _safe_read_text(module_pom)
        if not mod_content:
            continue

        source_comp = _component_by_name(components, module_name)
        if source_comp is None:
            continue

        for dep_match in dep_pattern.finditer(mod_content):
            dep_gid = dep_match.group(1).strip()
            dep_aid = dep_match.group(2).strip()
            dep_key = f"{dep_gid}:{dep_aid}"

            target_module = module_coords.get(dep_key)
            if target_module is None or target_module == module_name:
                continue

            target_comp = _component_by_name(components, target_module)
            if target_comp is None:
                continue

            intg_id = _make_id(
                "intg",
                f"{effective_name}/maven/{module_name}->{target_module}",
            )
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_comp.id,
                    target_component_id=target_comp.id,
                    style="api_call",
                    protocol="jvm",
                    description=(
                        f"Maven module '{module_name}' depends on "
                        f"'{target_module}' ({dep_key})"
                    ),
                )
            )

    if integrations:
        logger.info("Found %d Maven inter-module integrations", len(integrations))
    return integrations


def _discover_gradle_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Find Gradle project(':sub') dependencies between sub-projects."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    # Find sub-projects from settings file
    settings_file = None
    for name in ("settings.gradle", "settings.gradle.kts"):
        candidate = repo_path / name
        if candidate.is_file():
            settings_file = candidate
            break

    if settings_file is None:
        return []

    settings_content = _safe_read_text(settings_file)
    if not settings_content:
        return []

    include_pattern = re.compile(r"""include\s*\(?\s*['"]([^'"]+)['"]\s*\)?""")
    project_names: list[str] = []
    for match in include_pattern.finditer(settings_content):
        project_names.append(match.group(1).lstrip(":"))

    # Scan each sub-project's build file for project(':...') dependencies
    project_dep_pattern = re.compile(
        r"""(?:implementation|api|compile|compileOnly|runtimeOnly|testImplementation)"""
        r"""[\s(]*project\s*\(\s*['":]+([^'")\s]+)['")]+""",
    )

    for proj_name in project_names:
        proj_dir = repo_path / proj_name.replace(":", "/")
        if not proj_dir.is_dir():
            continue

        for build_name in ("build.gradle", "build.gradle.kts"):
            build_file = proj_dir / build_name
            if not build_file.is_file():
                continue

            build_content = _safe_read_text(build_file)
            if not build_content:
                continue

            source_comp = _component_by_name(components, proj_name)
            if source_comp is None:
                continue

            for dep_match in project_dep_pattern.finditer(build_content):
                dep_project = dep_match.group(1).lstrip(":").replace(":", "/")
                target_comp = _component_by_name(components, dep_project)
                if target_comp is None or target_comp.id == source_comp.id:
                    continue

                intg_id = _make_id(
                    "intg",
                    f"{effective_name}/gradle/{proj_name}->{dep_project}",
                )
                integrations.append(
                    IntegrationPoint(
                        id=intg_id,
                        source_component_id=source_comp.id,
                        target_component_id=target_comp.id,
                        style="api_call",
                        protocol="jvm",
                        description=(
                            f"Gradle project '{proj_name}' depends on project '{dep_project}'"
                        ),
                    )
                )

            break  # Only process first build file found per sub-project

    if integrations:
        logger.info("Found %d Gradle inter-project integrations", len(integrations))
    return integrations


# ---------------------------------------------------------------------------
# Strategy 4: Config-file connection string discovery
# ---------------------------------------------------------------------------

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

# Hosts that are not meaningful integration targets
_IGNORED_HOSTS = frozenset(
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


def _is_ignorable_host(host: str) -> bool:
    """Return True if the host is a generic/non-meaningful target."""
    host_lower = host.lower()
    return host_lower in _IGNORED_HOSTS or host_lower.startswith("$")


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


def _infer_style_from_protocol(protocol: str) -> IntegrationStyle:
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


def _discover_config_integrations(
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

        content = _safe_read_text(config_file)
        if not content:
            continue

        # Find the owning component for this config file
        owner_comp = _find_owning_component(config_file, repo_path, components)

        # JDBC connections
        for match in _JDBC_PATTERN.finditer(content):
            db_type = match.group(1).lower()
            host = match.group(2)
            if _is_ignorable_host(host):
                host = db_type  # Use DB type as identifier for localhost
            dedup_key = f"jdbc:{db_type}:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = _component_by_name(components, host)
            target_id = target_comp.id if target_comp else _find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else _find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = _make_id("intg", f"{effective_name}/config/jdbc/{db_type}/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol=f"jdbc:{db_type}",
                    description=f"JDBC connection to {db_type} at '{host}'",
                    data_flow="bidirectional",
                )
            )

        # Redis connections
        for match in _REDIS_PATTERN.finditer(content):
            host = match.group(1)
            if _is_ignorable_host(host):
                host = "redis"
            dedup_key = f"redis:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = _component_by_name(components, host)
            target_id = target_comp.id if target_comp else _find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else _find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = _make_id("intg", f"{effective_name}/config/redis/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol="redis",
                    description=f"Redis connection to '{host}'",
                    data_flow="bidirectional",
                )
            )

        # AMQP connections
        for match in _AMQP_PATTERN.finditer(content):
            host = match.group(1)
            if _is_ignorable_host(host):
                host = "rabbitmq"
            dedup_key = f"amqp:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = _component_by_name(components, host)
            target_id = target_comp.id if target_comp else _find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else _find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = _make_id("intg", f"{effective_name}/config/amqp/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="message_queue",
                    protocol="amqp",
                    description=f"AMQP connection to '{host}'",
                    data_flow="bidirectional",
                )
            )

        # MongoDB connections
        for match in _MONGO_PATTERN.finditer(content):
            host = match.group(1)
            if _is_ignorable_host(host):
                host = "mongodb"
            dedup_key = f"mongo:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = _component_by_name(components, host)
            target_id = target_comp.id if target_comp else _find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else _find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = _make_id("intg", f"{effective_name}/config/mongo/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol="mongodb",
                    description=f"MongoDB connection to '{host}'",
                    data_flow="bidirectional",
                )
            )

        # Kafka broker connections
        for match in _KAFKA_PATTERN.finditer(content):
            host = match.group(1)
            if _is_ignorable_host(host):
                host = "kafka"
            dedup_key = f"kafka:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = _component_by_name(components, host)
            target_id = target_comp.id if target_comp else _find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else _find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = _make_id("intg", f"{effective_name}/config/kafka/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="message_queue",
                    protocol="kafka",
                    description=f"Kafka broker at '{host}'",
                    data_flow="bidirectional",
                )
            )

        # Native PostgreSQL connections (postgresql:// or postgres://)
        for match in _NATIVE_PG_PATTERN.finditer(content):
            host = match.group(1)
            if _is_ignorable_host(host):
                host = "postgresql"
            dedup_key = f"pg:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = _component_by_name(components, host)
            target_id = target_comp.id if target_comp else _find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else _find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = _make_id("intg", f"{effective_name}/config/pg/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol="postgresql",
                    description=f"PostgreSQL connection to '{host}'",
                    data_flow="bidirectional",
                )
            )

        # Native MySQL connections (mysql://)
        for match in _NATIVE_MYSQL_PATTERN.finditer(content):
            host = match.group(1)
            if _is_ignorable_host(host):
                host = "mysql"
            dedup_key = f"mysql-native:{host}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            target_comp = _component_by_name(components, host)
            target_id = target_comp.id if target_comp else _find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else _find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = _make_id("intg", f"{effective_name}/config/mysql/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="shared_database",
                    protocol="mysql",
                    description=f"MySQL connection to '{host}'",
                    data_flow="bidirectional",
                )
            )

        # Spring Boot property-based connections
        # For YAML files, also flatten to properties format so regexes match
        search_content = content
        if config_file.suffix in (".yml", ".yaml"):
            parsed = _safe_yaml_load(content)
            if isinstance(parsed, dict):
                flattened = _flatten_yaml_to_properties(parsed)
                search_content = content + "\n" + flattened
        for pat, infra_name, protocol, style in _SPRING_PROPERTY_PATTERNS:
            for match in pat.finditer(search_content):
                raw_val = match.group(1).strip()
                host = _extract_host_from_value(raw_val)
                if not host or _is_ignorable_host(host):
                    host = infra_name
                dedup_key = f"spring-prop:{infra_name}:{host}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                target_comp = _component_by_name(components, host)
                target_id = target_comp.id if target_comp else _find_or_create_infra_id(host)
                source_id = (
                    owner_comp.id if owner_comp else _find_or_create_infra_id(effective_name)
                )

                if source_id == target_id:
                    continue

                intg_id = _make_id(
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
                    )
                )

        # HTTP endpoint connections (only for meaningful hosts)
        for match in _HTTP_ENDPOINT_PATTERN.finditer(content):
            host = match.group(1)
            if _is_ignorable_host(host):
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

            target_comp = _component_by_name(components, host)
            target_id = target_comp.id if target_comp else _find_or_create_infra_id(host)
            source_id = (
                owner_comp.id if owner_comp else _find_or_create_infra_id(effective_name)
            )

            if source_id == target_id:
                continue

            intg_id = _make_id("intg", f"{effective_name}/config/http/{host}")
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_id,
                    target_component_id=target_id,
                    style="api_call",
                    protocol="http",
                    description=f"HTTP endpoint at '{host}'",
                )
            )

    if integrations:
        logger.info("Found %d config-file connection integrations", len(integrations))
    return integrations


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
# Strategy 5: Docker Compose env-var cross-referencing
# ---------------------------------------------------------------------------

# Env var names that typically hold service addresses
_ADDR_ENV_SUFFIXES = ("_ADDR", "_HOST", "_URL", "_SERVICE_ADDR", "_ENDPOINT")


def _discover_compose_env_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Parse Docker Compose environment variables to find service-to-service references.

    Detects patterns like ``CART_ADDR=cart:7070`` or ``KAFKA_ADDR`` (resolved
    from ``.env``) that reference other compose service names.
    """
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    for compose_name in _COMPOSE_FILENAMES:
        compose_file = repo_path / compose_name
        if not compose_file.is_file():
            continue

        content = _safe_read_text(compose_file)
        if not content:
            continue

        data = _safe_yaml_load(content)
        if not isinstance(data, dict):
            continue

        services = data.get("services", {})
        if not isinstance(services, dict):
            continue

        service_names = {s.lower() for s in services}

        # Load .env file if present for variable resolution
        env_vars = _load_dotenv(repo_path)

        seen_pairs: set[tuple[str, str]] = set()

        for svc_name, svc_config in services.items():
            if not isinstance(svc_config, dict):
                continue

            source_comp = _component_by_name(components, svc_name)
            if source_comp is None:
                continue

            env_list = svc_config.get("environment", [])
            env_entries: list[tuple[str, str]] = []
            if isinstance(env_list, list):
                for entry in env_list:
                    if not isinstance(entry, str):
                        continue
                    if "=" in entry:
                        k, _, v = entry.partition("=")
                        env_entries.append((k.strip(), v.strip()))
                    else:
                        # Bare variable name — resolve from .env
                        resolved = env_vars.get(entry.strip(), "")
                        env_entries.append((entry.strip(), resolved))
            elif isinstance(env_list, dict):
                for k, v in env_list.items():
                    env_entries.append((str(k), str(v) if v is not None else ""))

            for env_key, env_val in env_entries:
                if not any(env_key.upper().endswith(sfx) for sfx in _ADDR_ENV_SUFFIXES):
                    continue

                # Extract the target service name from the value
                target_name = _extract_service_ref(env_val, service_names, env_vars)
                if not target_name:
                    continue

                target_comp = _component_by_name(components, target_name)
                if target_comp is None or target_comp.id == source_comp.id:
                    continue

                pair = (source_comp.id, target_comp.id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                protocol = _guess_protocol_from_env(env_key, env_val)
                style = _infer_style_from_protocol(protocol)

                intg_id = _make_id(
                    "intg",
                    f"{effective_name}/compose-env/{svc_name}->{target_name}",
                )
                integrations.append(
                    IntegrationPoint(
                        id=intg_id,
                        source_component_id=source_comp.id,
                        target_component_id=target_comp.id,
                        style=style,
                        protocol=protocol,
                        description=(
                            f"Compose service '{svc_name}' references "
                            f"'{target_name}' via env {env_key}"
                        ),
                    )
                )

        break  # Only process first compose file found

    if integrations:
        logger.info("Found %d Docker Compose env-var integrations", len(integrations))
    return integrations


def _load_dotenv(repo_path: Path) -> dict[str, str]:
    """Load key=value pairs from .env file if present."""
    env_vars: dict[str, str] = {}
    env_file = repo_path / ".env"
    if not env_file.is_file():
        return env_vars
    content = _safe_read_text(env_file)
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


def _extract_service_ref(
    value: str,
    service_names: set[str],
    env_vars: dict[str, str],
) -> str | None:
    """Extract a compose service name from an env var value.

    Handles formats like ``cart:7070``, ``http://cart:7070``,
    ``${CART_ADDR}`` (resolved from .env), or bare service names.
    """
    if not value:
        return None

    # Resolve ${VAR} references
    resolved = _resolve_env_refs(value, env_vars)

    # Strip protocol prefix
    resolved = re.sub(r"^https?://", "", resolved)

    # Extract hostname (before : or /)
    host_match = re.match(r"([a-zA-Z][a-zA-Z0-9_-]*)", resolved)
    if not host_match:
        return None

    candidate = host_match.group(1).lower()
    if candidate in service_names:
        return candidate

    # Try matching with hyphens converted to underscores and vice versa
    for svc in service_names:
        if candidate.replace("-", "_") == svc.replace("-", "_"):
            return svc
        if candidate.replace("_", "-") == svc.replace("_", "-"):
            return svc

    return None


def _resolve_env_refs(value: str, env_vars: dict[str, str], depth: int = 3) -> str:
    """Resolve ``${VAR}`` references in a string using env_vars dict."""
    if depth <= 0 or "${" not in value:
        return value

    def _replace(m: re.Match[str]) -> str:
        return env_vars.get(m.group(1), m.group(0))

    resolved = re.sub(r"\$\{([^}:]+)(?::[^}]*)?\}", _replace, value)
    if resolved != value:
        return _resolve_env_refs(resolved, env_vars, depth - 1)
    return resolved


def _guess_protocol_from_env(key: str, value: str) -> str:
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
# Strategy 6: K8s manifest env-var cross-referencing
# ---------------------------------------------------------------------------


def _discover_k8s_env_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Parse K8s deployment env vars to find service-to-service references.

    Detects patterns like ``PRODUCT_CATALOG_SERVICE_ADDR: productcatalogservice:3550``
    in deployment manifests.
    """
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    # Build a set of known component names for matching
    comp_names = {c.name.lower() for c in components}

    search_dirs = [repo_path / d for d in _K8S_DIRS if (repo_path / d).is_dir()]
    if not search_dirs:
        search_dirs = [repo_path]

    seen_pairs: set[tuple[str, str]] = set()

    for search_dir in search_dirs:
        try:
            yaml_files = list(search_dir.rglob("*.yaml")) + list(search_dir.rglob("*.yml"))
        except OSError:
            continue

        for yaml_file in yaml_files:
            rel_path = str(yaml_file.relative_to(repo_path))
            if should_exclude_path(rel_path):
                continue

            content = _safe_read_text(yaml_file)
            if not content:
                continue

            docs = _safe_yaml_load_all(content)
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                kind = doc.get("kind", "")
                if kind not in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
                    continue

                metadata = doc.get("metadata", {})
                if not isinstance(metadata, dict):
                    continue
                workload_name = metadata.get("name", "")
                if not workload_name:
                    continue

                source_comp = _component_by_name(components, workload_name)
                if source_comp is None:
                    # Try matching by app label
                    labels = metadata.get("labels", {}) or {}
                    source_comp = _component_by_k8s_selector(components, labels)
                if source_comp is None:
                    continue

                # Extract env vars from all containers
                containers = _extract_k8s_containers(doc)
                for env_key, env_val in containers:
                    if not any(env_key.upper().endswith(sfx) for sfx in _ADDR_ENV_SUFFIXES):
                        continue

                    target_name = _extract_k8s_service_ref(env_val, comp_names)
                    if not target_name:
                        continue

                    target_comp = _component_by_name(components, target_name)
                    if target_comp is None or target_comp.id == source_comp.id:
                        continue

                    pair = (source_comp.id, target_comp.id)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)

                    protocol = _guess_protocol_from_env(env_key, env_val)
                    style = _infer_style_from_protocol(protocol)

                    intg_id = _make_id(
                        "intg",
                        f"{effective_name}/k8s-env/{workload_name}->{target_name}",
                    )
                    integrations.append(
                        IntegrationPoint(
                            id=intg_id,
                            source_component_id=source_comp.id,
                            target_component_id=target_comp.id,
                            style=style,
                            protocol=protocol,
                            description=(
                                f"K8s {kind} '{workload_name}' references "
                                f"'{target_name}' via env {env_key}"
                            ),
                        )
                    )

    if integrations:
        logger.info("Found %d K8s env-var integrations", len(integrations))
    return integrations


def _extract_k8s_containers(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract (env_key, env_value) pairs from all containers in a K8s workload."""
    results: list[tuple[str, str]] = []
    spec = doc.get("spec", {}) or {}
    template = spec.get("template", {}) or {}
    pod_spec = template.get("spec", {}) or {}

    for container_list_key in ("containers", "initContainers"):
        containers = pod_spec.get(container_list_key, []) or []
        for container in containers:
            if not isinstance(container, dict):
                continue
            env_list = container.get("env", []) or []
            for env_entry in env_list:
                if not isinstance(env_entry, dict):
                    continue
                name = env_entry.get("name", "")
                value = env_entry.get("value", "")
                if name and value and isinstance(value, str):
                    results.append((name, value))
    return results


def _extract_k8s_service_ref(value: str, comp_names: set[str]) -> str | None:
    """Extract a K8s service name from an env var value like ``servicename:3550``."""
    if not value:
        return None

    # Strip protocol prefix
    cleaned = re.sub(r"^https?://", "", value)

    # Extract hostname before : or /
    host_match = re.match(r"([a-zA-Z][a-zA-Z0-9_-]*)", cleaned)
    if not host_match:
        return None

    candidate = host_match.group(1).lower()
    if _is_ignorable_host(candidate):
        return None

    if candidate in comp_names:
        return candidate

    # Try stripping common suffixes like "service"
    for suffix in ("service", "svc"):
        stripped = candidate.removesuffix(suffix)
        if stripped != candidate and stripped in comp_names:
            return stripped

    return None


# ---------------------------------------------------------------------------
# Strategy 7: gRPC proto service definitions
# ---------------------------------------------------------------------------


def _discover_grpc_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Parse .proto files to find gRPC service definitions and map to components."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    try:
        proto_files = list(repo_path.rglob("*.proto"))
    except OSError:
        return []

    # Collect service definitions from proto files
    service_pattern = re.compile(r"^service\s+(\w+)\s*\{", re.MULTILINE)

    # Build proto service name -> component mapping
    proto_services: dict[str, str] = {}  # ProtoServiceName -> proto_file_path
    for pf in proto_files:
        rel_path = str(pf.relative_to(repo_path))
        if should_exclude_path(rel_path):
            continue
        content = _safe_read_text(pf)
        if not content:
            continue
        for match in service_pattern.finditer(content):
            proto_services[match.group(1)] = rel_path

    if not proto_services:
        return []

    # Map proto service names to components
    comp_names_lower = {c.name.lower(): c for c in components}

    def _match_proto_to_component(proto_svc_name: str) -> Component | None:
        """Match a proto service name like 'CartService' to a component like 'cartservice'."""
        # Direct match
        lower = proto_svc_name.lower()
        if lower in comp_names_lower:
            return comp_names_lower[lower]
        # Strip 'Service' suffix
        stripped = lower.removesuffix("service")
        if stripped in comp_names_lower:
            return comp_names_lower[stripped]
        # Try with common naming patterns
        for comp_lower, comp in comp_names_lower.items():
            if comp_lower.replace("-", "").replace("_", "") == stripped:
                return comp
            if comp_lower.replace("-", "").replace("_", "") == lower:
                return comp
        return None

    # For each component's source code, check which proto services it calls.
    # Skip components whose boundary is the repo root — they'd scan every
    # file and produce false cartesian-product matches.
    for comp in components:
        scan_dir = _resolve_grpc_scan_dir(repo_path, comp)
        if scan_dir is None:
            continue

        called_services = _scan_for_grpc_clients(scan_dir, proto_services)
        for called_svc in called_services:
            target_comp = _match_proto_to_component(called_svc)
            if target_comp is None or target_comp.id == comp.id:
                continue

            intg_id = _make_id(
                "intg",
                f"{effective_name}/grpc/{comp.name}->{called_svc}",
            )
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=comp.id,
                    target_component_id=target_comp.id,
                    style="rpc",
                    protocol="grpc",
                    description=(f"gRPC call from '{comp.name}' to '{called_svc}'"),
                )
            )

    # If no code-level client scanning found results, create integrations
    # from K8s/Compose env vars that reference proto service names
    if not integrations:
        # At minimum, register that these proto services exist as RPC endpoints
        for proto_svc_name in proto_services:
            target_comp = _match_proto_to_component(proto_svc_name)
            if target_comp is None:
                continue
            # Log it for visibility but don't create orphan integrations
            logger.debug(
                "gRPC service '%s' maps to component '%s'",
                proto_svc_name,
                target_comp.name,
            )

    if integrations:
        logger.info("Found %d gRPC integrations", len(integrations))
    return integrations


def _resolve_grpc_scan_dir(repo_path: Path, comp: Component) -> Path | None:
    """Find a specific source directory for gRPC client scanning.

    When a component's boundary is the repo root (``./`` or ``.``), scanning
    the entire tree produces false positives. Instead, probe for a service-
    specific subdirectory like ``src/<name>/`` or ``services/<name>/``.
    Returns None if no specific directory can be found.
    """
    for boundary in comp.boundaries:
        bp = boundary.path
        comp_dir = repo_path / bp

        # If boundary points to a specific (non-root) directory, use it
        if bp not in (".", "./", "") and comp_dir.is_dir():
            return comp_dir

    # Boundary is repo root — try common service directory patterns
    name = comp.name
    for prefix in ("src", "services", "apps", "cmd", "internal", "packages"):
        candidate = repo_path / prefix / name
        if candidate.is_dir():
            return candidate
        # Try with 'service' suffix: e.g. src/cartservice/
        candidate_svc = repo_path / prefix / f"{name}service"
        if candidate_svc.is_dir():
            return candidate_svc

    return None


_PROTO_GENERATED_PATTERNS = re.compile(
    r"(\.pb\.go$|_pb2\.py$|_pb2_grpc\.py$|\.pb\.java$|\.pb\.cs$|"
    r"\.pb\.ts$|\.pb\.js$|_grpc\.pb\.go$|\.grpc\.cs$|Grpc\.java$|"
    r"\.proto$)",
)


def _scan_for_grpc_clients(
    comp_dir: Path,
    proto_services: dict[str, str],
) -> set[str]:
    """Scan application source files for gRPC client stub usage.

    Skips proto-generated files (``*_pb2.py``, ``*.pb.go``, etc.) to avoid
    false positives from generated stubs that contain all service definitions.
    """
    called: set[str] = set()
    source_extensions = (".go", ".py", ".java", ".cs", ".js", ".ts", ".rb")

    try:
        source_files = [
            f
            for ext in source_extensions
            for f in comp_dir.rglob(f"*{ext}")
            if not _PROTO_GENERATED_PATTERNS.search(f.name)
        ]
    except OSError:
        return called

    # Only match explicit client/stub patterns — not bare service names.
    # gRPC clients: NewCartServiceClient (Go), CartServiceStub (Java),
    # cart_service_pb2_grpc.CartServiceStub (Python)
    for svc_name in proto_services:
        patterns = [
            re.compile(rf"\bNew{svc_name}Client\b"),
            re.compile(rf"\b{svc_name}Client\b"),
            re.compile(rf"\b{svc_name}Stub\b"),
            re.compile(rf"\b{svc_name.lower()}_pb2_grpc\b"),
        ]

        for src_file in source_files[:200]:
            content = _safe_read_text(src_file)
            if not content:
                continue
            for pat in patterns:
                if pat.search(content):
                    called.add(svc_name)
                    break
            if svc_name in called:
                break

    return called


# ---------------------------------------------------------------------------
# Strategy 8: Build-dependency to infrastructure mapping
# ---------------------------------------------------------------------------

# Well-known Maven/Gradle artifacts that imply infrastructure integrations
_MAVEN_INFRA_DEPS: dict[str, tuple[str, str, IntegrationStyle]] = {
    # Database drivers
    "mysql-connector": ("mysql", "jdbc:mysql", "shared_database"),
    "postgresql": ("postgresql", "jdbc:postgresql", "shared_database"),
    "mssql-jdbc": ("sqlserver", "jdbc:sqlserver", "shared_database"),
    "ojdbc": ("oracle", "jdbc:oracle", "shared_database"),
    "h2": ("h2-database", "jdbc:h2", "shared_database"),
    "mariadb-java-client": ("mariadb", "jdbc:mariadb", "shared_database"),
    "sqlite-jdbc": ("sqlite", "jdbc:sqlite", "shared_database"),
    "mongo-java-driver": ("mongodb", "mongodb", "shared_database"),
    "mongodb-driver": ("mongodb", "mongodb", "shared_database"),
    # Redis clients
    "jedis": ("redis", "redis", "shared_database"),
    "lettuce-core": ("redis", "redis", "shared_database"),
    "redisson": ("redis", "redis", "shared_database"),
    # Message brokers
    "kafka-clients": ("kafka", "kafka", "message_queue"),
    "amqp-client": ("rabbitmq", "amqp", "message_queue"),
    "nats-client": ("nats", "nats", "message_queue"),
    "jnats": ("nats", "nats", "message_queue"),
    "pulsar-client": ("pulsar", "pulsar", "message_queue"),
    "activemq-client": ("activemq", "jms", "message_queue"),
    "artemis-jms-client": ("artemis", "jms", "message_queue"),
    # Spring Boot starters
    "spring-boot-starter-data-jpa": ("database", "jpa", "shared_database"),
    "spring-boot-starter-data-mongodb": ("mongodb", "mongodb", "shared_database"),
    "spring-boot-starter-data-redis": ("redis", "redis", "shared_database"),
    "spring-boot-starter-data-cassandra": (
        "cassandra",
        "cql",
        "shared_database",
    ),
    "spring-boot-starter-data-elasticsearch": (
        "elasticsearch",
        "http",
        "api_call",
    ),
    "spring-boot-starter-data-neo4j": ("neo4j", "bolt", "shared_database"),
    "spring-boot-starter-amqp": ("rabbitmq", "amqp", "message_queue"),
    "spring-kafka": ("kafka", "kafka", "message_queue"),
    "spring-boot-starter-cache": ("cache", "cache", "api_call"),
    "spring-boot-starter-mail": ("mail-server", "smtp", "api_call"),
    "spring-boot-starter-graphql": ("graphql", "graphql", "api_call"),
    "spring-boot-starter-websocket": ("websocket", "ws", "api_call"),
    "spring-boot-starter-oauth2-client": (
        "oauth2-provider",
        "oauth2",
        "api_call",
    ),
    "spring-boot-starter-oauth2-resource-server": (
        "oauth2-provider",
        "oauth2",
        "api_call",
    ),
    "spring-cloud-starter-openfeign": (
        "feign-target",
        "http",
        "api_call",
    ),
    "spring-cloud-starter-stream-kafka": ("kafka", "kafka", "message_queue"),
    "spring-cloud-starter-stream-rabbit": (
        "rabbitmq",
        "amqp",
        "message_queue",
    ),
    # Search / analytics
    "elasticsearch-rest-client": ("elasticsearch", "http", "api_call"),
    "elasticsearch-rest-high-level-client": (
        "elasticsearch",
        "http",
        "api_call",
    ),
    "opensearch-java": ("opensearch", "http", "api_call"),
    # gRPC
    "grpc-netty": ("grpc-server", "grpc", "api_call"),
    "grpc-stub": ("grpc-server", "grpc", "api_call"),
    # Caching
    "caffeine": ("cache", "cache", "api_call"),
    "ehcache": ("cache", "cache", "api_call"),
    "hazelcast": ("hazelcast", "hazelcast", "shared_database"),
    # Cloud SDKs
    "aws-java-sdk-s3": ("aws-s3", "http", "api_call"),
    "aws-java-sdk-sqs": ("aws-sqs", "http", "message_queue"),
    "aws-java-sdk-sns": ("aws-sns", "http", "message_queue"),
    "aws-java-sdk-dynamodb": ("aws-dynamodb", "http", "shared_database"),
    "google-cloud-storage": ("gcs", "http", "api_call"),
    "google-cloud-pubsub": ("gcp-pubsub", "http", "message_queue"),
}

# Npm package names that imply infrastructure
_NPM_INFRA_DEPS: dict[str, tuple[str, str, IntegrationStyle]] = {
    # Databases
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
    # ORMs / query builders
    "typeorm": ("database", "sql", "shared_database"),
    "prisma": ("database", "sql", "shared_database"),
    "@prisma/client": ("database", "sql", "shared_database"),
    "sequelize": ("database", "sql", "shared_database"),
    "knex": ("database", "sql", "shared_database"),
    "drizzle-orm": ("database", "sql", "shared_database"),
    # Cache / key-value
    "redis": ("redis", "redis", "shared_database"),
    "ioredis": ("redis", "redis", "shared_database"),
    "memcached": ("memcached", "memcached", "shared_database"),
    # Message brokers
    "kafkajs": ("kafka", "kafka", "message_queue"),
    "amqplib": ("rabbitmq", "amqp", "message_queue"),
    "nats": ("nats", "nats", "message_queue"),
    "bull": ("redis-queue", "redis", "message_queue"),
    "bullmq": ("redis-queue", "redis", "message_queue"),
    "@google-cloud/pubsub": ("gcp-pubsub", "http", "message_queue"),
    # Search / analytics
    "@elastic/elasticsearch": ("elasticsearch", "http", "api_call"),
    "@opensearch-project/opensearch": ("opensearch", "http", "api_call"),
    # gRPC
    "@grpc/grpc-js": ("grpc-server", "grpc", "api_call"),
    # GraphQL
    "graphql": ("graphql", "graphql", "api_call"),
    "apollo-server": ("graphql", "graphql", "api_call"),
    "@apollo/server": ("graphql", "graphql", "api_call"),
    # WebSockets
    "socket.io": ("websocket", "ws", "api_call"),
    "ws": ("websocket", "ws", "api_call"),
    # Cloud SDKs
    "@aws-sdk/client-s3": ("aws-s3", "http", "api_call"),
    "@aws-sdk/client-sqs": ("aws-sqs", "http", "message_queue"),
    "@aws-sdk/client-sns": ("aws-sns", "http", "message_queue"),
    "@aws-sdk/client-dynamodb": ("aws-dynamodb", "http", "shared_database"),
    "@google-cloud/storage": ("gcs", "http", "api_call"),
    "@azure/storage-blob": ("azure-blob", "http", "api_call"),
    "@azure/service-bus": ("azure-servicebus", "amqp", "message_queue"),
}

# Python package names that imply infrastructure
_PYTHON_INFRA_DEPS: dict[str, tuple[str, str, IntegrationStyle]] = {
    # Database drivers
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
    # ORMs / frameworks
    "sqlalchemy": ("database", "sql", "shared_database"),
    "django": ("database", "sql", "shared_database"),
    "tortoise-orm": ("database", "sql", "shared_database"),
    "peewee": ("database", "sql", "shared_database"),
    "databases": ("database", "sql", "shared_database"),
    # Cache / key-value
    "redis": ("redis", "redis", "shared_database"),
    "aioredis": ("redis", "redis", "shared_database"),
    "pymemcache": ("memcached", "memcached", "shared_database"),
    # Message brokers
    "celery": ("message-broker", "amqp", "message_queue"),
    "kafka-python": ("kafka", "kafka", "message_queue"),
    "confluent-kafka": ("kafka", "kafka", "message_queue"),
    "aiokafka": ("kafka", "kafka", "message_queue"),
    "pika": ("rabbitmq", "amqp", "message_queue"),
    "aio-pika": ("rabbitmq", "amqp", "message_queue"),
    "nats-py": ("nats", "nats", "message_queue"),
    "kombu": ("message-broker", "amqp", "message_queue"),
    # Search / analytics
    "elasticsearch": ("elasticsearch", "http", "api_call"),
    "opensearch-py": ("opensearch", "http", "api_call"),
    # gRPC
    "grpcio": ("grpc-server", "grpc", "api_call"),
    "grpcio-tools": ("grpc-server", "grpc", "api_call"),
    # Cloud SDKs
    "boto3": ("aws", "http", "api_call"),
    "google-cloud-storage": ("gcs", "http", "api_call"),
    "google-cloud-pubsub": ("gcp-pubsub", "http", "message_queue"),
    "azure-storage-blob": ("azure-blob", "http", "api_call"),
    "azure-servicebus": ("azure-servicebus", "amqp", "message_queue"),
    # HTTP clients (suggest external service integration)
    "httpx": ("http-service", "http", "api_call"),
    "aiohttp": ("http-service", "http", "api_call"),
}

# Go module paths that imply infrastructure
_GO_INFRA_DEPS: dict[str, tuple[str, str, IntegrationStyle]] = {
    # Database drivers
    "github.com/lib/pq": ("postgresql", "postgresql", "shared_database"),
    "github.com/jackc/pgx": ("postgresql", "postgresql", "shared_database"),
    "github.com/go-sql-driver/mysql": ("mysql", "mysql", "shared_database"),
    "go.mongodb.org/mongo-driver": ("mongodb", "mongodb", "shared_database"),
    "github.com/mattn/go-sqlite3": ("sqlite", "sqlite", "shared_database"),
    "github.com/denisenkom/go-mssqldb": (
        "sqlserver",
        "sqlserver",
        "shared_database",
    ),
    "github.com/microsoft/go-mssqldb": (
        "sqlserver",
        "sqlserver",
        "shared_database",
    ),
    "github.com/gocql/gocql": ("cassandra", "cql", "shared_database"),
    "github.com/neo4j/neo4j-go-driver": ("neo4j", "bolt", "shared_database"),
    # ORMs
    "gorm.io/gorm": ("database", "sql", "shared_database"),
    "github.com/uptrace/bun": ("database", "sql", "shared_database"),
    "entgo.io/ent": ("database", "sql", "shared_database"),
    # Cache / key-value
    "github.com/redis/go-redis": ("redis", "redis", "shared_database"),
    "github.com/go-redis/redis": ("redis", "redis", "shared_database"),
    "github.com/bradfitz/gomemcache": (
        "memcached",
        "memcached",
        "shared_database",
    ),
    # Message brokers
    "github.com/segmentio/kafka-go": ("kafka", "kafka", "message_queue"),
    "github.com/IBM/sarama": ("kafka", "kafka", "message_queue"),
    "github.com/Shopify/sarama": ("kafka", "kafka", "message_queue"),
    "github.com/twmb/franz-go": ("kafka", "kafka", "message_queue"),
    "github.com/streadway/amqp": ("rabbitmq", "amqp", "message_queue"),
    "github.com/rabbitmq/amqp091-go": ("rabbitmq", "amqp", "message_queue"),
    "github.com/nats-io/nats.go": ("nats", "nats", "message_queue"),
    "cloud.google.com/go/pubsub": ("gcp-pubsub", "http", "message_queue"),
    # Search / analytics
    "github.com/olivere/elastic": ("elasticsearch", "http", "api_call"),
    "github.com/elastic/go-elasticsearch": (
        "elasticsearch",
        "http",
        "api_call",
    ),
    "github.com/opensearch-project/opensearch-go": (
        "opensearch",
        "http",
        "api_call",
    ),
    # gRPC
    "google.golang.org/grpc": ("grpc-server", "grpc", "api_call"),
    # Cloud SDKs
    "github.com/aws/aws-sdk-go": ("aws", "http", "api_call"),
    "github.com/aws/aws-sdk-go-v2": ("aws", "http", "api_call"),
    "cloud.google.com/go/storage": ("gcs", "http", "api_call"),
    "github.com/Azure/azure-sdk-for-go": ("azure", "http", "api_call"),
    # Object storage
    "github.com/minio/minio-go": ("minio-s3", "http", "api_call"),
}


def _discover_build_dep_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Infer infrastructure integrations from build-file dependencies.

    Scans pom.xml, build.gradle, package.json, pyproject.toml, requirements.txt,
    and go.mod for well-known libraries that imply database, cache, or messaging
    infrastructure.
    """
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name
    seen_keys: set[str] = set()

    for comp in components:
        comp_integrations = _scan_component_build_deps(
            repo_path, comp, effective_name, seen_keys
        )
        integrations.extend(comp_integrations)

    if integrations:
        logger.info("Found %d build-dependency integrations", len(integrations))
    return integrations


def _scan_component_build_deps(
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
            content = _safe_read_text(pom)
            if content:
                results.extend(_match_maven_deps(content, comp, effective_name, seen_keys))

        # Gradle
        for gradle_name in ("build.gradle", "build.gradle.kts"):
            gradle = comp_dir / gradle_name
            if gradle.is_file():
                content = _safe_read_text(gradle)
                if content:
                    results.extend(
                        _match_gradle_deps(content, comp, effective_name, seen_keys)
                    )

        # package.json (npm)
        pkg_json = comp_dir / "package.json"
        if pkg_json.is_file():
            content = _safe_read_text(pkg_json)
            if content:
                data = _safe_json_load(content)
                if isinstance(data, dict):
                    results.extend(_match_npm_deps(data, comp, effective_name, seen_keys))

        # Python (pyproject.toml, requirements.txt)
        for py_file in ("pyproject.toml", "requirements.txt", "setup.cfg"):
            pf = comp_dir / py_file
            if pf.is_file():
                content = _safe_read_text(pf)
                if content:
                    results.extend(
                        _match_python_deps(content, comp, effective_name, seen_keys)
                    )

        # Go (go.mod)
        gomod = comp_dir / "go.mod"
        if gomod.is_file():
            content = _safe_read_text(gomod)
            if content:
                results.extend(_match_go_deps(content, comp, effective_name, seen_keys))

        # Rust (Cargo.toml)
        cargo = comp_dir / "Cargo.toml"
        if cargo.is_file():
            content = _safe_read_text(cargo)
            if content:
                results.extend(_match_rust_deps(content, comp, effective_name, seen_keys))

        # .NET (*.csproj)
        try:
            csproj_files = list(comp_dir.glob("*.csproj"))
        except OSError:
            csproj_files = []
        for csproj in csproj_files:
            content = _safe_read_text(csproj)
            if content:
                results.extend(_match_dotnet_deps(content, comp, effective_name, seen_keys))

    return results


def _match_maven_deps(
    content: str,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    results: list[IntegrationPoint] = []
    for artifact_pattern, (infra_name, protocol, style) in _MAVEN_INFRA_DEPS.items():
        if f"<artifactId>{artifact_pattern}" in content or (
            artifact_pattern in content
            and re.search(
                rf"<artifactId>[^<]*{re.escape(artifact_pattern)}[^<]*</artifactId>",
                content,
            )
        ):
            key = f"build:{comp.id}:{infra_name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            target_id = _find_or_create_infra_id(infra_name)
            if target_id == comp.id:
                continue

            intg_id = _make_id(
                "intg",
                f"{effective_name}/build-dep/{comp.name}->{infra_name}",
            )
            results.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=comp.id,
                    target_component_id=target_id,
                    style=style,
                    protocol=protocol,
                    description=(
                        f"Maven dependency implies {comp.name} connects to {infra_name}"
                    ),
                    data_flow="bidirectional" if style == "shared_database" else None,
                )
            )
    return results


def _match_gradle_deps(
    content: str,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    results: list[IntegrationPoint] = []
    for artifact_pattern, (infra_name, protocol, style) in _MAVEN_INFRA_DEPS.items():
        if artifact_pattern in content:
            key = f"build:{comp.id}:{infra_name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            target_id = _find_or_create_infra_id(infra_name)
            if target_id == comp.id:
                continue

            intg_id = _make_id(
                "intg",
                f"{effective_name}/build-dep/{comp.name}->{infra_name}",
            )
            results.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=comp.id,
                    target_component_id=target_id,
                    style=style,
                    protocol=protocol,
                    description=(
                        f"Gradle dependency implies {comp.name} connects to {infra_name}"
                    ),
                    data_flow="bidirectional" if style == "shared_database" else None,
                )
            )
    return results


def _match_npm_deps(
    data: dict[str, Any],
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    results: list[IntegrationPoint] = []
    all_deps: set[str] = set()
    for dep_key in ("dependencies", "devDependencies", "peerDependencies"):
        deps = data.get(dep_key, {})
        if isinstance(deps, dict):
            all_deps.update(deps.keys())

    for pkg_name, (infra_name, protocol, style) in _NPM_INFRA_DEPS.items():
        if pkg_name in all_deps:
            key = f"build:{comp.id}:{infra_name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            target_id = _find_or_create_infra_id(infra_name)
            if target_id == comp.id:
                continue

            intg_id = _make_id(
                "intg",
                f"{effective_name}/build-dep/{comp.name}->{infra_name}",
            )
            results.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=comp.id,
                    target_component_id=target_id,
                    style=style,
                    protocol=protocol,
                    description=(
                        f"npm dependency '{pkg_name}' implies {comp.name} "
                        f"connects to {infra_name}"
                    ),
                    data_flow="bidirectional" if style == "shared_database" else None,
                )
            )
    return results


def _match_python_deps(
    content: str,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    results: list[IntegrationPoint] = []
    content_lower = content.lower()
    for pkg_name, (infra_name, protocol, style) in _PYTHON_INFRA_DEPS.items():
        if pkg_name.lower() in content_lower:
            key = f"build:{comp.id}:{infra_name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            target_id = _find_or_create_infra_id(infra_name)
            if target_id == comp.id:
                continue

            intg_id = _make_id(
                "intg",
                f"{effective_name}/build-dep/{comp.name}->{infra_name}",
            )
            results.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=comp.id,
                    target_component_id=target_id,
                    style=style,
                    protocol=protocol,
                    description=(
                        f"Python dependency '{pkg_name}' implies {comp.name} "
                        f"connects to {infra_name}"
                    ),
                    data_flow="bidirectional" if style == "shared_database" else None,
                )
            )
    return results


def _match_go_deps(
    content: str,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    results: list[IntegrationPoint] = []
    for mod_path, (infra_name, protocol, style) in _GO_INFRA_DEPS.items():
        if mod_path in content:
            key = f"build:{comp.id}:{infra_name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            target_id = _find_or_create_infra_id(infra_name)
            if target_id == comp.id:
                continue

            intg_id = _make_id(
                "intg",
                f"{effective_name}/build-dep/{comp.name}->{infra_name}",
            )
            results.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=comp.id,
                    target_component_id=target_id,
                    style=style,
                    protocol=protocol,
                    description=(
                        f"Go module '{mod_path}' implies {comp.name} connects to {infra_name}"
                    ),
                    data_flow="bidirectional" if style == "shared_database" else None,
                )
            )
    return results


# Rust crate names that imply infrastructure
_RUST_INFRA_DEPS: dict[str, tuple[str, str, IntegrationStyle]] = {
    # Database drivers
    "tokio-postgres": ("postgresql", "postgresql", "shared_database"),
    "sqlx": ("database", "sql", "shared_database"),
    "diesel": ("database", "sql", "shared_database"),
    "sea-orm": ("database", "sql", "shared_database"),
    "mongodb": ("mongodb", "mongodb", "shared_database"),
    "rusqlite": ("sqlite", "sqlite", "shared_database"),
    # Cache / key-value
    "redis": ("redis", "redis", "shared_database"),
    "deadpool-redis": ("redis", "redis", "shared_database"),
    "memcache": ("memcached", "memcached", "shared_database"),
    # Message brokers
    "rdkafka": ("kafka", "kafka", "message_queue"),
    "kafka": ("kafka", "kafka", "message_queue"),
    "lapin": ("rabbitmq", "amqp", "message_queue"),
    "async-nats": ("nats", "nats", "message_queue"),
    # Search
    "elasticsearch": ("elasticsearch", "http", "api_call"),
    # gRPC
    "tonic": ("grpc-server", "grpc", "api_call"),
    # Cloud SDKs
    "aws-sdk-s3": ("aws-s3", "http", "api_call"),
    "aws-sdk-sqs": ("aws-sqs", "http", "message_queue"),
    "aws-sdk-dynamodb": ("aws-dynamodb", "http", "shared_database"),
}

# .NET NuGet package names that imply infrastructure
_DOTNET_INFRA_DEPS: dict[str, tuple[str, str, IntegrationStyle]] = {
    # Database drivers / EF Core providers
    "Npgsql": ("postgresql", "postgresql", "shared_database"),
    "Npgsql.EntityFrameworkCore.PostgreSQL": (
        "postgresql",
        "postgresql",
        "shared_database",
    ),
    "Microsoft.EntityFrameworkCore.SqlServer": (
        "sqlserver",
        "sqlserver",
        "shared_database",
    ),
    "Microsoft.EntityFrameworkCore.Sqlite": (
        "sqlite",
        "sqlite",
        "shared_database",
    ),
    "MySql.EntityFrameworkCore": ("mysql", "mysql", "shared_database"),
    "Pomelo.EntityFrameworkCore.MySql": ("mysql", "mysql", "shared_database"),
    "MySqlConnector": ("mysql", "mysql", "shared_database"),
    "MongoDB.Driver": ("mongodb", "mongodb", "shared_database"),
    "Oracle.EntityFrameworkCore": ("oracle", "oracle", "shared_database"),
    "CassandraCSharpDriver": ("cassandra", "cql", "shared_database"),
    "Neo4j.Driver": ("neo4j", "bolt", "shared_database"),
    # Cache / key-value
    "StackExchange.Redis": ("redis", "redis", "shared_database"),
    "Microsoft.Extensions.Caching.StackExchangeRedis": (
        "redis",
        "redis",
        "shared_database",
    ),
    # Message brokers
    "Confluent.Kafka": ("kafka", "kafka", "message_queue"),
    "RabbitMQ.Client": ("rabbitmq", "amqp", "message_queue"),
    "MassTransit": ("message-broker", "amqp", "message_queue"),
    "MassTransit.RabbitMQ": ("rabbitmq", "amqp", "message_queue"),
    "MassTransit.Kafka": ("kafka", "kafka", "message_queue"),
    "NATS.Client": ("nats", "nats", "message_queue"),
    # Search
    "NEST": ("elasticsearch", "http", "api_call"),
    "Elastic.Clients.Elasticsearch": ("elasticsearch", "http", "api_call"),
    # gRPC
    "Grpc.Net.Client": ("grpc-server", "grpc", "api_call"),
    "Grpc.AspNetCore": ("grpc-server", "grpc", "api_call"),
    # Cloud SDKs
    "AWSSDK.S3": ("aws-s3", "http", "api_call"),
    "AWSSDK.SQS": ("aws-sqs", "http", "message_queue"),
    "AWSSDK.DynamoDBv2": ("aws-dynamodb", "http", "shared_database"),
    "Azure.Storage.Blobs": ("azure-blob", "http", "api_call"),
    "Azure.Messaging.ServiceBus": (
        "azure-servicebus",
        "amqp",
        "message_queue",
    ),
    "Google.Cloud.Storage.V1": ("gcs", "http", "api_call"),
    "Google.Cloud.PubSub.V1": ("gcp-pubsub", "http", "message_queue"),
}


def _match_rust_deps(
    content: str,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    results: list[IntegrationPoint] = []
    for crate_name, (infra_name, protocol, style) in _RUST_INFRA_DEPS.items():
        if re.search(rf"^{re.escape(crate_name)}\s*=", content, re.MULTILINE):
            key = f"build:{comp.id}:{infra_name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            target_id = _find_or_create_infra_id(infra_name)
            if target_id == comp.id:
                continue

            intg_id = _make_id(
                "intg",
                f"{effective_name}/build-dep/{comp.name}->{infra_name}",
            )
            results.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=comp.id,
                    target_component_id=target_id,
                    style=style,
                    protocol=protocol,
                    description=(
                        f"Rust crate '{crate_name}' implies {comp.name} "
                        f"connects to {infra_name}"
                    ),
                    data_flow="bidirectional" if style == "shared_database" else None,
                )
            )
    return results


def _match_dotnet_deps(
    content: str,
    comp: Component,
    effective_name: str,
    seen_keys: set[str],
) -> list[IntegrationPoint]:
    results: list[IntegrationPoint] = []
    for pkg_name, (infra_name, protocol, style) in _DOTNET_INFRA_DEPS.items():
        if re.search(rf'Include="{re.escape(pkg_name)}"', content, re.IGNORECASE):
            key = f"build:{comp.id}:{infra_name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            target_id = _find_or_create_infra_id(infra_name)
            if target_id == comp.id:
                continue

            intg_id = _make_id(
                "intg",
                f"{effective_name}/build-dep/{comp.name}->{infra_name}",
            )
            results.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=comp.id,
                    target_component_id=target_id,
                    style=style,
                    protocol=protocol,
                    description=(
                        f".NET package '{pkg_name}' implies {comp.name} "
                        f"connects to {infra_name}"
                    ),
                    data_flow="bidirectional" if style == "shared_database" else None,
                )
            )
    return results


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate_integrations(
    integrations: list[IntegrationPoint],
) -> list[IntegrationPoint]:
    """Remove duplicate integration points (same source + target + style)."""
    seen: set[str] = set()
    result: list[IntegrationPoint] = []

    for intg in integrations:
        key = f"{intg.source_component_id}|{intg.target_component_id}|{intg.style}"
        if key not in seen:
            seen.add(key)
            result.append(intg)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Discover integration points in a single repository.

    Runs all discovery strategies and returns a deduplicated list of
    IntegrationPoint objects.

    Parameters
    ----------
    repo_path:
        Path to the repository root.
    components:
        Pre-discovered components to match against.
    repo_name:
        Optional human-friendly name for the repository.

    Returns
    -------
    list[IntegrationPoint]
        Deduplicated integration points.
    """
    effective_name = repo_name or repo_path.name
    logger.info("Discovering integrations in %s", repo_path)

    all_integrations: list[IntegrationPoint] = []

    # Strategy 1: K8s Service -> Deployment
    all_integrations.extend(_discover_k8s_integrations(repo_path, components, effective_name))

    # Strategy 2: Docker Compose
    all_integrations.extend(
        _discover_compose_integrations(repo_path, components, effective_name)
    )

    # Strategy 3: Maven inter-module
    all_integrations.extend(
        _discover_maven_integrations(repo_path, components, effective_name)
    )

    # Strategy 4: Gradle inter-project
    all_integrations.extend(
        _discover_gradle_integrations(repo_path, components, effective_name)
    )

    # Strategy 5: Config-file connection strings
    all_integrations.extend(
        _discover_config_integrations(repo_path, components, effective_name)
    )

    # Strategy 6: Docker Compose env-var cross-referencing
    all_integrations.extend(
        _discover_compose_env_integrations(repo_path, components, effective_name)
    )

    # Strategy 7: K8s manifest env-var cross-referencing
    all_integrations.extend(
        _discover_k8s_env_integrations(repo_path, components, effective_name)
    )

    # Strategy 8: gRPC proto service definitions
    all_integrations.extend(_discover_grpc_integrations(repo_path, components, effective_name))

    # Strategy 9: Build-dependency to infrastructure mapping
    all_integrations.extend(
        _discover_build_dep_integrations(repo_path, components, effective_name)
    )

    result = _deduplicate_integrations(all_integrations)
    logger.info("Total integrations discovered: %d", len(result))
    return result


def discover_integrations_multi_repo(
    repo_paths: list[Path],
    all_components: list[Component],
    repo_names: list[str] | None = None,
) -> list[IntegrationPoint]:
    """Discover integrations across multiple repositories.

    Sets ``is_cross_repo=True`` on integration points where the source
    and target components belong to different repos.

    Parameters
    ----------
    repo_paths:
        Paths to each repository root.
    all_components:
        Components from all repos (with ``repo`` attribute set).
    repo_names:
        Optional human-friendly names for each repository.

    Returns
    -------
    list[IntegrationPoint]
        Deduplicated integration points with cross-repo flags.
    """
    if repo_names and len(repo_names) != len(repo_paths):
        raise ValueError("repo_names must match repo_paths in length")

    # Build a lookup: component_id -> repo name
    comp_repo: dict[str, str | None] = {}
    for comp in all_components:
        comp_repo[comp.id] = comp.repo

    all_integrations: list[IntegrationPoint] = []

    for i, repo_path in enumerate(repo_paths):
        name = repo_names[i] if repo_names else None
        # Pass all_components so cross-repo references can be resolved
        intgs = discover_integrations(repo_path, all_components, repo_name=name)
        all_integrations.extend(intgs)

    # Mark cross-repo integrations
    result: list[IntegrationPoint] = []
    for intg in _deduplicate_integrations(all_integrations):
        src_repo = comp_repo.get(intg.source_component_id)
        tgt_repo = comp_repo.get(intg.target_component_id)
        if src_repo and tgt_repo and src_repo != tgt_repo:
            intg = intg.model_copy(update={"is_cross_repo": True})
        result.append(intg)

    return result


__all__ = [
    "discover_integrations",
    "discover_integrations_multi_repo",
]
