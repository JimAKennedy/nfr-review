# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Docker Compose integration discovery.

Strategies extracted from ``arch_integrations``:

* **Strategy 2** -- Docker Compose network links (depends_on, links,
  shared networks).
* **Strategy 5** -- Docker Compose env-var cross-referencing
  (``_ADDR`` / ``_HOST`` / ``_URL`` style variables).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from nfr_review.arch_models import (
    Component,
    IntegrationPoint,
)
from nfr_review.arch_utils import (
    ADDR_ENV_SUFFIXES,
    component_by_name,
    guess_protocol_from_env,
    infer_env_from_compose_filename,
    infer_style_from_protocol,
    load_dotenv,
    make_id,
    resolve_env_refs,
    safe_read_text,
    safe_yaml_load,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compose file discovery
# ---------------------------------------------------------------------------

COMPOSE_FILENAMES = (
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


def find_compose_files(repo_path: Path) -> list[Path]:
    """Find all compose files, base names first, then env-variant files."""
    found: list[Path] = []
    seen: set[str] = set()
    for name in COMPOSE_FILENAMES:
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


# ---------------------------------------------------------------------------
# Strategy 2: Docker Compose network links
# ---------------------------------------------------------------------------


def discover_compose_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Parse docker-compose depends_on, links, and shared networks."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    for compose_file in find_compose_files(repo_path):
        content = safe_read_text(compose_file)
        if not content:
            continue

        data = safe_yaml_load(content)
        if not isinstance(data, dict):
            continue

        services = data.get("services", {})
        if not isinstance(services, dict):
            continue

        compose_env = infer_env_from_compose_filename(compose_file)

        seen_pairs: set[tuple[str, str]] = set()

        for svc_name, svc_config in services.items():
            if not isinstance(svc_config, dict):
                continue

            source_comp = component_by_name(components, svc_name)
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
                target_comp = component_by_name(components, dep_name)
                if target_comp is None or target_comp.id == source_comp.id:
                    continue
                pair = (source_comp.id, target_comp.id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                intg_id = make_id(
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
                    target_comp = component_by_name(components, link_target)
                    if target_comp is None or target_comp.id == source_comp.id:
                        continue
                    pair = (source_comp.id, target_comp.id)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)

                    intg_id = make_id(
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
                        src_comp = component_by_name(components, src_name)
                        tgt_comp = component_by_name(components, tgt_name)
                        if src_comp is None or tgt_comp is None or src_comp.id == tgt_comp.id:
                            continue
                        pair = (src_comp.id, tgt_comp.id)
                        reverse_pair = (tgt_comp.id, src_comp.id)
                        if pair in seen_pairs or reverse_pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)

                        intg_id = make_id(
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
# Strategy 5: Docker Compose env-var cross-referencing
# ---------------------------------------------------------------------------


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
    resolved = resolve_env_refs(value, env_vars)

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


def discover_compose_env_integrations(
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

    for compose_file in find_compose_files(repo_path):
        content = safe_read_text(compose_file)
        if not content:
            continue

        data = safe_yaml_load(content)
        if not isinstance(data, dict):
            continue

        services = data.get("services", {})
        if not isinstance(services, dict):
            continue

        compose_env = infer_env_from_compose_filename(compose_file)
        service_names = {s.lower() for s in services}

        # Load .env file if present for variable resolution
        env_vars = load_dotenv(repo_path)

        seen_pairs: set[tuple[str, str]] = set()

        for svc_name, svc_config in services.items():
            if not isinstance(svc_config, dict):
                continue

            source_comp = component_by_name(components, svc_name)
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
                if not any(env_key.upper().endswith(sfx) for sfx in ADDR_ENV_SUFFIXES):
                    continue

                # Extract the target service name from the value
                target_name = _extract_service_ref(env_val, service_names, env_vars)
                if not target_name:
                    continue

                target_comp = component_by_name(components, target_name)
                if target_comp is None or target_comp.id == source_comp.id:
                    continue

                pair = (source_comp.id, target_comp.id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                protocol = guess_protocol_from_env(env_key, env_val)
                style = infer_style_from_protocol(protocol)

                intg_id = make_id(
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
