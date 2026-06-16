# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Kubernetes integration discovery.

Strategies extracted from ``arch_integrations``:

* **Strategy 1** -- K8s Service -> Deployment mapping
* **Strategy 6** -- K8s manifest env-var cross-referencing
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from nfr_review.arch_models import Component, IntegrationPoint
from nfr_review.arch_utils import (
    ADDR_ENV_SUFFIXES,
    component_by_k8s_selector,
    component_by_name,
    guess_protocol_from_env,
    infer_env_from_k8s_filepath,
    infer_env_from_k8s_namespace,
    infer_style_from_protocol,
    is_ignorable_host,
    make_id,
    safe_read_text,
    safe_yaml_load_all,
)
from nfr_review.path_filter import should_exclude_path

logger = logging.getLogger(__name__)

K8S_DIRS = ("k8s", "kubernetes", "deploy", "manifests", "helm")


# ---------------------------------------------------------------------------
# Strategy 1: K8s Service -> Deployment mapping
# ---------------------------------------------------------------------------


def discover_k8s_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Parse K8s Service manifests to find Service->Deployment integrations."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    search_dirs = [repo_path / d for d in K8S_DIRS if (repo_path / d).is_dir()]
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

            content = safe_read_text(yaml_file)
            if not content:
                continue

            docs = safe_yaml_load_all(content)
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

                env = infer_env_from_k8s_namespace(doc) or infer_env_from_k8s_filepath(
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
                svc_comp = component_by_name(components, svc["name"])
                wl_comp = component_by_name(components, workload["name"])

                if wl_comp is None:
                    # Try matching by app label
                    wl_comp = component_by_k8s_selector(components, workload["labels"])

                if svc_comp and wl_comp and svc_comp.id != wl_comp.id:
                    intg_env = svc.get("environment") or workload.get("environment")
                    intg_id = make_id(
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
# Strategy 6: K8s manifest env-var cross-referencing
# ---------------------------------------------------------------------------


def discover_k8s_env_integrations(
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

    search_dirs = [repo_path / d for d in K8S_DIRS if (repo_path / d).is_dir()]
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

            content = safe_read_text(yaml_file)
            if not content:
                continue

            docs = safe_yaml_load_all(content)
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

                source_comp = component_by_name(components, workload_name)
                if source_comp is None:
                    # Try matching by app label
                    labels = metadata.get("labels", {}) or {}
                    source_comp = component_by_k8s_selector(components, labels)
                if source_comp is None:
                    continue

                k8s_env = infer_env_from_k8s_namespace(doc) or infer_env_from_k8s_filepath(
                    yaml_file, repo_path
                )

                # Extract env vars from all containers
                containers = _extract_k8s_containers(doc)
                for env_key, env_val in containers:
                    if not any(env_key.upper().endswith(sfx) for sfx in ADDR_ENV_SUFFIXES):
                        continue

                    target_name = _extract_k8s_service_ref(env_val, comp_names)
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
    if is_ignorable_host(candidate):
        return None

    if candidate in comp_names:
        return candidate

    # Try stripping common suffixes like "service"
    for suffix in ("service", "svc"):
        stripped = candidate.removesuffix(suffix)
        if stripped != candidate and stripped in comp_names:
            return stripped

    return None
