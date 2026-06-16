# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration point and scenario discovery for architecture documentation.

Scans K8s manifests, Docker Compose files, build configs, and application
config files to discover integration points between components. Operates
without LLM — pure structural inference.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Literal, cast

from nfr_review.arch_models import (
    Component,
    ComponentBoundary,
    IntegrationPoint,
    IntegrationStyle,
)
from nfr_review.arch_utils import (
    component_by_k8s_selector as _component_by_k8s_selector,
)
from nfr_review.arch_utils import (
    component_by_name as _component_by_name,
)
from nfr_review.arch_utils import (
    component_by_repo_name as _component_by_repo_name,
)
from nfr_review.arch_utils import (
    discover_build_dep_integrations as _discover_build_dep_integrations,
)
from nfr_review.arch_utils import (
    find_or_create_infra_id as _find_or_create_infra_id,
)
from nfr_review.arch_utils import (
    infer_env_from_compose_filename as _infer_env_from_compose_filename,
)
from nfr_review.arch_utils import (
    infer_env_from_k8s_filepath as _infer_env_from_k8s_filepath,
)
from nfr_review.arch_utils import (
    infer_env_from_k8s_namespace as _infer_env_from_k8s_namespace,
)
from nfr_review.arch_utils import (
    infer_env_from_path_parts as _infer_env_from_path_parts,  # noqa: F401  (re-exported for tests)
)
from nfr_review.arch_utils import (
    infer_environment as _infer_environment,
)
from nfr_review.arch_utils import (
    is_comment_line as _is_comment_line,
)
from nfr_review.arch_utils import (
    load_dotenv as _load_dotenv,
)
from nfr_review.arch_utils import (
    make_id as _make_id,
)
from nfr_review.arch_utils import (
    resolve_env_refs as _resolve_env_refs,
)
from nfr_review.arch_utils import (
    safe_read_text as _safe_read_text,
)
from nfr_review.arch_utils import (
    safe_yaml_load as _safe_yaml_load,
)
from nfr_review.arch_utils import (
    safe_yaml_load_all as _safe_yaml_load_all,
)
from nfr_review.path_filter import should_exclude_path

logger = logging.getLogger(__name__)

ComponentType = Literal[
    "service", "library", "database", "queue", "gateway", "ui", "worker", "external"
]


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

                env = _infer_env_from_k8s_namespace(doc) or _infer_env_from_k8s_filepath(
                    yaml_file, repo_path
                )

                if kind == "Service":
                    spec = doc.get("spec", {}) or {}
                    selector = spec.get("selector", {}) or {}
                    if isinstance(selector, dict):
                        k8s_services.append(
                            {
                                "name": name,
                                "selector": selector,
                                "namespace": metadata.get("namespace", "default"),
                                "environment": env,
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

                    k8s_workloads.append(
                        {
                            "name": name,
                            "labels": merged_labels,
                            "kind": kind,
                            "environment": env,
                        }
                    )

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
                    intg_env = svc.get("environment") or workload.get("environment")
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
                            environment=intg_env,
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

_COMPOSE_GLOB_PATTERNS = (
    "docker-compose.*.yml",
    "docker-compose.*.yaml",
    "docker-compose-*.yml",
    "docker-compose-*.yaml",
    "compose.*.yml",
    "compose.*.yaml",
    "compose-*.yml",
    "compose-*.yaml",
)


def _find_compose_files(repo_path: Path) -> list[Path]:
    """Find all compose files, base names first, then env-variant files."""
    found: list[Path] = []
    seen: set[str] = set()
    for name in _COMPOSE_FILENAMES:
        candidate = repo_path / name
        if candidate.is_file() and candidate.name not in seen:
            found.append(candidate)
            seen.add(candidate.name)
    for pattern in _COMPOSE_GLOB_PATTERNS:
        try:
            for candidate in repo_path.glob(pattern):
                if candidate.is_file() and candidate.name not in seen:
                    found.append(candidate)
                    seen.add(candidate.name)
        except OSError:
            continue
    return found


def _discover_compose_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Parse docker-compose depends_on, links, and shared networks."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    for compose_file in _find_compose_files(repo_path):
        content = _safe_read_text(compose_file)
        if not content:
            continue

        data = _safe_yaml_load(content)
        if not isinstance(data, dict):
            continue

        services = data.get("services", {})
        if not isinstance(services, dict):
            continue

        compose_env = _infer_env_from_compose_filename(compose_file)

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
                        environment=compose_env,
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
                            environment=compose_env,
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
                                environment=compose_env,
                            )
                        )

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

_EMBEDDED_DB_TYPES = frozenset({"h2", "hsqldb", "derby", "sqlite"})

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


_IGNORED_DOMAINS = (
    ".example.com",
    ".example.org",
    ".example.net",
    ".test",
    ".invalid",
    ".localhost",
    ".local",
)


def _is_ignorable_host(host: str) -> bool:
    """Return True if the host is a generic/non-meaningful target."""
    host_lower = host.lower()
    if host_lower in _IGNORED_HOSTS or host_lower.startswith("$"):
        return True
    for suffix in _IGNORED_DOMAINS:
        if host_lower.endswith(suffix):
            return True
    return False


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

        # Infer environment from the config filename/path
        env = _infer_environment(config_file, repo_path)

        # JDBC connections
        for match in _JDBC_PATTERN.finditer(content):
            db_type = match.group(1).lower()
            host = match.group(2)
            if _is_ignorable_host(host):
                host = db_type  # Use DB type as identifier for localhost
            jdbc_env = env
            if jdbc_env is None and db_type in _EMBEDDED_DB_TYPES:
                jdbc_env = "dev"
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
                    environment=jdbc_env,
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
                    environment=env,
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
                    environment=env,
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
                    environment=env,
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
                    environment=env,
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
                    environment=env,
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
                    environment=env,
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
                        environment=env,
                    )
                )

        # HTTP endpoint connections (only for meaningful hosts)
        for match in _HTTP_ENDPOINT_PATTERN.finditer(content):
            host = match.group(1)
            if _is_ignorable_host(host):
                continue
            # Skip matches inside comment lines
            if _is_comment_line(content, match.start()):
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
                    environment=env,
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

    for compose_file in _find_compose_files(repo_path):
        content = _safe_read_text(compose_file)
        if not content:
            continue

        data = _safe_yaml_load(content)
        if not isinstance(data, dict):
            continue

        services = data.get("services", {})
        if not isinstance(services, dict):
            continue

        compose_env = _infer_env_from_compose_filename(compose_file)
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
                        environment=compose_env,
                    )
                )

    if integrations:
        logger.info("Found %d Docker Compose env-var integrations", len(integrations))
    return integrations


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

                k8s_env = _infer_env_from_k8s_namespace(doc) or _infer_env_from_k8s_filepath(
                    yaml_file, repo_path
                )

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
                            environment=k8s_env,
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
# Strategy 10: CMake FetchContent / add_subdirectory cross-repo deps
# ---------------------------------------------------------------------------

_FETCHCONTENT_DECLARE_RE = re.compile(
    r"FetchContent_Declare\s*\(\s*(\w+)", re.IGNORECASE | re.DOTALL
)
_CMAKE_GIT_REPO_RE = re.compile(r"GIT_REPOSITORY\s+([\S]+)", re.IGNORECASE)
_ADD_SUBDIR_RE = re.compile(r"add_subdirectory\s*\(\s*([^\s)]+)", re.IGNORECASE)


def _repo_name_from_url(url: str) -> str | None:
    """Extract a repository name from a Git URL.

    Handles https://host/org/repo.git, git@host:org/repo.git, and bare names.
    """
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # Last path segment
    slash_idx = url.rfind("/")
    colon_idx = url.rfind(":")
    sep = max(slash_idx, colon_idx)
    if sep >= 0:
        return url[sep + 1 :]
    return url or None


def _discover_cmake_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Discover cross-repo dependencies from CMake FetchContent and add_subdirectory."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name
    seen_pairs: set[tuple[str, str]] = set()

    source_comp = _component_by_name(components, effective_name)
    if source_comp is None:
        for comp in components:
            if comp.repo and comp.repo.lower() == effective_name.lower():
                source_comp = comp
                break

    if source_comp is None:
        return integrations

    cmake_files: list[Path] = []
    for cmake_path in repo_path.rglob("CMakeLists.txt"):
        if should_exclude_path(str(cmake_path.relative_to(repo_path))):
            continue
        cmake_files.append(cmake_path)

    for cmake_path in sorted(cmake_files):
        content = _safe_read_text(cmake_path)
        if not content:
            continue

        # FetchContent_Declare — match GIT_REPOSITORY URLs to known components
        for m in _FETCHCONTENT_DECLARE_RE.finditer(content):
            dep_name = m.group(1)
            start = m.start()
            paren_depth = 0
            end = start
            for idx in range(start, len(content)):
                if content[idx] == "(":
                    paren_depth += 1
                elif content[idx] == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        end = idx + 1
                        break
            block_text = content[start:end]

            if _is_comment_line(content, m.start()):
                continue

            url_m = _CMAKE_GIT_REPO_RE.search(block_text)
            if not url_m:
                continue
            url = url_m.group(1)
            extracted_name = _repo_name_from_url(url)
            if not extracted_name:
                continue

            target_comp = _component_by_repo_name(components, extracted_name)
            if target_comp is None:
                target_comp = _component_by_name(components, dep_name)
            if target_comp is None or target_comp.id == source_comp.id:
                continue

            pair = (source_comp.id, target_comp.id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            rel_path = cmake_path.relative_to(repo_path)
            integrations.append(
                IntegrationPoint(
                    id=_make_id("cmake-fetch", f"{effective_name}-{extracted_name}"),
                    source_component_id=source_comp.id,
                    target_component_id=target_comp.id,
                    style="build_dependency",
                    protocol="cmake-fetchcontent",
                    description=(
                        f"FetchContent dependency on {extracted_name} via {rel_path}"
                    ),
                )
            )

        # add_subdirectory — match relative paths to sibling repos
        for m in _ADD_SUBDIR_RE.finditer(content):
            if _is_comment_line(content, m.start()):
                continue
            subdir_arg = m.group(1)
            resolved = (cmake_path.parent / subdir_arg).resolve()
            target_name = resolved.name

            target_comp = _component_by_repo_name(components, target_name)
            if target_comp is None or target_comp.id == source_comp.id:
                continue

            pair = (source_comp.id, target_comp.id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            rel_path = cmake_path.relative_to(repo_path)
            integrations.append(
                IntegrationPoint(
                    id=_make_id("cmake-subdir", f"{effective_name}-{target_name}"),
                    source_component_id=source_comp.id,
                    target_component_id=target_comp.id,
                    style="build_dependency",
                    protocol="cmake-add-subdirectory",
                    description=(
                        f"add_subdirectory dependency on {target_name} via {rel_path}"
                    ),
                )
            )

    if integrations:
        logger.info(
            "Found %d CMake cross-repo dependencies in %s",
            len(integrations),
            effective_name,
        )
    return integrations


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

    # Strategy 10: CMake FetchContent / add_subdirectory cross-repo deps
    all_integrations.extend(
        _discover_cmake_integrations(repo_path, components, effective_name)
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


_PROTOCOL_TO_COMPONENT_TYPE: dict[str, str] = {
    "postgresql": "database",
    "mysql": "database",
    "mongodb": "database",
    "redis": "database",
    "cassandra": "database",
    "neo4j": "database",
    "h2": "database",
    "elasticsearch": "database",
    "kafka": "queue",
    "amqp": "queue",
    "nats": "queue",
    "smtp": "external",
    "http": "external",
    "https": "external",
    "grpc": "external",
}


def materialize_infra_components(
    components: list[Component],
    integrations: list[IntegrationPoint],
) -> list[Component]:
    """Create Component objects for infrastructure targets not already known.

    Integration discovery creates stable IDs via ``_find_or_create_infra_id``
    but never materializes them as real Component objects. This means diagram
    edges to databases/queues are silently dropped because the target node
    doesn't exist.

    This function scans all integration endpoints, finds IDs with no matching
    component, and creates lightweight Component stubs so diagrams can render
    them.  When the same infra target is referenced with different environments,
    per-environment components are created and integration edges are rewritten
    to point to the env-specific copy.
    """
    known_ids = {c.id for c in components}

    # Collect (infra_id, environment) -> [integration indices]
    infra_envs: dict[str, dict[str | None, list[int]]] = {}
    infra_meta: dict[str, tuple[str, ComponentType]] = {}

    for idx, intg in enumerate(integrations):
        for target_id in (intg.source_component_id, intg.target_component_id):
            if target_id in known_ids:
                continue
            if not target_id.startswith("infra-"):
                continue

            if target_id not in infra_meta:
                slug = target_id.split("-", 1)[1].rsplit("-", 1)[0]
                name = slug.replace("-", " ").title()
                comp_type: ComponentType = "database"
                if intg.protocol:
                    proto_key = intg.protocol.split(":")[0].lower()
                    raw = _PROTOCOL_TO_COMPONENT_TYPE.get(proto_key, "external")
                    comp_type = cast(ComponentType, raw)
                infra_meta[target_id] = (name, comp_type)

            infra_envs.setdefault(target_id, {}).setdefault(intg.environment, []).append(idx)

    comp_by_id = {c.id: c for c in components}

    new_components: dict[str, Component] = {}

    for base_id, env_map in infra_envs.items():
        name, comp_type = infra_meta[base_id]

        # Inherit repo from a connected application component
        repo: str | None = None
        for intg_indices in env_map.values():
            for idx in intg_indices:
                intg = integrations[idx]
                for cid in (intg.source_component_id, intg.target_component_id):
                    peer = comp_by_id.get(cid)
                    if peer and peer.repo:
                        repo = peer.repo
                        break
                if repo:
                    break
            if repo:
                break

        # Auto-tag embedded/in-memory databases as dev when env is unknown
        slug = base_id.split("-", 1)[1].rsplit("-", 1)[0]
        if None in env_map and any(db in slug for db in _EMBEDDED_DB_TYPES):
            indices = env_map.pop(None)
            env_map.setdefault("dev", []).extend(indices)
            for idx in indices:
                integrations[idx] = integrations[idx].model_copy(update={"environment": "dev"})

        envs = set(env_map.keys())

        if len(envs) <= 1:
            env = next(iter(envs))
            new_components[base_id] = Component(
                id=base_id,
                name=name,
                description=f"Infrastructure: {name}",
                component_type=comp_type,
                boundaries=[ComponentBoundary(boundary_type="repo", path=".")],
                environment=env,
                repo=repo,
            )
        else:
            for env, intg_indices in env_map.items():
                env_suffix = env or "default"
                env_id = f"{base_id}--{env_suffix}"
                display = f"{name} ({env_suffix})" if env else name
                new_components[env_id] = Component(
                    id=env_id,
                    name=display,
                    description=f"Infrastructure: {display}",
                    component_type=comp_type,
                    boundaries=[ComponentBoundary(boundary_type="repo", path=".")],
                    environment=env,
                    repo=repo,
                )
                for idx in intg_indices:
                    intg = integrations[idx]
                    updates: dict[str, str] = {}
                    if intg.source_component_id == base_id:
                        updates["source_component_id"] = env_id
                    if intg.target_component_id == base_id:
                        updates["target_component_id"] = env_id
                    if updates:
                        integrations[idx] = intg.model_copy(update=updates)

    if new_components:
        for comp in new_components.values():
            components.append(comp)
        logger.info("Materialized %d infrastructure components", len(new_components))

    return components


__all__ = [
    "discover_integrations",
    "discover_integrations_multi_repo",
    "materialize_infra_components",
]
