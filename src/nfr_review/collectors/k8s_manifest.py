"""Kubernetes manifest collector — parses K8s YAML files and emits structured
evidence about workloads, probes, resource limits, security contexts,
network policies, and patching readiness signals.

Evidence payload contract (kind="k8s-resource"):
    file_path: str — path relative to repo_path
    kind: str — K8s resource kind (Deployment, StatefulSet, etc.)
    name: str — metadata.name
    namespace: str | None — metadata.namespace
    labels: dict | None — spec.template.metadata.labels (pod labels used for PDB matching)
    replicas: int | None — spec.replicas
    strategy: dict | None — spec.strategy (Deployment) or spec.updateStrategy
    anti_affinity: dict | None — spec.template.spec.affinity.podAntiAffinity
    termination_grace_period: int | None — spec.template.spec.terminationGracePeriodSeconds
    containers: list[dict] — each with:
        name: str
        image: str
        resources: dict | None — limits/requests if present
        liveness_probe: dict | None
        readiness_probe: dict | None
        startup_probe: dict | None
        security_context: dict | None
        pre_stop: dict | None — lifecycle.preStop hook

Evidence payload contract (kind="k8s-pdb"):
    file_path: str — path relative to repo_path
    name: str — metadata.name
    namespace: str | None — metadata.namespace
    min_available: int | str | None — spec.minAvailable
    max_unavailable: int | str | None — spec.maxUnavailable
    match_labels: dict | None — spec.selector.matchLabels

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

_RECOGNISED_KINDS = _WORKLOAD_KINDS | {
    "NetworkPolicy",
    "HorizontalPodAutoscaler",
    "PodDisruptionBudget",
}

_TEMPLATE_WORKLOADS = frozenset({"Deployment", "StatefulSet", "DaemonSet"})


def _extract_containers(doc: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    if kind in _TEMPLATE_WORKLOADS:
        containers_raw = (
            doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        )
    elif kind == "Pod":
        containers_raw = doc.get("spec", {}).get("containers", [])
    else:
        return []

    result: list[dict[str, Any]] = []
    for c in containers_raw:
        if not isinstance(c, dict):
            continue
        lifecycle = c.get("lifecycle") or {}
        env_raw = c.get("env") or []
        env_out = [
            {"name": e.get("name", ""), "value": e.get("value")}
            for e in env_raw
            if isinstance(e, dict)
        ] or None
        result.append(
            {
                "name": c.get("name", ""),
                "image": c.get("image", ""),
                "resources": c.get("resources") or None,
                "liveness_probe": c.get("livenessProbe") or None,
                "readiness_probe": c.get("readinessProbe") or None,
                "startup_probe": c.get("startupProbe") or None,
                "security_context": c.get("securityContext") or None,
                "pre_stop": lifecycle.get("preStop") or None,
                "env": env_out,
            }
        )
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
                logger.debug("Cannot read %s: %s", rel, exc)
                files_failed += 1
                continue

            try:
                docs = list(yaml.load_all(content))
            except YAMLError as exc:
                logger.debug("YAML parse error in %s: %s", rel, exc)
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

                metadata = doc.get("metadata", {}) or {}
                resource_name = metadata.get("name", "")
                namespace = metadata.get("namespace") or None

                if kind == "PodDisruptionBudget":
                    pdb_spec = doc.get("spec", {}) or {}
                    selector = pdb_spec.get("selector", {}) or {}
                    evidence.append(
                        Evidence(
                            collector_name=self.name,
                            collector_version=self.version,
                            locator=f"{rel}:{resource_name}",
                            kind="k8s-pdb",
                            payload={
                                "file_path": str(rel),
                                "name": resource_name,
                                "namespace": namespace,
                                "min_available": pdb_spec.get("minAvailable"),
                                "max_unavailable": pdb_spec.get("maxUnavailable"),
                                "match_labels": selector.get("matchLabels") or None,
                            },
                        )
                    )
                    continue

                if kind not in _WORKLOAD_KINDS:
                    continue

                spec = doc.get("spec", {}) or {}
                containers = _extract_containers(doc, kind)

                if kind in _TEMPLATE_WORKLOADS:
                    pod_spec = spec.get("template", {}).get("spec", {}) or {}
                else:
                    pod_spec = spec

                strategy = spec.get("strategy") or spec.get("updateStrategy") or None
                affinity = pod_spec.get("affinity", {}) or {}

                # Pod template labels (used for PDB selector matching)
                if kind in _TEMPLATE_WORKLOADS:
                    pod_template_meta = spec.get("template", {}).get("metadata", {}) or {}
                    pod_labels = pod_template_meta.get("labels") or None
                elif kind == "Pod":
                    pod_labels = metadata.get("labels") or None
                else:
                    pod_labels = None

                annotations = metadata.get("annotations") or None
                node_selector = pod_spec.get("nodeSelector") or None
                node_affinity = affinity.get("nodeAffinity") or None

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
                            "annotations": annotations,
                            "labels": pod_labels,
                            "replicas": spec.get("replicas"),
                            "strategy": strategy,
                            "node_selector": node_selector,
                            "node_affinity": node_affinity,
                            "anti_affinity": affinity.get("podAntiAffinity") or None,
                            "termination_grace_period": pod_spec.get(
                                "terminationGracePeriodSeconds"
                            ),
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
                locator=".",
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
