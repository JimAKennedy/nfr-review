# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for collector evidence.

Each collector's payload contract is defined as a BasePayload subclass here,
replacing the untyped dict[str, Any] payloads with validated Pydantic models.
"""

from __future__ import annotations

from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload
from nfr_review.collectors.payloads.ci import (
    CiPipelinePayload,
    CiSummaryPayload,
    CmakeTestSignalFile,
    CmakeTestSignalsPayload,
)
from nfr_review.collectors.payloads.deps import DependencyItem, DepsPayload
from nfr_review.collectors.payloads.dockerfile import (
    DockerCopyAddCommand,
    DockerEnvArg,
    DockerfileAnalysisPayload,
    DockerRunCommand,
    DockerStage,
    DockerUserDirective,
)
from nfr_review.collectors.payloads.k8s import (
    K8sContainer,
    K8sContainerEnvVar,
    K8sManifestSummaryPayload,
    K8sPdbPayload,
    K8sResourcePayload,
)
from nfr_review.collectors.payloads.repo_structure import RepoStructureSummaryPayload

__all__ = [
    "AdrDocumentPayload",
    "AdrSummaryPayload",
    "CiPipelinePayload",
    "CiSummaryPayload",
    "CmakeTestSignalFile",
    "CmakeTestSignalsPayload",
    "DependencyItem",
    "DepsPayload",
    "DockerCopyAddCommand",
    "DockerEnvArg",
    "DockerfileAnalysisPayload",
    "DockerRunCommand",
    "DockerStage",
    "DockerUserDirective",
    "K8sContainer",
    "K8sContainerEnvVar",
    "K8sManifestSummaryPayload",
    "K8sPdbPayload",
    "K8sResourcePayload",
    "RepoStructureSummaryPayload",
]
