# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for collector evidence.

Each collector's payload contract is defined as a BasePayload subclass here,
replacing the untyped dict[str, Any] payloads with validated Pydantic models.
"""

from __future__ import annotations

from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload
from nfr_review.collectors.payloads.adr_derive import (
    AdrDerivedPayload,
    AdrDeriveSkipPayload,
    AdrDeriveSummaryPayload,
)
from nfr_review.collectors.payloads.apim import ApimPolicyPayload
from nfr_review.collectors.payloads.ci import (
    CiPipelinePayload,
    CiSummaryPayload,
    CmakeTestSignalFile,
    CmakeTestSignalsPayload,
)
from nfr_review.collectors.payloads.cmake import (
    CmakeConfigPayload,
    CmakeFetchContentDeclare,
    CmakeOption,
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
from nfr_review.collectors.payloads.gatling import (
    GatlingResultPayload,
    GatlingSummaryPayload,
)
from nfr_review.collectors.payloads.helm import HelmAnalysisPayload
from nfr_review.collectors.payloads.istio import IstioAnalysisPayload, IstioResource
from nfr_review.collectors.payloads.jacoco import (
    JacocoCoverageMetrics,
    JacocoPackageCoverage,
    JacocoReportPayload,
)
from nfr_review.collectors.payloads.java_ast import (
    JavaAstFilePayload,
    JavaBaseClass,
    JavaCatchBlock,
    JavaClass,
    JavaField,
    JavaLogStatement,
    JavaMethod,
    JavaParameter,
    JavaThreadPool,
)
from nfr_review.collectors.payloads.jdepend import (
    JDependPackageMetrics,
    JDependPackagesPayload,
    JDependSkipPayload,
    JDependSummaryPayload,
)
from nfr_review.collectors.payloads.k8s import (
    K8sContainer,
    K8sContainerEnvVar,
    K8sManifestSummaryPayload,
    K8sPdbPayload,
    K8sResourcePayload,
)
from nfr_review.collectors.payloads.otel import OtelAnalysisPayload
from nfr_review.collectors.payloads.proto import (
    ProtoAnalysisPayload,
    ProtoEnum,
    ProtoEnumValue,
    ProtoField,
    ProtoMessage,
    ProtoReservedRange,
    ProtoRpcMethod,
    ProtoService,
)
from nfr_review.collectors.payloads.repo_structure import RepoStructureSummaryPayload
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
from nfr_review.collectors.payloads.skaffold import SkaffoldAnalysisPayload
from nfr_review.collectors.payloads.spring import SpringConfigFilePayload
from nfr_review.collectors.payloads.telemetry import (
    TelemetryConfigSummaryPayload,
    TelemetryExporterTarget,
    TelemetryPipelinePayload,
    TelemetrySdkInitPayload,
    TelemetrySyntheticConfigPayload,
)
from nfr_review.collectors.payloads.terraform import (
    TerraformAnalysisPayload,
    TerraformBlock,
    TerraformDataBlock,
    TerraformModuleBlock,
    TerraformProviderBlock,
    TerraformRequiredProvider,
    TerraformResourceBlock,
    TerraformVariableBlock,
)

__all__ = [
    "AdrDerivedPayload",
    "AdrDeriveSkipPayload",
    "AdrDeriveSummaryPayload",
    "AdrDocumentPayload",
    "AdrSummaryPayload",
    "ApimPolicyPayload",
    "CiPipelinePayload",
    "CiSummaryPayload",
    "CmakeConfigPayload",
    "CmakeFetchContentDeclare",
    "CmakeOption",
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
    "GatlingResultPayload",
    "GatlingSummaryPayload",
    "HelmAnalysisPayload",
    "IstioAnalysisPayload",
    "IstioResource",
    "JavaAstFilePayload",
    "JavaBaseClass",
    "JavaCatchBlock",
    "JavaClass",
    "JavaField",
    "JavaLogStatement",
    "JavaMethod",
    "JavaParameter",
    "JavaThreadPool",
    "JacocoCoverageMetrics",
    "JacocoPackageCoverage",
    "JacocoReportPayload",
    "JDependPackageMetrics",
    "JDependPackagesPayload",
    "JDependSkipPayload",
    "JDependSummaryPayload",
    "K8sContainer",
    "K8sContainerEnvVar",
    "K8sManifestSummaryPayload",
    "K8sPdbPayload",
    "K8sResourcePayload",
    "OtelAnalysisPayload",
    "ProtoAnalysisPayload",
    "ProtoEnum",
    "ProtoEnumValue",
    "ProtoField",
    "ProtoMessage",
    "ProtoReservedRange",
    "ProtoRpcMethod",
    "ProtoService",
    "RepoStructureSummaryPayload",
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
    "SkaffoldAnalysisPayload",
    "SpringConfigFilePayload",
    "TelemetryConfigSummaryPayload",
    "TelemetryExporterTarget",
    "TelemetryPipelinePayload",
    "TelemetrySdkInitPayload",
    "TelemetrySyntheticConfigPayload",
    "TerraformAnalysisPayload",
    "TerraformBlock",
    "TerraformDataBlock",
    "TerraformModuleBlock",
    "TerraformProviderBlock",
    "TerraformRequiredProvider",
    "TerraformResourceBlock",
    "TerraformVariableBlock",
]
