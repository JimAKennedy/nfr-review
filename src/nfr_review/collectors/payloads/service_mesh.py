# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the service mesh collector."""

from __future__ import annotations

from typing import Any

from nfr_review.models import BasePayload


class ServiceMeshRouteDestination(BasePayload):
    """A single destination in an HTTP route."""

    host: str
    subset: str | None = None
    weight: int | None = None


class ServiceMeshRetries(BasePayload):
    """Retry configuration for an HTTP route."""

    attempts: int | None = None
    per_try_timeout: str | None = None
    retry_on: str | None = None


class ServiceMeshHttpRoute(BasePayload):
    """A single HTTP route entry from a VirtualService."""

    destinations: list[ServiceMeshRouteDestination]
    timeout: str | None = None
    retries: ServiceMeshRetries | None = None
    fault: dict[str, Any] | None = None
    match: list[dict[str, Any]] | None = None


class ServiceMeshVirtualServicePayload(BasePayload):
    """Payload for kind='service-mesh-virtual-service' evidence."""

    file_path: str
    name: str
    namespace: str | None = None
    hosts: list[str]
    http_routes: list[ServiceMeshHttpRoute]
    has_weighted_routing: bool
    total_routes: int


class ServiceMeshSubset(BasePayload):
    """A single subset from a DestinationRule."""

    name: str
    labels: dict[str, str]
    traffic_policy: dict[str, Any] | None = None


class ServiceMeshDestinationRulePayload(BasePayload):
    """Payload for kind='service-mesh-destination-rule' evidence."""

    file_path: str
    name: str
    namespace: str | None = None
    host: str
    connection_pool: dict[str, Any] | None = None
    outlier_detection: dict[str, Any] | None = None
    tls_mode: str | None = None
    subsets: list[ServiceMeshSubset]
    has_connection_pool: bool
    has_outlier_detection: bool


class ServiceMeshRolloutPayload(BasePayload):
    """Payload for kind='service-mesh-rollout' evidence."""

    file_path: str
    name: str
    namespace: str | None = None
    replicas: int | None = None
    strategy_type: str
    canary_steps: list[dict[str, Any]] | None = None
    canary_max_surge: str | None = None
    canary_max_unavailable: str | None = None
    analysis_refs: list[str]
    anti_affinity: dict[str, Any] | None = None
    has_analysis: bool


class ServiceMeshAnalysisMetric(BasePayload):
    """A single metric from an AnalysisTemplate."""

    name: str
    provider: dict[str, Any] | None = None
    success_condition: str | None = None
    failure_condition: str | None = None
    interval: str | None = None
    count: int | None = None


class ServiceMeshAnalysisArg(BasePayload):
    """A single argument from an AnalysisTemplate."""

    name: str
    value: Any = None


class ServiceMeshAnalysisTemplatePayload(BasePayload):
    """Payload for kind='service-mesh-analysis-template' evidence."""

    file_path: str
    name: str
    namespace: str | None = None
    metrics: list[ServiceMeshAnalysisMetric]
    args: list[ServiceMeshAnalysisArg]
    has_metrics: bool


class ServiceMeshSummaryPayload(BasePayload):
    """Payload for kind='service-mesh-summary' evidence."""

    virtual_services: int
    destination_rules: int
    rollouts: int
    analysis_templates: int
    files_parsed: int
    files_failed: int


__all__ = [
    "ServiceMeshAnalysisArg",
    "ServiceMeshAnalysisMetric",
    "ServiceMeshAnalysisTemplatePayload",
    "ServiceMeshDestinationRulePayload",
    "ServiceMeshHttpRoute",
    "ServiceMeshRetries",
    "ServiceMeshRolloutPayload",
    "ServiceMeshRouteDestination",
    "ServiceMeshSubset",
    "ServiceMeshSummaryPayload",
    "ServiceMeshVirtualServicePayload",
]
