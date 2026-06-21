# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Registry mapping (collector_name, kind) to typed payload classes.

Used by Evidence.model_post_init to auto-coerce dict payloads to typed
BasePayload subclasses, enabling transparent backward compat for tests
that still construct Evidence with raw dicts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.models import BasePayload

PAYLOAD_REGISTRY: dict[tuple[str, str], type[BasePayload]] = {}


def _populate() -> None:
    from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload
    from nfr_review.collectors.payloads.adr_derive import (
        AdrDerivedPayload,
        AdrDeriveSkipPayload,
        AdrDeriveSummaryPayload,
    )
    from nfr_review.collectors.payloads.apim import ApimPolicyPayload

    # Hygiene collectors
    from nfr_review.collectors.payloads.build_readiness import BuildReadinessPayload
    from nfr_review.collectors.payloads.ci import (
        CiPipelinePayload,
        CiSummaryPayload,
        CmakeTestSignalsPayload,
    )
    from nfr_review.collectors.payloads.ci_automation import CiAutomationPayload
    from nfr_review.collectors.payloads.cmake import CmakeConfigPayload
    from nfr_review.collectors.payloads.code_debt import CodeDebtPayload
    from nfr_review.collectors.payloads.community import CommunityPayload
    from nfr_review.collectors.payloads.cpp_ast import CppAstFilePayload
    from nfr_review.collectors.payloads.csharp_ast import CSharpAstFilePayload
    from nfr_review.collectors.payloads.deps import DepsPayload
    from nfr_review.collectors.payloads.dockerfile import DockerfileAnalysisPayload
    from nfr_review.collectors.payloads.documentation import DocumentationPayload
    from nfr_review.collectors.payloads.gatling import (
        GatlingResultPayload,
        GatlingSummaryPayload,
    )
    from nfr_review.collectors.payloads.go_ast import GoAstFilePayload
    from nfr_review.collectors.payloads.graphify import GraphifyPayload
    from nfr_review.collectors.payloads.helm import HelmAnalysisPayload
    from nfr_review.collectors.payloads.istio import IstioAnalysisPayload
    from nfr_review.collectors.payloads.jacoco import JacocoReportPayload
    from nfr_review.collectors.payloads.java_ast import JavaAstFilePayload
    from nfr_review.collectors.payloads.jdepend import (
        JDependPackagesPayload,
        JDependSkipPayload,
        JDependSummaryPayload,
    )
    from nfr_review.collectors.payloads.k8s import (
        K8sManifestSummaryPayload,
        K8sPdbPayload,
        K8sResourcePayload,
    )
    from nfr_review.collectors.payloads.license_scan import (
        LicenseScanPayload,
        LicenseScanSummaryPayload,
    )
    from nfr_review.collectors.payloads.nodejs_ast import NodejsAstFilePayload
    from nfr_review.collectors.payloads.otel import OtelAnalysisPayload, OtelSdkConfigPayload
    from nfr_review.collectors.payloads.otel_trace import OtelTracePayload
    from nfr_review.collectors.payloads.privacy import PrivacyPayload
    from nfr_review.collectors.payloads.proto import ProtoAnalysisPayload
    from nfr_review.collectors.payloads.python_ast import PythonAstFilePayload
    from nfr_review.collectors.payloads.repo_structure import RepoStructureSummaryPayload
    from nfr_review.collectors.payloads.service_mesh import (
        ServiceMeshAnalysisTemplatePayload,
        ServiceMeshDestinationRulePayload,
        ServiceMeshRolloutPayload,
        ServiceMeshSummaryPayload,
        ServiceMeshVirtualServicePayload,
    )
    from nfr_review.collectors.payloads.skaffold import SkaffoldAnalysisPayload
    from nfr_review.collectors.payloads.spring import SpringConfigFilePayload
    from nfr_review.collectors.payloads.telemetry import (
        TelemetryConfigSummaryPayload,
        TelemetryPipelinePayload,
        TelemetrySdkInitPayload,
        TelemetrySyntheticConfigPayload,
    )
    from nfr_review.collectors.payloads.terraform import TerraformAnalysisPayload

    mapping: dict[tuple[str, str], type[BasePayload]] = {
        ("adr", "adr-document"): AdrDocumentPayload,
        ("adr", "adr-summary"): AdrSummaryPayload,
        ("adr-derive", "adr-derived"): AdrDerivedPayload,
        ("adr-derive", "adr-derive-summary"): AdrDeriveSummaryPayload,
        ("adr-derive", "adr-derive-skip"): AdrDeriveSkipPayload,
        ("apim-policy", "apim-policy"): ApimPolicyPayload,
        ("ci-artifact", "ci-pipeline"): CiPipelinePayload,
        ("ci-artifact", "cmake-test-signals"): CmakeTestSignalsPayload,
        ("ci-artifact", "ci-summary"): CiSummaryPayload,
        ("cmake", "cmake-config"): CmakeConfigPayload,
        ("cpp-ast", "cpp-ast-file"): CppAstFilePayload,
        ("csharp-ast", "csharp-ast-file"): CSharpAstFilePayload,
        ("csharp-deps", "csharp-deps"): DepsPayload,
        ("dockerfile", "dockerfile-analysis"): DockerfileAnalysisPayload,
        ("gatling", "gatling-result"): GatlingResultPayload,
        ("gatling", "gatling-summary"): GatlingSummaryPayload,
        ("go-ast", "go-ast-file"): GoAstFilePayload,
        ("go-deps", "go-deps"): DepsPayload,
        ("helm", "helm-analysis"): HelmAnalysisPayload,
        ("istio", "istio-analysis"): IstioAnalysisPayload,
        ("jacoco-report", "jacoco-report"): JacocoReportPayload,
        ("java-ast", "java-ast-file"): JavaAstFilePayload,
        ("java-deps", "java-deps"): DepsPayload,
        ("jdepend", "jdepend-packages"): JDependPackagesPayload,
        ("jdepend", "jdepend-summary"): JDependSummaryPayload,
        ("jdepend", "jdepend-skip"): JDependSkipPayload,
        ("k8s-manifest", "k8s-resource"): K8sResourcePayload,
        ("k8s-manifest", "k8s-pdb"): K8sPdbPayload,
        ("k8s-manifest", "k8s-manifest-summary"): K8sManifestSummaryPayload,
        ("nodejs-ast", "nodejs-ast-file"): NodejsAstFilePayload,
        ("nodejs-deps", "nodejs-deps"): DepsPayload,
        ("otel", "otel-analysis"): OtelAnalysisPayload,
        ("otel", "otel-sdk-config"): OtelSdkConfigPayload,
        ("otel-trace", "otel-trace"): OtelTracePayload,
        ("proto", "proto-analysis"): ProtoAnalysisPayload,
        ("python-ast", "python-ast-file"): PythonAstFilePayload,
        ("python-deps", "python-deps"): DepsPayload,
        ("repo-structure", "repo-structure-summary"): RepoStructureSummaryPayload,
        ("service-mesh", "service-mesh-virtual-service"): ServiceMeshVirtualServicePayload,
        ("service-mesh", "service-mesh-destination-rule"): ServiceMeshDestinationRulePayload,
        ("service-mesh", "service-mesh-rollout"): ServiceMeshRolloutPayload,
        ("service-mesh", "service-mesh-analysis-template"): ServiceMeshAnalysisTemplatePayload,
        ("service-mesh", "service-mesh-summary"): ServiceMeshSummaryPayload,
        ("skaffold", "skaffold-analysis"): SkaffoldAnalysisPayload,
        ("spring-config", "spring-config-file"): SpringConfigFilePayload,
        ("telemetry-config", "telemetry-pipeline"): TelemetryPipelinePayload,
        ("telemetry-config", "telemetry-sdk-init"): TelemetrySdkInitPayload,
        ("telemetry-config", "telemetry-synthetic-config"): TelemetrySyntheticConfigPayload,
        ("telemetry-config", "telemetry-config-summary"): TelemetryConfigSummaryPayload,
        ("terraform", "terraform-analysis"): TerraformAnalysisPayload,
        ("graphify", "graphify-analysis"): GraphifyPayload,
        # Hygiene collectors
        ("build-readiness", "build-readiness-analysis"): BuildReadinessPayload,
        ("ci-automation", "ci-automation-analysis"): CiAutomationPayload,
        ("code-debt", "code-debt-analysis"): CodeDebtPayload,
        ("community", "community-analysis"): CommunityPayload,
        ("documentation", "documentation-analysis"): DocumentationPayload,
        ("license-scan", "license-scan"): LicenseScanPayload,
        ("license-scan", "license-scan-summary"): LicenseScanSummaryPayload,
        ("privacy", "privacy-analysis"): PrivacyPayload,
    }
    PAYLOAD_REGISTRY.update(mapping)


_populate()
