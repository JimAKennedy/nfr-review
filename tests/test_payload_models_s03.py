# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for typed payload models from the 16 remaining collectors (M035-S03)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nfr_review.collectors.payloads.adr_derive import (
    AdrDerivedPayload,
    AdrDeriveSkipPayload,
    AdrDeriveSummaryPayload,
)
from nfr_review.collectors.payloads.apim import ApimPolicyPayload
from nfr_review.collectors.payloads.cmake import (
    CmakeConfigPayload,
    CmakeFetchContentDeclare,
    CmakeOption,
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

# ---------------------------------------------------------------------------
# Helpers — reusable factory data
# ---------------------------------------------------------------------------


def _otel_kwargs() -> dict:
    return dict(
        file_path="otel-collector-config.yaml",
        receivers=["otlp", "prometheus"],
        processors=["batch", "memory_limiter"],
        exporters=["otlp", "logging"],
        pipelines={"traces": {"receivers": ["otlp"], "exporters": ["otlp"]}},
    )


def _skaffold_kwargs() -> dict:
    return dict(
        file_path="skaffold.yaml",
        api_version="skaffold/v2beta29",
        build={"artifacts": [{"image": "app"}]},
        deploy={"kubectl": {"manifests": ["k8s/*.yaml"]}},
        profiles=[{"name": "dev", "deploy": {}}],
    )


def _apim_kwargs() -> dict:
    return dict(
        file_path="policy.xml",
        has_rate_limit=True,
        has_auth_policy=True,
        backend_urls=["https://api.example.com"],
        uses_named_values=False,
        inbound_policies=["rate-limit", "validate-jwt"],
        outbound_policies=["set-header"],
    )


def _gatling_result_kwargs() -> dict:
    return dict(
        simulation_dir="results/sim-20240101",
        total_requests=10000,
        ok_requests=9900,
        ko_requests=100,
        error_rate=1.0,
        mean_response_time_ms=120.5,
        p50_response_time_ms=100.0,
        p75_response_time_ms=150.0,
        p95_response_time_ms=250.0,
        p99_response_time_ms=500.0,
        min_response_time_ms=5.0,
        max_response_time_ms=2500.0,
        requests_per_second=333.3,
    )


def _gatling_summary_kwargs() -> dict:
    return dict(
        simulation_count=2,
        simulations=["BasicSimulation", "StressSimulation"],
    )


def _cmake_config_kwargs() -> dict:
    return dict(
        file_path="CMakeLists.txt",
        cmake_minimum_required="3.16",
        project_name="mylib",
        project_version="1.0.0",
        fetchcontent_declares=[
            CmakeFetchContentDeclare(
                name="googletest",
                url="https://github.com/google/googletest.git",
                tag="v1.14.0",
                line=10,
                is_pinned=True,
            )
        ],
        has_target_compile_features=True,
        has_target_compile_options=False,
        has_global_cmake_flags=False,
        has_install_targets=True,
        options=[CmakeOption(name="BUILD_TESTS", description="Build test suite", line=5)],
    )


def _istio_kwargs() -> dict:
    return dict(
        file_path="istio/vs.yaml",
        resources=[
            IstioResource(
                kind="VirtualService",
                api_version="networking.istio.io/v1beta1",
                name="my-vs",
                namespace="default",
                spec={"hosts": ["my-svc"]},
                line=1,
            )
        ],
    )


def _helm_kwargs() -> dict:
    return dict(
        chart_path="charts/myapp",
        chart_name="myapp",
        chart_version="1.2.3",
        app_version="2.0.0",
        description="My application chart",
        maintainers=[{"name": "dev", "email": "dev@example.com"}],
        chart_values={"replicaCount": 3, "image": {"tag": "latest"}},
        rendered_manifests=[{"kind": "Deployment", "metadata": {"name": "myapp"}}],
        template_files=["deployment.yaml", "service.yaml"],
        helm_available=True,
    )


def _jacoco_kwargs() -> dict:
    overall = JacocoCoverageMetrics(
        line_covered=800,
        line_missed=200,
        line_pct=80.0,
        branch_covered=400,
        branch_missed=100,
        branch_pct=80.0,
        instruction_covered=5000,
        instruction_missed=1000,
        instruction_pct=83.33,
    )
    pkg = JacocoPackageCoverage(
        name="com.example.core",
        line_pct=85.0,
        branch_pct=78.0,
        instruction_pct=82.0,
    )
    return dict(
        report_path="target/site/jacoco/jacoco.xml",
        report_name="JaCoCo Report",
        overall=overall,
        packages=[pkg],
    )


def _spring_kwargs() -> dict:
    return dict(
        file_path="src/main/resources/application.yml",
        profile="dev",
        management={"endpoints": {"web": {"exposure": {"include": "*"}}}},
        logging={"level": {"root": "INFO"}},
        server={"port": 8080},
        spring_security={"oauth2": {"enabled": True}},
        actuator={"health": {"show-details": "always"}},
        raw_keys=["server.port", "spring.datasource.url"],
    )


def _jdepend_packages_kwargs() -> dict:
    return dict(
        bytecode_dir="target/classes",
        packages=[
            JDependPackageMetrics(
                name="com.example.core",
                total_classes=20,
                concrete_classes=15,
                abstract_classes=5,
                ca=3,
                ce=7,
                a=0.25,
                i=0.7,
                d=0.05,
                v=1,
            )
        ],
    )


def _jdepend_summary_kwargs() -> dict:
    return dict(
        total_packages=10,
        packages_with_cycles=1,
        cycle_groups=[["com.example.a", "com.example.b"]],
        avg_distance=0.15,
        max_distance=0.35,
    )


def _adr_derived_kwargs() -> dict:
    return dict(
        title="Use event-driven architecture",
        rationale="Multiple services need async communication",
        category="architecture",
        confidence=0.85,
        evidence_refs=["ev-001", "ev-002"],
    )


def _adr_derive_summary_kwargs() -> dict:
    return dict(
        total_derived=5,
        categories={"architecture": 3, "security": 2},
        avg_confidence=0.78,
    )


def _sm_virtual_service_kwargs() -> dict:
    dest = ServiceMeshRouteDestination(host="my-svc", subset="v1", weight=80)
    route = ServiceMeshHttpRoute(
        destinations=[dest],
        timeout="30s",
        retries=ServiceMeshRetries(attempts=3, per_try_timeout="10s", retry_on="5xx"),
    )
    return dict(
        file_path="mesh/vs.yaml",
        name="my-vs",
        namespace="default",
        hosts=["my-svc"],
        http_routes=[route],
        has_weighted_routing=True,
        total_routes=1,
    )


def _sm_destination_rule_kwargs() -> dict:
    subset = ServiceMeshSubset(name="v1", labels={"version": "v1"}, traffic_policy=None)
    return dict(
        file_path="mesh/dr.yaml",
        name="my-dr",
        namespace="default",
        host="my-svc",
        connection_pool={"tcp": {"maxConnections": 100}},
        outlier_detection={"consecutive5xxErrors": 5},
        tls_mode="ISTIO_MUTUAL",
        subsets=[subset],
        has_connection_pool=True,
        has_outlier_detection=True,
    )


def _sm_rollout_kwargs() -> dict:
    return dict(
        file_path="mesh/rollout.yaml",
        name="my-rollout",
        namespace="default",
        replicas=5,
        strategy_type="canary",
        canary_steps=[{"setWeight": 20}, {"pause": {"duration": "1m"}}],
        canary_max_surge="25%",
        canary_max_unavailable="0",
        analysis_refs=["success-rate"],
        anti_affinity=None,
        has_analysis=True,
    )


def _sm_analysis_template_kwargs() -> dict:
    metric = ServiceMeshAnalysisMetric(
        name="success-rate",
        provider={"prometheus": {"query": "sum(rate(...))"}},
        success_condition="result[0] >= 0.95",
        interval="1m",
        count=5,
    )
    arg = ServiceMeshAnalysisArg(name="service-name", value="my-svc")
    return dict(
        file_path="mesh/analysis.yaml",
        name="success-rate-template",
        namespace="default",
        metrics=[metric],
        args=[arg],
        has_metrics=True,
    )


def _sm_summary_kwargs() -> dict:
    return dict(
        virtual_services=3,
        destination_rules=2,
        rollouts=1,
        analysis_templates=2,
        files_parsed=8,
        files_failed=0,
    )


def _telemetry_pipeline_kwargs() -> dict:
    target = TelemetryExporterTarget(name="jaeger", type="otlp", endpoint="http://jaeger:4317")
    return dict(
        file_path="otel-config.yaml",
        receivers=["otlp"],
        processors=["batch"],
        exporters=["otlp"],
        pipelines={"traces": {"receivers": ["otlp"], "exporters": ["otlp"]}},
        signal_types=["traces", "metrics"],
        exporter_targets=[target],
        resource_attributes={"service.name": "my-svc"},
        extensions=["health_check"],
    )


def _telemetry_sdk_init_kwargs() -> dict:
    return dict(
        file_path="src/main/java/Tracing.java",
        language="java",
        sdk_packages=["io.opentelemetry:opentelemetry-sdk"],
        instrumentation_type="manual",
        configured_signals=["traces", "metrics"],
    )


def _telemetry_synthetic_kwargs() -> dict:
    return dict(
        file_path="synthetic/config.yaml",
        tool="playwright",
        test_type="browser",
        targets=["https://app.example.com"],
        frequency="5m",
    )


def _telemetry_summary_kwargs() -> dict:
    return dict(
        collector_configs_found=2,
        sdk_instrumentations_found=3,
        synthetic_configs_found=1,
        signal_coverage={"traces": True, "metrics": True, "logs": False},
        files_parsed=6,
        files_failed=0,
    )


def _terraform_kwargs() -> dict:
    rp = TerraformRequiredProvider(
        name="aws", source="hashicorp/aws", version_constraint="~> 5.0"
    )
    tb = TerraformBlock(backend_type="s3", required_version=">= 1.5", required_providers=[rp])
    pb = TerraformProviderBlock(name="aws", version="5.31.0", line=10)
    rb = TerraformResourceBlock(
        type="aws_instance", name="web", body_text='ami = "abc"', line=20
    )
    db = TerraformDataBlock(
        type="aws_ami", name="ubuntu", body_text='owners = ["self"]', line=30
    )
    vb = TerraformVariableBlock(
        name="region", has_description=True, has_type=True, has_default=True
    )
    mb = TerraformModuleBlock(
        name="vpc",
        source="terraform-aws-modules/vpc/aws",
        version="5.1.0",
    )
    return dict(
        file_path="main.tf",
        terraform_blocks=[tb],
        provider_blocks=[pb],
        resource_blocks=[rb],
        data_blocks=[db],
        variable_blocks=[vb],
        module_blocks=[mb],
    )


def _proto_kwargs() -> dict:
    field = ProtoField(name="id", number=1, type="int64", label="optional", line=5)
    reserved = ProtoReservedRange(start=10, end=20)
    msg = ProtoMessage(
        name="User",
        line=3,
        has_comment=True,
        fields=[field],
        reserved_numbers=[15],
        reserved_ranges=[reserved],
    )
    rpc = ProtoRpcMethod(
        name="GetUser",
        request_type="GetUserRequest",
        response_type="GetUserResponse",
        line=20,
        has_comment=True,
    )
    svc = ProtoService(name="UserService", line=18, has_comment=True, methods=[rpc])
    ev = ProtoEnumValue(name="UNKNOWN", number=0)
    enum = ProtoEnum(name="Status", line=30, enum_values=[ev])
    return dict(
        file_path="user.proto",
        syntax="proto3",
        package="example.v1",
        imports=["google/protobuf/timestamp.proto"],
        messages=[msg],
        services=[svc],
        enums=[enum],
    )


def _java_ast_kwargs() -> dict:
    param = JavaParameter(name="id", type="long")
    base = JavaBaseClass(name="AbstractService", access="public")
    field = JavaField(name="logger", type="Logger", access="private", line=10)
    method = JavaMethod(
        name="findById",
        annotations=["@Override"],
        return_type="User",
        access="public",
        is_virtual=False,
        is_pure_virtual=False,
        line=15,
        parameters=[param],
        mapping_paths=["/users/{id}"],
    )
    cls = JavaClass(
        name="UserService",
        line=5,
        annotations=["@Service"],
        is_abstract=False,
        is_interface=False,
        base_classes=[base],
        fields=[field],
        methods=[method],
        namespace="com.example.service",
        outer_class="",
    )
    catch = JavaCatchBlock(caught_type="IOException", rethrows=True, line=30)
    pool = JavaThreadPool(
        class_name="ThreadPoolExecutor",
        line=40,
        has_bounded_queue=True,
        has_rejection_policy=True,
    )
    log = JavaLogStatement(method="info", arguments_text='"Starting"', line=3)
    return dict(
        file_path="src/main/java/UserService.java",
        package="com.example.service",
        classes=[cls],
        methods=[method],
        catch_blocks=[catch],
        imports=["java.io.IOException", "org.slf4j.Logger"],
        thread_pool_constructions=[pool],
        log_statements=[log],
    )


# ===========================================================================
# 1. OtelAnalysisPayload
# ===========================================================================


class TestOtelAnalysisPayload:
    def test_construction(self) -> None:
        p = OtelAnalysisPayload(**_otel_kwargs())
        assert p.file_path == "otel-collector-config.yaml"
        assert p.receivers == ["otlp", "prometheus"]
        assert p.processors == ["batch", "memory_limiter"]
        assert p.exporters == ["otlp", "logging"]
        assert "traces" in p.pipelines

    def test_roundtrip(self) -> None:
        p = OtelAnalysisPayload(**_otel_kwargs())
        dumped = p.model_dump()
        restored = OtelAnalysisPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            OtelAnalysisPayload(**_otel_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = OtelAnalysisPayload(**_otel_kwargs())
        assert p.get("file_path") == "otel-collector-config.yaml"
        assert p.get("missing", "default") == "default"
        assert p["file_path"] == "otel-collector-config.yaml"
        assert "file_path" in p


# ===========================================================================
# 2. SkaffoldAnalysisPayload
# ===========================================================================


class TestSkaffoldAnalysisPayload:
    def test_construction(self) -> None:
        p = SkaffoldAnalysisPayload(**_skaffold_kwargs())
        assert p.file_path == "skaffold.yaml"
        assert p.api_version == "skaffold/v2beta29"
        assert len(p.profiles) == 1

    def test_roundtrip(self) -> None:
        p = SkaffoldAnalysisPayload(**_skaffold_kwargs())
        dumped = p.model_dump()
        restored = SkaffoldAnalysisPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            SkaffoldAnalysisPayload(**_skaffold_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = SkaffoldAnalysisPayload(**_skaffold_kwargs())
        assert p.get("api_version") == "skaffold/v2beta29"
        assert p.get("missing") is None


# ===========================================================================
# 3. ApimPolicyPayload
# ===========================================================================


class TestApimPolicyPayload:
    def test_construction(self) -> None:
        p = ApimPolicyPayload(**_apim_kwargs())
        assert p.file_path == "policy.xml"
        assert p.has_rate_limit is True
        assert p.has_auth_policy is True
        assert p.backend_urls == ["https://api.example.com"]
        assert p.inbound_policies == ["rate-limit", "validate-jwt"]
        assert p.outbound_policies == ["set-header"]

    def test_roundtrip(self) -> None:
        p = ApimPolicyPayload(**_apim_kwargs())
        dumped = p.model_dump()
        restored = ApimPolicyPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            ApimPolicyPayload(**_apim_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = ApimPolicyPayload(**_apim_kwargs())
        assert p.get("has_rate_limit") is True
        assert p["has_auth_policy"] is True
        assert "backend_urls" in p


# ===========================================================================
# 4. GatlingResultPayload / GatlingSummaryPayload
# ===========================================================================


class TestGatlingResultPayload:
    def test_construction(self) -> None:
        p = GatlingResultPayload(**_gatling_result_kwargs())
        assert p.total_requests == 10000
        assert p.ok_requests == 9900
        assert p.ko_requests == 100
        assert p.error_rate == 1.0
        assert p.mean_response_time_ms == 120.5
        assert p.requests_per_second == 333.3

    def test_roundtrip(self) -> None:
        p = GatlingResultPayload(**_gatling_result_kwargs())
        dumped = p.model_dump()
        restored = GatlingResultPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            GatlingResultPayload(**_gatling_result_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = GatlingResultPayload(**_gatling_result_kwargs())
        assert p.get("total_requests") == 10000
        assert p["simulation_dir"] == "results/sim-20240101"
        assert "error_rate" in p


class TestGatlingSummaryPayload:
    def test_construction(self) -> None:
        p = GatlingSummaryPayload(**_gatling_summary_kwargs())
        assert p.simulation_count == 2
        assert "BasicSimulation" in p.simulations

    def test_roundtrip(self) -> None:
        p = GatlingSummaryPayload(**_gatling_summary_kwargs())
        dumped = p.model_dump()
        restored = GatlingSummaryPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            GatlingSummaryPayload(**_gatling_summary_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = GatlingSummaryPayload(**_gatling_summary_kwargs())
        assert p.get("simulation_count") == 2


# ===========================================================================
# 5. CMake payloads
# ===========================================================================


class TestCmakeFetchContentDeclare:
    def test_construction(self) -> None:
        fc = CmakeFetchContentDeclare(
            name="googletest",
            url="https://github.com/google/googletest.git",
            tag="v1.14.0",
            line=10,
            is_pinned=True,
        )
        assert fc.name == "googletest"
        assert fc.is_pinned is True


class TestCmakeOption:
    def test_construction(self) -> None:
        o = CmakeOption(name="BUILD_TESTS", description="Build test suite", line=5)
        assert o.name == "BUILD_TESTS"
        assert o.description == "Build test suite"


class TestCmakeConfigPayload:
    def test_construction(self) -> None:
        p = CmakeConfigPayload(**_cmake_config_kwargs())
        assert p.file_path == "CMakeLists.txt"
        assert p.cmake_minimum_required == "3.16"
        assert p.project_name == "mylib"
        assert len(p.fetchcontent_declares) == 1
        assert p.has_target_compile_features is True
        assert len(p.options) == 1

    def test_minimal_construction(self) -> None:
        p = CmakeConfigPayload(
            file_path="CMakeLists.txt",
            fetchcontent_declares=[],
            has_target_compile_features=False,
            has_target_compile_options=False,
            has_global_cmake_flags=False,
            has_install_targets=False,
            options=[],
        )
        assert p.cmake_minimum_required is None
        assert p.project_name is None

    def test_roundtrip(self) -> None:
        p = CmakeConfigPayload(**_cmake_config_kwargs())
        dumped = p.model_dump()
        restored = CmakeConfigPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            CmakeConfigPayload(**_cmake_config_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = CmakeConfigPayload(**_cmake_config_kwargs())
        assert p.get("file_path") == "CMakeLists.txt"
        assert p.get("nonexistent", 42) == 42


# ===========================================================================
# 6. Istio payloads
# ===========================================================================


class TestIstioResource:
    def test_construction(self) -> None:
        r = IstioResource(
            kind="VirtualService",
            api_version="networking.istio.io/v1beta1",
            name="my-vs",
            spec={"hosts": ["svc"]},
            line=1,
        )
        assert r.kind == "VirtualService"
        assert r.namespace is None


class TestIstioAnalysisPayload:
    def test_construction(self) -> None:
        p = IstioAnalysisPayload(**_istio_kwargs())
        assert p.file_path == "istio/vs.yaml"
        assert len(p.resources) == 1
        assert p.resources[0].kind == "VirtualService"

    def test_roundtrip(self) -> None:
        p = IstioAnalysisPayload(**_istio_kwargs())
        dumped = p.model_dump()
        restored = IstioAnalysisPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            IstioAnalysisPayload(**_istio_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = IstioAnalysisPayload(**_istio_kwargs())
        assert p.get("file_path") == "istio/vs.yaml"
        assert "resources" in p


# ===========================================================================
# 7. HelmAnalysisPayload
# ===========================================================================


class TestHelmAnalysisPayload:
    def test_construction(self) -> None:
        p = HelmAnalysisPayload(**_helm_kwargs())
        assert p.chart_path == "charts/myapp"
        assert p.chart_name == "myapp"
        assert p.chart_version == "1.2.3"
        assert p.helm_available is True
        assert len(p.template_files) == 2

    def test_minimal_construction(self) -> None:
        p = HelmAnalysisPayload(
            chart_path="charts/app",
            chart_values={},
            rendered_manifests=[],
            template_files=[],
            helm_available=False,
        )
        assert p.chart_name is None
        assert p.maintainers is None

    def test_roundtrip(self) -> None:
        p = HelmAnalysisPayload(**_helm_kwargs())
        dumped = p.model_dump()
        restored = HelmAnalysisPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            HelmAnalysisPayload(**_helm_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = HelmAnalysisPayload(**_helm_kwargs())
        assert p.get("chart_path") == "charts/myapp"
        assert p["helm_available"] is True


# ===========================================================================
# 8. JaCoCo payloads
# ===========================================================================


class TestJacocoCoverageMetrics:
    def test_construction(self) -> None:
        m = JacocoCoverageMetrics(
            line_covered=100,
            line_missed=20,
            line_pct=83.33,
            branch_covered=50,
            branch_missed=10,
            branch_pct=83.33,
            instruction_covered=500,
            instruction_missed=100,
            instruction_pct=83.33,
        )
        assert m.line_pct == 83.33
        assert m.branch_covered == 50


class TestJacocoPackageCoverage:
    def test_construction(self) -> None:
        p = JacocoPackageCoverage(
            name="com.example", line_pct=80.0, branch_pct=75.0, instruction_pct=82.0
        )
        assert p.name == "com.example"


class TestJacocoReportPayload:
    def test_construction(self) -> None:
        p = JacocoReportPayload(**_jacoco_kwargs())
        assert p.report_path == "target/site/jacoco/jacoco.xml"
        assert p.report_name == "JaCoCo Report"
        assert p.overall.line_pct == 80.0
        assert len(p.packages) == 1

    def test_roundtrip(self) -> None:
        p = JacocoReportPayload(**_jacoco_kwargs())
        dumped = p.model_dump()
        restored = JacocoReportPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            JacocoReportPayload(**_jacoco_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = JacocoReportPayload(**_jacoco_kwargs())
        assert p.get("report_name") == "JaCoCo Report"
        assert p["report_path"] == "target/site/jacoco/jacoco.xml"
        assert "overall" in p


# ===========================================================================
# 9. SpringConfigFilePayload
# ===========================================================================


class TestSpringConfigFilePayload:
    def test_construction(self) -> None:
        p = SpringConfigFilePayload(**_spring_kwargs())
        assert p.file_path == "src/main/resources/application.yml"
        assert p.profile == "dev"
        assert p.server == {"port": 8080}
        assert "server.port" in p.raw_keys

    def test_minimal_construction(self) -> None:
        p = SpringConfigFilePayload(
            file_path="application.yml",
            management={},
            logging={},
            server={},
            spring_security={},
            actuator={},
            raw_keys=[],
        )
        assert p.profile is None

    def test_roundtrip(self) -> None:
        p = SpringConfigFilePayload(**_spring_kwargs())
        dumped = p.model_dump()
        restored = SpringConfigFilePayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            SpringConfigFilePayload(**_spring_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = SpringConfigFilePayload(**_spring_kwargs())
        assert p.get("profile") == "dev"
        assert p.get("missing", "fallback") == "fallback"


# ===========================================================================
# 10. JDepend payloads
# ===========================================================================


class TestJDependPackageMetrics:
    def test_construction(self) -> None:
        m = JDependPackageMetrics(name="com.example.core")
        assert m.name == "com.example.core"
        assert m.total_classes == 0
        assert m.d == 0.0

    def test_full_construction(self) -> None:
        m = JDependPackageMetrics(
            name="com.example",
            total_classes=20,
            concrete_classes=15,
            abstract_classes=5,
            ca=3,
            ce=7,
            a=0.25,
            i=0.7,
            d=0.05,
            v=1,
        )
        assert m.concrete_classes == 15


class TestJDependPackagesPayload:
    def test_construction(self) -> None:
        p = JDependPackagesPayload(**_jdepend_packages_kwargs())
        assert p.bytecode_dir == "target/classes"
        assert len(p.packages) == 1

    def test_roundtrip(self) -> None:
        p = JDependPackagesPayload(**_jdepend_packages_kwargs())
        dumped = p.model_dump()
        restored = JDependPackagesPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            JDependPackagesPayload(**_jdepend_packages_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = JDependPackagesPayload(**_jdepend_packages_kwargs())
        assert p.get("bytecode_dir") == "target/classes"


class TestJDependSummaryPayload:
    def test_construction(self) -> None:
        p = JDependSummaryPayload(**_jdepend_summary_kwargs())
        assert p.total_packages == 10
        assert p.packages_with_cycles == 1
        assert len(p.cycle_groups) == 1

    def test_roundtrip(self) -> None:
        p = JDependSummaryPayload(**_jdepend_summary_kwargs())
        dumped = p.model_dump()
        restored = JDependSummaryPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            JDependSummaryPayload(**_jdepend_summary_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = JDependSummaryPayload(**_jdepend_summary_kwargs())
        assert p.get("avg_distance") == 0.15


class TestJDependSkipPayload:
    def test_construction(self) -> None:
        p = JDependSkipPayload(reason="no bytecode found")
        assert p.reason == "no bytecode found"
        assert p.stderr == ""

    def test_roundtrip(self) -> None:
        p = JDependSkipPayload(reason="no bytecode", stderr="err msg")
        dumped = p.model_dump()
        restored = JDependSkipPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            JDependSkipPayload(reason="x", bogus="y")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = JDependSkipPayload(reason="skip")
        assert p.get("reason") == "skip"


# ===========================================================================
# 11. ADR Derive payloads
# ===========================================================================


class TestAdrDerivedPayload:
    def test_construction(self) -> None:
        p = AdrDerivedPayload(**_adr_derived_kwargs())
        assert p.title == "Use event-driven architecture"
        assert p.confidence == 0.85
        assert len(p.evidence_refs) == 2

    def test_roundtrip(self) -> None:
        p = AdrDerivedPayload(**_adr_derived_kwargs())
        dumped = p.model_dump()
        restored = AdrDerivedPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            AdrDerivedPayload(**_adr_derived_kwargs(), bogus="nope")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = AdrDerivedPayload(**_adr_derived_kwargs())
        assert p.get("category") == "architecture"
        assert p["title"] == "Use event-driven architecture"
        assert "confidence" in p


class TestAdrDeriveSummaryPayload:
    def test_construction(self) -> None:
        p = AdrDeriveSummaryPayload(**_adr_derive_summary_kwargs())
        assert p.total_derived == 5
        assert p.categories == {"architecture": 3, "security": 2}

    def test_roundtrip(self) -> None:
        p = AdrDeriveSummaryPayload(**_adr_derive_summary_kwargs())
        dumped = p.model_dump()
        restored = AdrDeriveSummaryPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            AdrDeriveSummaryPayload(**_adr_derive_summary_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = AdrDeriveSummaryPayload(**_adr_derive_summary_kwargs())
        assert p.get("avg_confidence") == 0.78


class TestAdrDeriveSkipPayload:
    def test_construction(self) -> None:
        p = AdrDeriveSkipPayload(reason="no ADRs found")
        assert p.reason == "no ADRs found"

    def test_roundtrip(self) -> None:
        p = AdrDeriveSkipPayload(reason="skip")
        dumped = p.model_dump()
        restored = AdrDeriveSkipPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            AdrDeriveSkipPayload(reason="x", bogus="y")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = AdrDeriveSkipPayload(reason="no data")
        assert p.get("reason") == "no data"


# ===========================================================================
# 12. Service Mesh payloads
# ===========================================================================


class TestServiceMeshRouteDestination:
    def test_construction(self) -> None:
        d = ServiceMeshRouteDestination(host="my-svc", subset="v1", weight=80)
        assert d.host == "my-svc"
        assert d.subset == "v1"
        assert d.weight == 80

    def test_minimal(self) -> None:
        d = ServiceMeshRouteDestination(host="svc")
        assert d.subset is None
        assert d.weight is None


class TestServiceMeshRetries:
    def test_construction(self) -> None:
        r = ServiceMeshRetries(attempts=3, per_try_timeout="10s", retry_on="5xx")
        assert r.attempts == 3

    def test_minimal(self) -> None:
        r = ServiceMeshRetries()
        assert r.attempts is None


class TestServiceMeshHttpRoute:
    def test_construction(self) -> None:
        dest = ServiceMeshRouteDestination(host="svc")
        route = ServiceMeshHttpRoute(destinations=[dest], timeout="30s")
        assert len(route.destinations) == 1
        assert route.timeout == "30s"
        assert route.retries is None


class TestServiceMeshSubset:
    def test_construction(self) -> None:
        s = ServiceMeshSubset(name="v1", labels={"version": "v1"})
        assert s.name == "v1"
        assert s.traffic_policy is None


class TestServiceMeshVirtualServicePayload:
    def test_construction(self) -> None:
        p = ServiceMeshVirtualServicePayload(**_sm_virtual_service_kwargs())
        assert p.name == "my-vs"
        assert p.has_weighted_routing is True
        assert p.total_routes == 1
        assert len(p.http_routes) == 1

    def test_roundtrip(self) -> None:
        p = ServiceMeshVirtualServicePayload(**_sm_virtual_service_kwargs())
        dumped = p.model_dump()
        restored = ServiceMeshVirtualServicePayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            ServiceMeshVirtualServicePayload(**_sm_virtual_service_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = ServiceMeshVirtualServicePayload(**_sm_virtual_service_kwargs())
        assert p.get("name") == "my-vs"
        assert p["has_weighted_routing"] is True
        assert "hosts" in p


class TestServiceMeshDestinationRulePayload:
    def test_construction(self) -> None:
        p = ServiceMeshDestinationRulePayload(**_sm_destination_rule_kwargs())
        assert p.name == "my-dr"
        assert p.host == "my-svc"
        assert p.tls_mode == "ISTIO_MUTUAL"
        assert p.has_connection_pool is True
        assert p.has_outlier_detection is True

    def test_roundtrip(self) -> None:
        p = ServiceMeshDestinationRulePayload(**_sm_destination_rule_kwargs())
        dumped = p.model_dump()
        restored = ServiceMeshDestinationRulePayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            ServiceMeshDestinationRulePayload(**_sm_destination_rule_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = ServiceMeshDestinationRulePayload(**_sm_destination_rule_kwargs())
        assert p.get("tls_mode") == "ISTIO_MUTUAL"


class TestServiceMeshRolloutPayload:
    def test_construction(self) -> None:
        p = ServiceMeshRolloutPayload(**_sm_rollout_kwargs())
        assert p.name == "my-rollout"
        assert p.strategy_type == "canary"
        assert p.has_analysis is True
        assert p.replicas == 5

    def test_roundtrip(self) -> None:
        p = ServiceMeshRolloutPayload(**_sm_rollout_kwargs())
        dumped = p.model_dump()
        restored = ServiceMeshRolloutPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            ServiceMeshRolloutPayload(**_sm_rollout_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = ServiceMeshRolloutPayload(**_sm_rollout_kwargs())
        assert p.get("strategy_type") == "canary"


class TestServiceMeshAnalysisMetric:
    def test_construction(self) -> None:
        m = ServiceMeshAnalysisMetric(
            name="success-rate",
            success_condition="result[0] >= 0.95",
            interval="1m",
            count=5,
        )
        assert m.name == "success-rate"
        assert m.count == 5


class TestServiceMeshAnalysisArg:
    def test_construction(self) -> None:
        a = ServiceMeshAnalysisArg(name="svc", value="my-svc")
        assert a.name == "svc"
        assert a.value == "my-svc"

    def test_default_value(self) -> None:
        a = ServiceMeshAnalysisArg(name="svc")
        assert a.value is None


class TestServiceMeshAnalysisTemplatePayload:
    def test_construction(self) -> None:
        p = ServiceMeshAnalysisTemplatePayload(**_sm_analysis_template_kwargs())
        assert p.name == "success-rate-template"
        assert p.has_metrics is True
        assert len(p.metrics) == 1
        assert len(p.args) == 1

    def test_roundtrip(self) -> None:
        p = ServiceMeshAnalysisTemplatePayload(**_sm_analysis_template_kwargs())
        dumped = p.model_dump()
        restored = ServiceMeshAnalysisTemplatePayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            ServiceMeshAnalysisTemplatePayload(**_sm_analysis_template_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = ServiceMeshAnalysisTemplatePayload(**_sm_analysis_template_kwargs())
        assert p.get("name") == "success-rate-template"


class TestServiceMeshSummaryPayload:
    def test_construction(self) -> None:
        p = ServiceMeshSummaryPayload(**_sm_summary_kwargs())
        assert p.virtual_services == 3
        assert p.destination_rules == 2
        assert p.files_failed == 0

    def test_roundtrip(self) -> None:
        p = ServiceMeshSummaryPayload(**_sm_summary_kwargs())
        dumped = p.model_dump()
        restored = ServiceMeshSummaryPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            ServiceMeshSummaryPayload(**_sm_summary_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = ServiceMeshSummaryPayload(**_sm_summary_kwargs())
        assert p.get("rollouts") == 1


# ===========================================================================
# 13. Telemetry payloads
# ===========================================================================


class TestTelemetryExporterTarget:
    def test_construction(self) -> None:
        t = TelemetryExporterTarget(name="jaeger", type="otlp", endpoint="http://jaeger:4317")
        assert t.name == "jaeger"
        assert t.endpoint == "http://jaeger:4317"

    def test_minimal(self) -> None:
        t = TelemetryExporterTarget(name="stdout", type="logging")
        assert t.endpoint is None


class TestTelemetryPipelinePayload:
    def test_construction(self) -> None:
        p = TelemetryPipelinePayload(**_telemetry_pipeline_kwargs())
        assert p.file_path == "otel-config.yaml"
        assert p.signal_types == ["traces", "metrics"]
        assert len(p.exporter_targets) == 1
        assert p.extensions == ["health_check"]

    def test_roundtrip(self) -> None:
        p = TelemetryPipelinePayload(**_telemetry_pipeline_kwargs())
        dumped = p.model_dump()
        restored = TelemetryPipelinePayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            TelemetryPipelinePayload(**_telemetry_pipeline_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = TelemetryPipelinePayload(**_telemetry_pipeline_kwargs())
        assert p.get("file_path") == "otel-config.yaml"
        assert p["signal_types"] == ["traces", "metrics"]
        assert "pipelines" in p


class TestTelemetrySdkInitPayload:
    def test_construction(self) -> None:
        p = TelemetrySdkInitPayload(**_telemetry_sdk_init_kwargs())
        assert p.language == "java"
        assert p.instrumentation_type == "manual"
        assert "traces" in p.configured_signals

    def test_roundtrip(self) -> None:
        p = TelemetrySdkInitPayload(**_telemetry_sdk_init_kwargs())
        dumped = p.model_dump()
        restored = TelemetrySdkInitPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            TelemetrySdkInitPayload(**_telemetry_sdk_init_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = TelemetrySdkInitPayload(**_telemetry_sdk_init_kwargs())
        assert p.get("language") == "java"


class TestTelemetrySyntheticConfigPayload:
    def test_construction(self) -> None:
        p = TelemetrySyntheticConfigPayload(**_telemetry_synthetic_kwargs())
        assert p.tool == "playwright"
        assert p.test_type == "browser"
        assert p.frequency == "5m"

    def test_minimal(self) -> None:
        p = TelemetrySyntheticConfigPayload(
            file_path="synth.yaml",
            tool="k6",
            test_type="load",
            targets=["http://localhost"],
        )
        assert p.frequency is None

    def test_roundtrip(self) -> None:
        p = TelemetrySyntheticConfigPayload(**_telemetry_synthetic_kwargs())
        dumped = p.model_dump()
        restored = TelemetrySyntheticConfigPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            TelemetrySyntheticConfigPayload(**_telemetry_synthetic_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = TelemetrySyntheticConfigPayload(**_telemetry_synthetic_kwargs())
        assert p.get("tool") == "playwright"


class TestTelemetryConfigSummaryPayload:
    def test_construction(self) -> None:
        p = TelemetryConfigSummaryPayload(**_telemetry_summary_kwargs())
        assert p.collector_configs_found == 2
        assert p.sdk_instrumentations_found == 3
        assert p.signal_coverage == {"traces": True, "metrics": True, "logs": False}

    def test_roundtrip(self) -> None:
        p = TelemetryConfigSummaryPayload(**_telemetry_summary_kwargs())
        dumped = p.model_dump()
        restored = TelemetryConfigSummaryPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            TelemetryConfigSummaryPayload(**_telemetry_summary_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = TelemetryConfigSummaryPayload(**_telemetry_summary_kwargs())
        assert p.get("files_parsed") == 6
        assert p["files_failed"] == 0
        assert "signal_coverage" in p


# ===========================================================================
# 14. Terraform payloads
# ===========================================================================


class TestTerraformRequiredProvider:
    def test_construction(self) -> None:
        rp = TerraformRequiredProvider(
            name="aws", source="hashicorp/aws", version_constraint="~> 5.0"
        )
        assert rp.name == "aws"
        assert rp.source == "hashicorp/aws"

    def test_minimal(self) -> None:
        rp = TerraformRequiredProvider(name="local")
        assert rp.source is None
        assert rp.version_constraint is None


class TestTerraformBlock:
    def test_construction(self) -> None:
        rp = TerraformRequiredProvider(name="aws")
        tb = TerraformBlock(
            backend_type="s3", required_version=">= 1.5", required_providers=[rp]
        )
        assert tb.backend_type == "s3"
        assert len(tb.required_providers) == 1

    def test_minimal(self) -> None:
        tb = TerraformBlock(required_providers=[])
        assert tb.backend_type is None
        assert tb.required_version is None


class TestTerraformProviderBlock:
    def test_construction(self) -> None:
        pb = TerraformProviderBlock(name="aws", version="5.31.0", line=10)
        assert pb.name == "aws"
        assert pb.alias is None


class TestTerraformResourceBlock:
    def test_construction(self) -> None:
        rb = TerraformResourceBlock(
            type="aws_instance", name="web", body_text='ami = "abc"', line=20
        )
        assert rb.type == "aws_instance"
        assert rb.name == "web"


class TestTerraformDataBlock:
    def test_construction(self) -> None:
        db = TerraformDataBlock(
            type="aws_ami", name="ubuntu", body_text='owners = ["self"]', line=30
        )
        assert db.type == "aws_ami"


class TestTerraformVariableBlock:
    def test_construction(self) -> None:
        vb = TerraformVariableBlock(
            name="region", has_description=True, has_type=True, has_default=True
        )
        assert vb.name == "region"
        assert vb.has_description is True


class TestTerraformModuleBlock:
    def test_construction(self) -> None:
        mb = TerraformModuleBlock(
            name="vpc", source="terraform-aws-modules/vpc/aws", version="5.1.0"
        )
        assert mb.name == "vpc"

    def test_minimal(self) -> None:
        mb = TerraformModuleBlock(name="local-mod")
        assert mb.source is None
        assert mb.version is None


class TestTerraformAnalysisPayload:
    def test_construction(self) -> None:
        p = TerraformAnalysisPayload(**_terraform_kwargs())
        assert p.file_path == "main.tf"
        assert len(p.terraform_blocks) == 1
        assert len(p.provider_blocks) == 1
        assert len(p.resource_blocks) == 1
        assert len(p.data_blocks) == 1
        assert len(p.variable_blocks) == 1
        assert len(p.module_blocks) == 1

    def test_roundtrip(self) -> None:
        p = TerraformAnalysisPayload(**_terraform_kwargs())
        dumped = p.model_dump()
        restored = TerraformAnalysisPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            TerraformAnalysisPayload(**_terraform_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = TerraformAnalysisPayload(**_terraform_kwargs())
        assert p.get("file_path") == "main.tf"
        assert p["file_path"] == "main.tf"
        assert "terraform_blocks" in p


# ===========================================================================
# 15. Proto payloads
# ===========================================================================


class TestProtoField:
    def test_construction(self) -> None:
        f = ProtoField(name="id", number=1, type="int64", label="optional", line=5)
        assert f.name == "id"
        assert f.number == 1


class TestProtoReservedRange:
    def test_construction(self) -> None:
        r = ProtoReservedRange(start=10, end=20)
        assert r.start == 10
        assert r.end == 20


class TestProtoMessage:
    def test_construction(self) -> None:
        field = ProtoField(name="id", number=1, type="int64", label="optional", line=5)
        msg = ProtoMessage(
            name="User",
            line=3,
            has_comment=True,
            fields=[field],
            reserved_numbers=[15],
            reserved_ranges=[ProtoReservedRange(start=10, end=20)],
        )
        assert msg.name == "User"
        assert len(msg.fields) == 1
        assert msg.reserved_numbers == [15]


class TestProtoRpcMethod:
    def test_construction(self) -> None:
        rpc = ProtoRpcMethod(
            name="GetUser",
            request_type="GetUserRequest",
            response_type="GetUserResponse",
            line=20,
            has_comment=True,
        )
        assert rpc.name == "GetUser"
        assert rpc.request_type == "GetUserRequest"


class TestProtoService:
    def test_construction(self) -> None:
        rpc = ProtoRpcMethod(
            name="GetUser",
            request_type="GetUserRequest",
            response_type="GetUserResponse",
            line=20,
            has_comment=True,
        )
        svc = ProtoService(name="UserService", line=18, has_comment=True, methods=[rpc])
        assert svc.name == "UserService"
        assert len(svc.methods) == 1


class TestProtoEnumValue:
    def test_construction(self) -> None:
        ev = ProtoEnumValue(name="UNKNOWN", number=0)
        assert ev.name == "UNKNOWN"
        assert ev.number == 0


class TestProtoEnum:
    def test_construction(self) -> None:
        ev = ProtoEnumValue(name="UNKNOWN", number=0)
        enum = ProtoEnum(name="Status", line=30, enum_values=[ev])
        assert enum.name == "Status"
        assert len(enum.enum_values) == 1


class TestProtoAnalysisPayload:
    def test_construction(self) -> None:
        p = ProtoAnalysisPayload(**_proto_kwargs())
        assert p.file_path == "user.proto"
        assert p.syntax == "proto3"
        assert p.package == "example.v1"
        assert len(p.messages) == 1
        assert len(p.services) == 1
        assert len(p.enums) == 1

    def test_minimal(self) -> None:
        p = ProtoAnalysisPayload(
            file_path="empty.proto",
            imports=[],
            messages=[],
            services=[],
            enums=[],
        )
        assert p.syntax is None
        assert p.package is None

    def test_roundtrip(self) -> None:
        p = ProtoAnalysisPayload(**_proto_kwargs())
        dumped = p.model_dump()
        restored = ProtoAnalysisPayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            ProtoAnalysisPayload(**_proto_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = ProtoAnalysisPayload(**_proto_kwargs())
        assert p.get("syntax") == "proto3"
        assert p["package"] == "example.v1"
        assert "messages" in p


# ===========================================================================
# 16. Java AST payloads
# ===========================================================================


class TestJavaParameter:
    def test_construction(self) -> None:
        p = JavaParameter(name="id", type="long")
        assert p.name == "id"
        assert p.type == "long"


class TestJavaBaseClass:
    def test_construction(self) -> None:
        b = JavaBaseClass(name="AbstractService", access="public")
        assert b.name == "AbstractService"
        assert b.access == "public"


class TestJavaField:
    def test_construction(self) -> None:
        f = JavaField(name="logger", type="Logger", access="private", line=10)
        assert f.name == "logger"
        assert f.line == 10


class TestJavaMethod:
    def test_construction(self) -> None:
        param = JavaParameter(name="id", type="long")
        m = JavaMethod(
            name="findById",
            annotations=["@Override"],
            return_type="User",
            access="public",
            is_virtual=False,
            is_pure_virtual=False,
            line=15,
            parameters=[param],
            mapping_paths=["/users/{id}"],
        )
        assert m.name == "findById"
        assert len(m.parameters) == 1
        assert m.mapping_paths == ["/users/{id}"]


class TestJavaClass:
    def test_construction(self) -> None:
        cls = JavaClass(
            name="UserService",
            line=5,
            annotations=["@Service"],
            is_abstract=False,
            is_interface=False,
            base_classes=[],
            fields=[],
            methods=[],
            namespace="com.example",
            outer_class="",
        )
        assert cls.name == "UserService"
        assert cls.is_interface is False


class TestJavaCatchBlock:
    def test_construction(self) -> None:
        c = JavaCatchBlock(caught_type="IOException", rethrows=True, line=30)
        assert c.caught_type == "IOException"
        assert c.rethrows is True


class TestJavaThreadPool:
    def test_construction(self) -> None:
        tp = JavaThreadPool(
            class_name="ThreadPoolExecutor",
            line=40,
            has_bounded_queue=True,
            has_rejection_policy=True,
        )
        assert tp.class_name == "ThreadPoolExecutor"
        assert tp.has_bounded_queue is True


class TestJavaLogStatement:
    def test_construction(self) -> None:
        log = JavaLogStatement(method="info", arguments_text='"Starting"', line=3)
        assert log.method == "info"


class TestJavaAstFilePayload:
    def test_construction(self) -> None:
        p = JavaAstFilePayload(**_java_ast_kwargs())
        assert p.file_path == "src/main/java/UserService.java"
        assert p.package == "com.example.service"
        assert len(p.classes) == 1
        assert len(p.methods) == 1
        assert len(p.catch_blocks) == 1
        assert len(p.imports) == 2
        assert len(p.thread_pool_constructions) == 1
        assert len(p.log_statements) == 1

    def test_roundtrip(self) -> None:
        p = JavaAstFilePayload(**_java_ast_kwargs())
        dumped = p.model_dump()
        restored = JavaAstFilePayload(**dumped)
        assert restored == p

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            JavaAstFilePayload(**_java_ast_kwargs(), bogus="x")  # type: ignore[call-arg]

    def test_dict_compat_get(self) -> None:
        p = JavaAstFilePayload(**_java_ast_kwargs())
        assert p.get("package") == "com.example.service"
        assert p["file_path"] == "src/main/java/UserService.java"
        assert "classes" in p
