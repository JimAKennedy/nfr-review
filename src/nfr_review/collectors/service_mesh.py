# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Service mesh collector — parses Istio VirtualService, DestinationRule and
argo-rollouts Rollout, AnalysisTemplate CRDs to extract structured traffic
management signals for PATCH-TRAFFIC rules.

Evidence payload contracts:

kind="service-mesh-virtual-service":
    file_path: str — relative path
    name: str — metadata.name
    namespace: str | None
    hosts: list[str]
    http_routes: list[dict] — each with:
        destinations: list[dict] — host, subset, weight
        timeout: str | None
        retries: dict | None — attempts, perTryTimeout, retryOn
        fault: dict | None — delay/abort injection config
        match: list[dict] | None — match conditions
    has_weighted_routing: bool — True if any route has explicit weights
    total_routes: int

kind="service-mesh-destination-rule":
    file_path: str — relative path
    name: str — metadata.name
    namespace: str | None
    host: str
    connection_pool: dict | None — tcp and http pool settings
    outlier_detection: dict | None — ejection config
    tls_mode: str | None — trafficPolicy.tls.mode
    subsets: list[dict] — name, labels, traffic_policy (per-subset overrides)
    has_connection_pool: bool
    has_outlier_detection: bool

kind="service-mesh-rollout":
    file_path: str — relative path
    name: str — metadata.name
    namespace: str | None
    replicas: int | None
    strategy_type: str — "canary" | "blueGreen" | "unknown"
    canary_steps: list[dict] | None — setWeight, pause, analysis, experiment
    canary_max_surge: str | None
    canary_max_unavailable: str | None
    analysis_refs: list[str] — names of AnalysisTemplate references
    anti_affinity: dict | None
    has_analysis: bool

kind="service-mesh-analysis-template":
    file_path: str — relative path
    name: str — metadata.name
    namespace: str | None
    metrics: list[dict] — name, provider, success_condition, failure_condition, interval, count
    args: list[dict] — name, value (template arguments)
    has_metrics: bool

kind="service-mesh-summary":
    virtual_services: int
    destination_rules: int
    rollouts: int
    analysis_templates: int
    files_parsed: int
    files_failed: int
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.collectors.payloads.service_mesh import (
    ServiceMeshAnalysisArg,
    ServiceMeshAnalysisMetric,
    ServiceMeshAnalysisTemplatePayload,
    ServiceMeshDestinationRulePayload,
    ServiceMeshHttpRoute,
    ServiceMeshRetries,
    ServiceMeshRolloutPayload,
    ServiceMeshRouteDestination,
    ServiceMeshSubset,
    ServiceMeshSummaryPayload,
    ServiceMeshVirtualServicePayload,
)
from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.service_mesh")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_ISTIO_API_RE = re.compile(r"^[a-z0-9-]+\.istio\.io/")
_ARGO_ROLLOUTS_API = "argoproj.io/v1alpha1"


def _extract_http_routes(spec: dict[str, Any]) -> list[ServiceMeshHttpRoute]:
    routes: list[ServiceMeshHttpRoute] = []
    for http_entry in spec.get("http", []) or []:
        if not isinstance(http_entry, dict):
            continue
        destinations: list[ServiceMeshRouteDestination] = []
        for route in http_entry.get("route", []) or []:
            if not isinstance(route, dict):
                continue
            dest = route.get("destination", {}) or {}
            destinations.append(
                ServiceMeshRouteDestination(
                    host=dest.get("host", ""),
                    subset=dest.get("subset") or None,
                    weight=route.get("weight"),
                )
            )

        retries_raw = http_entry.get("retries") or None
        retries: ServiceMeshRetries | None = None
        if isinstance(retries_raw, dict):
            retries = ServiceMeshRetries(
                attempts=retries_raw.get("attempts"),
                per_try_timeout=retries_raw.get("perTryTimeout"),
                retry_on=retries_raw.get("retryOn"),
            )

        routes.append(
            ServiceMeshHttpRoute(
                destinations=destinations,
                timeout=http_entry.get("timeout") or None,
                retries=retries,
                fault=http_entry.get("fault") or None,
                match=http_entry.get("match") or None,
            )
        )
    return routes


def _extract_traffic_policy(spec: dict[str, Any]) -> dict[str, Any]:
    tp = spec.get("trafficPolicy", {}) or {}
    tls = tp.get("tls", {}) or {}
    return {
        "connection_pool": tp.get("connectionPool") or None,
        "outlier_detection": tp.get("outlierDetection") or None,
        "tls_mode": tls.get("mode") or None,
    }


def _extract_subsets(spec: dict[str, Any]) -> list[ServiceMeshSubset]:
    subsets: list[ServiceMeshSubset] = []
    for s in spec.get("subsets", []) or []:
        if not isinstance(s, dict):
            continue
        subset_tp = s.get("trafficPolicy")
        subsets.append(
            ServiceMeshSubset(
                name=s.get("name", ""),
                labels=s.get("labels") or {},
                traffic_policy=subset_tp if isinstance(subset_tp, dict) else None,
            )
        )
    return subsets


def _extract_canary_steps(strategy: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for step in strategy.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        steps.append(step)
    return steps


def _extract_analysis_refs(strategy: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for step in strategy.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        analysis = step.get("analysis")
        if isinstance(analysis, dict):
            for tmpl in analysis.get("templates", []) or []:
                if isinstance(tmpl, dict) and tmpl.get("templateName"):
                    refs.append(tmpl["templateName"])

    for section_key in ("analysis", "backgroundAnalysis"):
        section = strategy.get(section_key)
        if isinstance(section, dict):
            for tmpl in section.get("templates", []) or []:
                if isinstance(tmpl, dict) and tmpl.get("templateName"):
                    refs.append(tmpl["templateName"])

    return refs


def _extract_metrics(spec: dict[str, Any]) -> list[ServiceMeshAnalysisMetric]:
    metrics: list[ServiceMeshAnalysisMetric] = []
    for m in spec.get("metrics", []) or []:
        if not isinstance(m, dict):
            continue
        provider = m.get("provider", {}) or {}
        metrics.append(
            ServiceMeshAnalysisMetric(
                name=m.get("name", ""),
                provider=provider if provider else None,
                success_condition=m.get("successCondition") or None,
                failure_condition=m.get("failureCondition") or None,
                interval=m.get("interval") or None,
                count=m.get("count"),
            )
        )
    return metrics


def _extract_template_args(spec: dict[str, Any]) -> list[ServiceMeshAnalysisArg]:
    args: list[ServiceMeshAnalysisArg] = []
    for a in spec.get("args", []) or []:
        if not isinstance(a, dict):
            continue
        args.append(
            ServiceMeshAnalysisArg(
                name=a.get("name", ""),
                value=a.get("value"),
            )
        )
    return args


def _build_virtual_service_evidence(
    collector_name: str,
    collector_version: str,
    rel: Path,
    name: str,
    namespace: str | None,
    spec: dict[str, Any],
) -> Evidence:
    http_routes = _extract_http_routes(spec)
    has_weighted = any(any(d.weight is not None for d in r.destinations) for r in http_routes)
    return Evidence(
        collector_name=collector_name,
        collector_version=collector_version,
        locator=f"{rel}:{name}",
        kind="service-mesh-virtual-service",
        payload=ServiceMeshVirtualServicePayload(
            file_path=str(rel),
            name=name,
            namespace=namespace,
            hosts=spec.get("hosts", []) or [],
            http_routes=http_routes,
            has_weighted_routing=has_weighted,
            total_routes=len(http_routes),
        ),
    )


def _build_destination_rule_evidence(
    collector_name: str,
    collector_version: str,
    rel: Path,
    name: str,
    namespace: str | None,
    spec: dict[str, Any],
) -> Evidence:
    tp = _extract_traffic_policy(spec)
    subsets = _extract_subsets(spec)
    return Evidence(
        collector_name=collector_name,
        collector_version=collector_version,
        locator=f"{rel}:{name}",
        kind="service-mesh-destination-rule",
        payload=ServiceMeshDestinationRulePayload(
            file_path=str(rel),
            name=name,
            namespace=namespace,
            host=spec.get("host", ""),
            connection_pool=tp["connection_pool"],
            outlier_detection=tp["outlier_detection"],
            tls_mode=tp["tls_mode"],
            subsets=subsets,
            has_connection_pool=tp["connection_pool"] is not None,
            has_outlier_detection=tp["outlier_detection"] is not None,
        ),
    )


def _build_rollout_evidence(
    collector_name: str,
    collector_version: str,
    rel: Path,
    name: str,
    namespace: str | None,
    spec: dict[str, Any],
) -> Evidence:
    strategy = spec.get("strategy", {}) or {}
    if "canary" in strategy:
        strategy_type = "canary"
        canary = strategy["canary"]
        canary_steps = _extract_canary_steps(canary)
        analysis_refs = _extract_analysis_refs(canary)
        max_surge = canary.get("maxSurge")
        max_unavailable = canary.get("maxUnavailable")
    elif "blueGreen" in strategy:
        strategy_type = "blueGreen"
        canary_steps = None
        analysis_refs = _extract_analysis_refs(strategy["blueGreen"])
        max_surge = None
        max_unavailable = None
    else:
        strategy_type = "unknown"
        canary_steps = None
        analysis_refs = []
        max_surge = None
        max_unavailable = None

    template = spec.get("template", {}) or {}
    pod_spec = template.get("spec", {}) or {}
    affinity = pod_spec.get("affinity", {}) or {}

    return Evidence(
        collector_name=collector_name,
        collector_version=collector_version,
        locator=f"{rel}:{name}",
        kind="service-mesh-rollout",
        payload=ServiceMeshRolloutPayload(
            file_path=str(rel),
            name=name,
            namespace=namespace,
            replicas=spec.get("replicas"),
            strategy_type=strategy_type,
            canary_steps=canary_steps,
            canary_max_surge=str(max_surge) if max_surge is not None else None,
            canary_max_unavailable=str(max_unavailable)
            if max_unavailable is not None
            else None,
            analysis_refs=analysis_refs,
            anti_affinity=affinity.get("podAntiAffinity") or None,
            has_analysis=len(analysis_refs) > 0,
        ),
    )


def _build_analysis_template_evidence(
    collector_name: str,
    collector_version: str,
    rel: Path,
    name: str,
    namespace: str | None,
    spec: dict[str, Any],
) -> Evidence:
    metrics = _extract_metrics(spec)
    tmpl_args = _extract_template_args(spec)
    return Evidence(
        collector_name=collector_name,
        collector_version=collector_version,
        locator=f"{rel}:{name}",
        kind="service-mesh-analysis-template",
        payload=ServiceMeshAnalysisTemplatePayload(
            file_path=str(rel),
            name=name,
            namespace=namespace,
            metrics=metrics,
            args=tmpl_args,
            has_metrics=len(metrics) > 0,
        ),
    )


def _classify_mesh_doc(
    doc: dict[str, Any],
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    api_version = doc.get("apiVersion", "")
    if not isinstance(api_version, str):
        return None
    kind = doc.get("kind", "")
    if not kind:
        return None
    metadata = doc.get("metadata", {}) or {}
    name = metadata.get("name", "")
    namespace = metadata.get("namespace") or None
    spec = doc.get("spec", {}) or {}

    if _ISTIO_API_RE.match(api_version) and kind == "VirtualService":
        return ("virtual-service", name, kind, namespace, spec)
    if _ISTIO_API_RE.match(api_version) and kind == "DestinationRule":
        return ("destination-rule", name, kind, namespace, spec)
    if api_version == _ARGO_ROLLOUTS_API and kind == "Rollout":
        return ("rollout", name, kind, namespace, spec)
    if api_version == _ARGO_ROLLOUTS_API and kind == "AnalysisTemplate":
        return ("analysis-template", name, kind, namespace, spec)
    return None


_CRD_BUILDERS = {
    "virtual-service": _build_virtual_service_evidence,
    "destination-rule": _build_destination_rule_evidence,
    "rollout": _build_rollout_evidence,
    "analysis-template": _build_analysis_template_evidence,
}

_CRD_COUNT_KEYS = {
    "virtual-service": "virtual_services",
    "destination-rule": "destination_rules",
    "rollout": "rollouts",
    "analysis-template": "analysis_templates",
}


class ServiceMeshCollector:
    name = "service-mesh"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        yaml = YAML(typ="safe")
        exclude_test = getattr(config, "exclude_test_paths", True)
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))
        counts: dict[str, int] = {k: 0 for k in _CRD_COUNT_KEYS.values()}
        files_parsed = 0
        files_failed = 0

        for yaml_file in sorted(repo_path.rglob("*.y*ml")):
            rel = yaml_file.relative_to(repo_path)
            if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                continue
            if yaml_file.suffix not in (".yaml", ".yml"):
                continue
            if should_exclude_path(
                str(rel), exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
            ):
                continue

            parsed, failed = self._process_yaml_file(yaml_file, rel, yaml, evidence, counts)
            files_parsed += parsed
            files_failed += failed

        evidence.append(
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="service-mesh-summary",
                payload=ServiceMeshSummaryPayload(
                    files_parsed=files_parsed,
                    files_failed=files_failed,
                    **counts,
                ),
            )
        )
        return evidence

    def _process_yaml_file(
        self,
        yaml_file: Path,
        rel: Path,
        yaml: YAML,
        evidence: list[Evidence],
        counts: dict[str, int],
    ) -> tuple[int, int]:
        try:
            content = yaml_file.read_bytes()
        except OSError as exc:
            logger.debug("Cannot read %s: %s", rel, exc)
            return 0, 1

        try:
            docs = list(yaml.load_all(content))
        except YAMLError as exc:
            logger.debug("YAML parse error in %s: %s", rel, exc)
            return 0, 1

        file_had_mesh = False
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            classified = _classify_mesh_doc(doc)
            if classified is None:
                continue
            crd_type, name, _kind, namespace, spec = classified
            builder = _CRD_BUILDERS[crd_type]
            evidence.append(builder(self.name, self.version, rel, name, namespace, spec))
            counts[_CRD_COUNT_KEYS[crd_type]] += 1
            file_had_mesh = True

        return (1 if file_had_mesh else 0), 0


def _register() -> None:
    if "service-mesh" not in collector_registry:
        collector_registry.register("service-mesh", ServiceMeshCollector())


_register()

__all__ = ["ServiceMeshCollector"]
