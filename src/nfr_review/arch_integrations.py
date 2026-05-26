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

import yaml

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
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def _safe_yaml_load_all(text: str) -> list[Any]:
    try:
        return [doc for doc in yaml.safe_load_all(text) if doc is not None]
    except yaml.YAMLError:
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

_CONFIG_FILENAMES = (
    "application.yml",
    "application.yaml",
    "application.properties",
    "application-*.yml",
    "application-*.yaml",
    "application-*.properties",
    ".env",
    "appsettings.json",
    "appsettings.*.json",
    "config.yml",
    "config.yaml",
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
        "amqp": "message_queue",
        "kafka": "message_queue",
        "http": "api_call",
        "https": "api_call",
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
    parts = list(rel.parts)

    # Walk up from the config file's directory to find an owning component
    for comp in components:
        for boundary in comp.boundaries:
            bp = boundary.path
            if bp == ".":
                continue
            # Check if config file is under the component's boundary path
            if str(rel).startswith(bp.rstrip("/") + "/") or str(rel.parent) == bp:
                return comp

    # Fallback: if we're at repo root, pick the first root component
    if len(parts) <= 2:
        for comp in components:
            for boundary in comp.boundaries:
                if boundary.boundary_type == "repo" and boundary.path == ".":
                    return comp

    return components[0] if components else None


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
