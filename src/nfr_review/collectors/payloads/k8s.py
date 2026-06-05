# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the K8s manifest collector."""

from __future__ import annotations

from typing import Any

from nfr_review.models import BasePayload


class K8sContainerEnvVar(BasePayload):
    """One environment variable in a container spec."""

    name: str
    value: str | None = None


class K8sContainer(BasePayload):
    """Extracted container spec from a workload resource."""

    name: str
    image: str
    resources: dict[str, Any] | None = None
    liveness_probe: dict[str, Any] | None = None
    readiness_probe: dict[str, Any] | None = None
    startup_probe: dict[str, Any] | None = None
    security_context: dict[str, Any] | None = None
    pre_stop: dict[str, Any] | None = None
    env: list[K8sContainerEnvVar] | None = None


class K8sResourcePayload(BasePayload):
    """Payload for kind='k8s-resource' evidence."""

    file_path: str
    kind: str
    name: str
    namespace: str | None = None
    annotations: dict[str, str] | None = None
    labels: dict[str, str] | None = None
    replicas: int | None = None
    strategy: dict[str, Any] | None = None
    node_selector: dict[str, str] | None = None
    node_affinity: dict[str, Any] | None = None
    anti_affinity: dict[str, Any] | None = None
    termination_grace_period: int | None = None
    security_context: dict[str, Any] | None = None
    containers: list[K8sContainer]


class K8sPdbPayload(BasePayload):
    """Payload for kind='k8s-pdb' evidence."""

    file_path: str
    name: str
    namespace: str | None = None
    min_available: int | str | None = None
    max_unavailable: int | str | None = None
    match_labels: dict[str, str] | None = None


class K8sManifestSummaryPayload(BasePayload):
    """Payload for kind='k8s-manifest-summary' evidence."""

    resource_counts: dict[str, int]
    has_network_policy: bool
    files_parsed: int
    files_failed: int


__all__ = [
    "K8sContainerEnvVar",
    "K8sContainer",
    "K8sResourcePayload",
    "K8sPdbPayload",
    "K8sManifestSummaryPayload",
]
