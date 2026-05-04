"""Kubernetes manifest collector — parses K8s YAML files and emits structured
evidence about workloads, probes, resource limits, security contexts, and
network policies.

Evidence payload contract (kind="k8s-resource"):
    file_path: str — path relative to repo_path
    kind: str — K8s resource kind (Deployment, StatefulSet, etc.)
    name: str — metadata.name
    namespace: str | None — metadata.namespace
    containers: list[dict] — each with:
        name: str
        image: str
        resources: dict | None — limits/requests if present
        liveness_probe: dict | None
        readiness_probe: dict | None
        security_context: dict | None

Evidence payload contract (kind="k8s-manifest-summary"):
    resource_counts: dict[str, int] — count per K8s kind found
    has_network_policy: bool — True if any NetworkPolicy was found
    files_parsed: int
    files_failed: int
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.k8s_manifest")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_WORKLOAD_KINDS = frozenset({"Deployment", "StatefulSet", "DaemonSet", "Pod"})

_RECOGNISED_KINDS = _WORKLOAD_KINDS | {"NetworkPolicy", "HorizontalPodAutoscaler"}

_TEMPLATE_WORKLOADS = frozenset({"Deployment", "StatefulSet", "DaemonSet"})


def _extract_containers(doc: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    if kind in _TEMPLATE_WORKLOADS:
        containers_raw = (
            doc.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        )
    elif kind == "Pod":
        containers_raw = doc.get("spec", {}).get("containers", [])
    else:
        return []

    result: list[dict[str, Any]] = []
    for c in containers_raw:
        if not isinstance(c, dict):
            continue
        result.append({
            "name": c.get("name", ""),
            "image": c.get("image", ""),
            "resources": c.get("resources") or None,
            "liveness_probe": c.get("livenessProbe") or None,
            "readiness_probe": c.get("readinessProbe") or None,
            "security_context": c.get("securityContext") or None,
        })
    return result


class K8sManifestCollector:
    name = "k8s-manifest"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        resource_counts: dict[str, int] = {}
        has_network_policy = False
        files_parsed = 0
        files_failed = 0

        yaml = YAML(typ="safe")

        for yaml_file in sorted(repo_path.rglob("*.y*ml")):
            rel = yaml_file.relative_to(repo_path)
            if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                continue
            if yaml_file.suffix not in (".yaml", ".yml"):
                continue

            try:
                content = yaml_file.read_bytes()
            except OSError as exc:
                logger.warning("Cannot read %s: %s", rel, exc)
                files_failed += 1
                continue

            try:
                docs = list(yaml.load_all(content))
            except YAMLError as exc:
                logger.warning("YAML parse error in %s: %s", rel, exc)
                files_failed += 1
                continue

            file_had_k8s = False
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                if "apiVersion" not in doc or "kind" not in doc:
                    continue

                kind = doc["kind"]
                resource_counts[kind] = resource_counts.get(kind, 0) + 1
                file_had_k8s = True

                if kind == "NetworkPolicy":
                    has_network_policy = True

                if kind not in _WORKLOAD_KINDS:
                    continue

                metadata = doc.get("metadata", {}) or {}
                resource_name = metadata.get("name", "")
                namespace = metadata.get("namespace") or None
                containers = _extract_containers(doc, kind)

                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=f"{rel}:{resource_name}",
                        kind="k8s-resource",
                        payload={
                            "file_path": str(rel),
                            "kind": kind,
                            "name": resource_name,
                            "namespace": namespace,
                            "containers": containers,
                        },
                    )
                )

            if file_had_k8s:
                files_parsed += 1

        evidence.append(
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=str(repo_path),
                kind="k8s-manifest-summary",
                payload={
                    "resource_counts": resource_counts,
                    "has_network_policy": has_network_policy,
                    "files_parsed": files_parsed,
                    "files_failed": files_failed,
                },
            )
        )

        return evidence


def _register() -> None:
    if "k8s-manifest" not in collector_registry:
        collector_registry.register("k8s-manifest", K8sManifestCollector())


_register()

__all__ = ["K8sManifestCollector"]
