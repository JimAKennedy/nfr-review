# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Structured metadata for every registered rule.

Provides :class:`RuleMetadata` (Pydantic model) and :data:`RULE_METADATA`, a
dict keyed by ``rule.id`` that maps every built-in rule to its metadata.
Used by ``list-rules --format json`` and the static rule catalogue (S03).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nfr_review.models import Severity


class RuleMetadata(BaseModel):
    """Structured metadata for one rule, suitable for catalogue and JSON export."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity
    category: str = Field(description="ISO 25010 category")
    tags: list[str] = Field(default_factory=list)
    description: str = Field(description="One-paragraph explanation")
    compliance_refs: list[str] = Field(default_factory=list)


def _m(
    severity: Severity,
    category: str,
    description: str,
    tags: list[str] | None = None,
    refs: list[str] | None = None,
) -> RuleMetadata:
    return RuleMetadata(
        severity=severity,
        category=category,
        description=description,
        tags=tags or [],
        compliance_refs=refs or [],
    )


RULE_METADATA: dict[str, RuleMetadata] = {
    # --- ADR rules ---
    "adr-gap": _m(
        "medium",
        "maintainability",
        "Flags implicit architectural decisions in code that lack a corresponding ADR.",
        ["adr", "architecture"],
        ["ISO 25010:Maintainability"],
    ),
    "adr-lifecycle-gap": _m(
        "low",
        "maintainability",
        "Flags ADRs that exist but lack lifecycle status tracking.",
        ["adr", "architecture", "documentation"],
        ["ISO 25010:Maintainability"],
    ),
    "architectural-drift-from-adr": _m(
        "high",
        "maintainability",
        "Detects divergence between architecture decision records and actual codebase.",
        ["adr", "architecture", "llm"],
        ["ISO 25010:Maintainability"],
    ),
    # --- APIM rules ---
    "apim-auth-policy-missing": _m(
        "critical",
        "security",
        "Flags Azure API Management policies that lack authentication configuration.",
        ["apim", "azure", "auth"],
        ["ISO 25010:Security", "OWASP:A01"],
    ),
    "apim-hardcoded-backend-url": _m(
        "medium",
        "maintainability",
        "Flags APIM policies using hardcoded backend URLs instead of named values.",
        ["apim", "azure", "config"],
        ["ISO 25010:Maintainability"],
    ),
    "apim-rate-limit-missing": _m(
        "high",
        "security",
        "Flags APIM policies without rate limiting in the inbound section.",
        ["apim", "azure", "rate-limiting"],
        ["ISO 25010:Security", "OWASP:A04"],
    ),
    # --- AST cross-language rules ---
    "bare-except-catch-all": _m(
        "high",
        "reliability",
        "Flags bare except blocks and overly broad exception catch-alls across Java, Python,.",
        ["error-handling", "cross-language"],
        ["ISO 25010:Reliability"],
    ),
    "logging-to-stdout": _m(
        "medium",
        "reliability",
        "Flags direct stdout/stderr writes that should use a structured logging framework.",
        ["logging", "observability", "cross-language"],
        ["ISO 25010:Reliability"],
    ),
    # --- CI rules ---
    "ci-security-scan-missing": _m(
        "high",
        "security",
        "Flags CI pipelines that lack a security scanning step (SAST, DAST, or dependency.",
        ["ci", "security-scanning"],
        ["ISO 25010:Security", "OWASP:A06"],
    ),
    "ci-test-stage-missing": _m(
        "high",
        "reliability",
        "Flags CI pipelines that lack a test execution step.",
        ["ci", "testing"],
        ["ISO 25010:Reliability"],
    ),
    # --- CMake rules ---
    "cmake-build-config": _m(
        "medium",
        "maintainability",
        "Flags CMake projects with missing or misconfigured build type settings.",
        ["cmake", "cpp", "build"],
        ["ISO 25010:Maintainability"],
    ),
    "cmake-fetchcontent-pinning": _m(
        "high",
        "security",
        "Flags FetchContent dependencies that use unpinned branches instead of specific.",
        ["cmake", "cpp", "supply-chain"],
        ["ISO 25010:Security"],
    ),
    "cmake-minimum-version": _m(
        "low",
        "maintainability",
        "Flags CMake projects with outdated or missing cmake_minimum_required version.",
        ["cmake", "cpp"],
        ["ISO 25010:Maintainability"],
    ),
    # --- Correlation / tracing ---
    "correlation-id-missing": _m(
        "medium",
        "reliability",
        "Flags Java projects with no distributed tracing or correlation-ID library.",
        ["java", "observability", "tracing"],
        ["ISO 25010:Reliability"],
    ),
    # --- C++ rules ---
    "cpp-clang-format": _m(
        "low",
        "maintainability",
        "Flags C++ repos missing a .clang-format configuration file.",
        ["cpp", "formatting", "toolchain"],
        ["ISO 25010:Maintainability"],
    ),
    "cpp-clang-tidy": _m(
        "low",
        "maintainability",
        "Flags C++ repos missing a .clang-tidy configuration file.",
        ["cpp", "linting", "toolchain"],
        ["ISO 25010:Maintainability"],
    ),
    "cpp-dormant-classes": _m(
        "medium",
        "maintainability",
        "Flags C++ classes with high method-to-call ratio suggesting dead or underused code.",
        ["cpp", "dead-code"],
        ["ISO 25010:Maintainability"],
    ),
    "cpp-exception-safety": _m(
        "high",
        "reliability",
        "Flags C++ code with exception-safety concerns including missing noexcept and unsafe.",
        ["cpp", "error-handling"],
        ["ISO 25010:Reliability"],
    ),
    "cpp-include-guards": _m(
        "low",
        "maintainability",
        "Flags C++ headers missing include guards or #pragma once.",
        ["cpp", "headers"],
        ["ISO 25010:Maintainability"],
    ),
    "cpp-raw-memory": _m(
        "high",
        "reliability",
        "Flags raw new/delete and malloc/free usage that should use smart pointers or RAII.",
        ["cpp", "memory-safety"],
        ["ISO 25010:Reliability"],
    ),
    "cpp-sanitizer-ci": _m(
        "medium",
        "reliability",
        "Flags C++ CI pipelines that lack address/thread/memory sanitizer builds.",
        ["cpp", "ci", "sanitizers"],
        ["ISO 25010:Reliability"],
    ),
    # --- C# rules ---
    "csharp-async-void": _m(
        "high",
        "reliability",
        "Flags async void methods that should be async Task to avoid unobserved exceptions.",
        ["csharp", "async"],
        ["ISO 25010:Reliability"],
    ),
    "csharp-blocking-async": _m(
        "high",
        "performance",
        "Flags synchronous blocking on async operations (.Result, .Wait()) that risk thread.",
        ["csharp", "async", "threading"],
        ["ISO 25010:Performance"],
    ),
    "csharp-configure-await": _m(
        "low",
        "performance",
        "Flags await expressions missing ConfigureAwait(false) in library code.",
        ["csharp", "async"],
        ["ISO 25010:Performance"],
    ),
    "csharp-disposable-no-using": _m(
        "high",
        "reliability",
        "Flags IDisposable object creation not wrapped in a using statement, risking.",
        ["csharp", "resource-management"],
        ["ISO 25010:Reliability"],
    ),
    # --- Dependency rules ---
    "dep-freshness": _m(
        "medium",
        "security",
        "Graduated staleness and dead library detection across Python, Node.js, Java, Go,.",
        ["dependencies", "supply-chain", "cross-language"],
        ["ISO 25010:Security", "OWASP:A06"],
    ),
    "dep-upgrade-path": _m(
        "medium",
        "maintainability",
        "N-1 ceiling detection with upgrade path recommendations via constraint solving.",
        ["dependencies", "supply-chain", "cross-language"],
        ["ISO 25010:Maintainability"],
    ),
    # --- Dockerfile rules ---
    "dockerfile-base-pinning": _m(
        "high",
        "security",
        "Flags Docker base images using floating tags instead of pinned versions or digests.",
        ["docker", "supply-chain"],
        ["ISO 25010:Security", "OWASP:A08"],
    ),
    "dockerfile-k8s-image-drift": _m(
        "medium",
        "reliability",
        "Flags mismatches between Dockerfile base image tags and Kubernetes container image.",
        ["docker", "kubernetes", "consistency"],
        ["ISO 25010:Reliability"],
    ),
    "dockerfile-k8s-user-conflict": _m(
        "high",
        "security",
        "Flags Kubernetes deployments that override a Dockerfile non-root USER with.",
        ["docker", "kubernetes", "security"],
        ["ISO 25010:Security", "OWASP:A05"],
    ),
    "dockerfile-multistage": _m(
        "low",
        "performance",
        "Suggests multi-stage builds when a single-stage Dockerfile has build-time RUN.",
        ["docker", "image-size"],
        ["ISO 25010:Performance"],
    ),
    "dockerfile-secret-leakage": _m(
        "critical",
        "security",
        "Flags Dockerfiles that COPY/ADD secret files or expose secrets via ARG/ENV.",
        ["docker", "secrets"],
        ["ISO 25010:Security", "OWASP:A02"],
    ),
    "dockerfile-user-directive": _m(
        "high",
        "security",
        "Flags Dockerfiles that lack a USER directive, causing containers to run as root.",
        ["docker", "security"],
        ["ISO 25010:Security", "OWASP:A05"],
    ),
    # --- Dormant classes (Java) ---
    "java-dormant-classes": _m(
        "medium",
        "maintainability",
        "Flags Java classes with high method count but low usage, suggesting dead or.",
        ["java", "dead-code"],
        ["ISO 25010:Maintainability"],
    ),
    # --- Gatling ---
    "gatling-performance-thresholds": _m(
        "medium",
        "performance",
        "Evaluates Gatling load test results against configurable performance thresholds.",
        ["performance-testing", "gatling"],
        ["ISO 25010:Performance"],
    ),
    # --- Go rules ---
    "go-defer-in-loop": _m(
        "high",
        "reliability",
        "Flags defer statements inside for loops that accumulate deferred calls until.",
        ["go", "resource-management"],
        ["ISO 25010:Reliability"],
    ),
    "go-dormant-classes": _m(
        "medium",
        "maintainability",
        "Flags Go types with high method count but low usage, suggesting dead or underused.",
        ["go", "dead-code"],
        ["ISO 25010:Maintainability"],
    ),
    "go-error-ignored": _m(
        "high",
        "reliability",
        "Flags Go error return values explicitly discarded via blank identifier assignment.",
        ["go", "error-handling"],
        ["ISO 25010:Reliability"],
    ),
    "go-goroutine-leak": _m(
        "high",
        "reliability",
        "Flags goroutine launches without explicit lifecycle management (context, WaitGroup,.",
        ["go", "concurrency"],
        ["ISO 25010:Reliability"],
    ),
    "go-http-no-timeout": _m(
        "high",
        "reliability",
        "Flags HTTP calls using http.DefaultClient or custom Client without Timeout.",
        ["go", "http", "timeout"],
        ["ISO 25010:Reliability"],
    ),
    # --- Health / Spring ---
    "health-endpoint-missing": _m(
        "high",
        "reliability",
        "Flags Java services with no @RestController exposing a health-check endpoint.",
        ["java", "health", "observability"],
        ["ISO 25010:Reliability"],
    ),
    "health-probe-separation": _m(
        "medium",
        "reliability",
        "Flags Kubernetes containers whose liveness and readiness probes are identically.",
        ["kubernetes", "health", "probes"],
        ["ISO 25010:Reliability"],
    ),
    # --- Helm rules ---
    "helm-chart-metadata": _m(
        "low",
        "maintainability",
        "Flags Helm charts with incomplete Chart.yaml metadata (missing version,.",
        ["helm", "metadata"],
        ["ISO 25010:Maintainability"],
    ),
    "helm-secret-leakage": _m(
        "critical",
        "security",
        "Flags plaintext secrets in Helm values.yaml and rendered manifest templates.",
        ["helm", "secrets"],
        ["ISO 25010:Security", "OWASP:A02"],
    ),
    "helm-values-validation": _m(
        "medium",
        "reliability",
        "Flags Helm charts with missing resource limits, replica counts, or.",
        ["helm", "configuration"],
        ["ISO 25010:Reliability"],
    ),
    # --- Istio rules ---
    "istio-circuit-breaker": _m(
        "high",
        "reliability",
        "Flags DestinationRules that lack outlierDetection for circuit breaking.",
        ["istio", "resilience", "service-mesh"],
        ["ISO 25010:Reliability"],
    ),
    "istio-mtls-strict": _m(
        "critical",
        "security",
        "Flags Istio meshes where PeerAuthentication does not enforce STRICT mTLS.",
        ["istio", "mtls", "service-mesh"],
        ["ISO 25010:Security", "OWASP:A02"],
    ),
    "istio-traffic-policy": _m(
        "medium",
        "performance",
        "Flags DestinationRules that lack trafficPolicy with connectionPool settings.",
        ["istio", "traffic", "service-mesh"],
        ["ISO 25010:Performance"],
    ),
    # --- JaCoCo rules ---
    "jacoco-coverage-actual": _m(
        "medium",
        "reliability",
        "Evaluates actual line and branch coverage from JaCoCo XML reports against.",
        ["java", "testing", "coverage"],
        ["ISO 25010:Reliability"],
    ),
    "jacoco-threshold-missing": _m(
        "medium",
        "reliability",
        "Flags Java projects with no JaCoCo dependency or plugin configured.",
        ["java", "testing", "coverage"],
        ["ISO 25010:Reliability"],
    ),
    # --- Java rules ---
    "exception-handling-antipattern": _m(
        "high",
        "reliability",
        "Flags catch blocks that swallow Exception/Throwable without rethrowing or logging.",
        ["java", "error-handling"],
        ["ISO 25010:Reliability"],
    ),
    "logging-config-missing": _m(
        "medium",
        "reliability",
        "Flags Spring Boot apps without structured logging (JSON/logstash encoder).",
        ["java", "spring", "logging", "observability"],
        ["ISO 25010:Reliability"],
    ),
    "resilience-annotation-missing": _m(
        "high",
        "reliability",
        "Flags classes that import HTTP clients but lack resilience annotations (@Retry,.",
        ["java", "resilience"],
        ["ISO 25010:Reliability"],
    ),
    "thread-pool-misconfiguration": _m(
        "high",
        "performance",
        "Flags ThreadPoolExecutor instances without bounded queue or rejection policy.",
        ["java", "threading", "concurrency"],
        ["ISO 25010:Performance"],
    ),
    # --- JDepend rules ---
    "JDEP-CYCLE": _m(
        "high",
        "maintainability",
        "Flags Java package cycles detected by JDepend analysis.",
        ["java", "jdepend", "architecture"],
        ["ISO 25010:Maintainability"],
    ),
    "JDEP-DISTANCE": _m(
        "medium",
        "maintainability",
        "Flags Java packages with distance from main sequence (D) above 0.5.",
        ["java", "jdepend", "architecture"],
        ["ISO 25010:Maintainability"],
    ),
    "JDEP-INSTABILITY": _m(
        "medium",
        "performance",
        "Flags Java packages with high instability (I > 0.8) and low abstractness.",
        ["java", "jdepend", "architecture"],
        ["ISO 25010:Performance"],
    ),
    # --- Kubernetes rules ---
    "network-policy-missing": _m(
        "high",
        "security",
        "Flags Kubernetes namespaces with no NetworkPolicy resources defined.",
        ["kubernetes", "network"],
        ["ISO 25010:Security", "OWASP:A05"],
    ),
    "probes-missing": _m(
        "high",
        "reliability",
        "Flags Kubernetes containers missing livenessProbe or readinessProbe.",
        ["kubernetes", "health", "probes"],
        ["ISO 25010:Reliability"],
    ),
    "resource-limits-missing": _m(
        "high",
        "reliability",
        "Flags Kubernetes containers without resources.limits defined.",
        ["kubernetes", "resource-management"],
        ["ISO 25010:Reliability"],
    ),
    "non-root-container-violation": _m(
        "high",
        "security",
        "Flags Kubernetes containers without securityContext.runAsNonRoot=true.",
        ["kubernetes", "security"],
        ["ISO 25010:Security", "OWASP:A05"],
    ),
    # --- Node.js rules ---
    "nodejs-callback-error-ignored": _m(
        "high",
        "reliability",
        "Flags Node.js callbacks that receive an error parameter but never check or.",
        ["nodejs", "error-handling"],
        ["ISO 25010:Reliability"],
    ),
    "nodejs-floating-promise": _m(
        "high",
        "reliability",
        "Flags promise chains without .catch() that risk unhandled promise rejections.",
        ["nodejs", "async", "error-handling"],
        ["ISO 25010:Reliability"],
    ),
    "nodejs-promise-no-catch": _m(
        "high",
        "reliability",
        "Flags .then() chains without .catch() error handling.",
        ["nodejs", "async", "error-handling"],
        ["ISO 25010:Reliability"],
    ),
    "nodejs-sync-fs-api": _m(
        "medium",
        "performance",
        "Flags synchronous fs and child_process calls that block the Node.js event loop.",
        ["nodejs", "performance", "async"],
        ["ISO 25010:Performance"],
    ),
    # --- OTel rules ---
    "otel-exporter-config": _m(
        "high",
        "reliability",
        "Flags OTel Collector configs where no production exporter is configured.",
        ["otel", "observability"],
        ["ISO 25010:Reliability"],
    ),
    "otel-pipeline-completeness": _m(
        "medium",
        "reliability",
        "Flags OTel Collector configs where not all signal types (traces, metrics, logs).",
        ["otel", "observability"],
        ["ISO 25010:Reliability"],
    ),
    "otel-sampling": _m(
        "medium",
        "performance",
        "Flags OTel Collector configs without sampling or rate-limiting processors.",
        ["otel", "observability", "performance"],
        ["ISO 25010:Performance"],
    ),
    # --- OTel readiness rules (S01) ---
    "otel-test-agent": _m(
        "medium",
        "reliability",
        "Flags repos where test profiles don't attach the OTel agent.",
        ["otel", "observability", "testing"],
        ["ISO 25010:Reliability"],
    ),
    "otel-file-exporter": _m(
        "medium",
        "reliability",
        "Flags repos without an OTel file exporter configured for CI trace capture.",
        ["otel", "observability", "ci"],
        ["ISO 25010:Reliability"],
    ),
    "otel-w3c-propagation": _m(
        "medium",
        "reliability",
        "Flags repos without W3C trace-context propagation configured.",
        ["otel", "observability", "tracing"],
        ["ISO 25010:Reliability"],
    ),
    "otel-resource-attrs": _m(
        "medium",
        "reliability",
        "Flags repos without required OTel resource attributes.",
        ["otel", "observability", "tracing"],
        ["ISO 25010:Reliability"],
    ),
    # --- OTel test-coverage rules (S02) ---
    "otel-integration-test-coverage": _m(
        "medium",
        "reliability",
        "Flags repos where API endpoints lack corresponding integration tests.",
        ["testing", "coverage", "observability"],
        ["ISO 25010:Reliability"],
    ),
    "otel-fault-injection-tests": _m(
        "medium",
        "reliability",
        "Flags repos with resilience patterns but no fault-injection tests.",
        ["testing", "resilience", "chaos"],
        ["ISO 25010:Reliability"],
    ),
    "otel-test-observability": _m(
        "medium",
        "reliability",
        "Flags test configs that don't produce OTel traces for dynamic analysis.",
        ["otel", "testing", "observability"],
        ["ISO 25010:Reliability"],
    ),
    # --- OTel dynamic analysis rules (S03) ---
    "dyn-method-coverage": _m(
        "info",
        "reliability",
        "Reports which instrumented methods were exercised during a test "
        "run by aggregating code.namespace and code.function span attributes.",
        ["otel", "observability", "dynamic-analysis", "coverage"],
        ["ISO 25010:Reliability"],
    ),
    "dyn-call-sequence": _m(
        "info",
        "reliability",
        "Generates Mermaid sequence diagrams from OTel trace span trees "
        "to visualise runtime call flows.",
        ["otel", "observability", "dynamic-analysis", "tracing"],
        ["ISO 25010:Reliability"],
    ),
    # --- PATCH rules (patching safety) ---
    "PATCH-ARCH-001": _m(
        "high",
        "reliability",
        "Flags Deployment/StatefulSet resources running with a single replica, making.",
        ["kubernetes", "patching", "availability"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-ARCH-002": _m(
        "high",
        "reliability",
        "Flags workloads missing preStop hooks or with insufficient.",
        ["kubernetes", "patching", "graceful-shutdown"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-ARCH-003": _m(
        "high",
        "reliability",
        "Flags workloads with missing or unsafe update/rollout strategy (e.g. Recreate.",
        ["kubernetes", "patching", "rollout"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-ARCH-004": _m(
        "medium",
        "reliability",
        "Flags multi-replica Deployments/StatefulSets with no matching PodDisruptionBudget.",
        ["kubernetes", "patching", "pdb"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-DEPS-001": _m(
        "low",
        "maintainability",
        "Detects dependency declaration annotations on Kubernetes workloads for patch.",
        ["kubernetes", "patching", "dependencies"],
        ["ISO 25010:Maintainability"],
    ),
    "PATCH-DEPS-002": _m(
        "medium",
        "reliability",
        "Detects shared-fate indicators across workloads (common volumes, configmaps,.",
        ["kubernetes", "patching", "dependencies"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-DEPS-003": _m(
        "high",
        "reliability",
        "Detects cross-ring dependency direction violations in patch deployment ordering.",
        ["kubernetes", "patching", "dependencies"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-HEALTH-001": _m(
        "high",
        "reliability",
        "Checks readiness/liveness probes in the context of patching safety and rolling.",
        ["kubernetes", "patching", "probes"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-HEALTH-002": _m(
        "medium",
        "reliability",
        "Flags readiness probes that are likely trivial or overly fragile during patching.",
        ["kubernetes", "patching", "probes"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-HEALTH-003": _m(
        "high",
        "reliability",
        "Checks startup probe presence for patching safety with slow-starting containers.",
        ["kubernetes", "patching", "probes"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-HEALTH-004": _m(
        "medium",
        "reliability",
        "Flags workloads with insufficient terminationGracePeriodSeconds for safe patching.",
        ["kubernetes", "patching", "graceful-shutdown"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-ROLL-001": _m(
        "medium",
        "maintainability",
        "Checks for rollback/disaster-recovery documentation in the repository root.",
        ["patching", "rollback", "documentation"],
        ["ISO 25010:Maintainability"],
    ),
    "PATCH-ROLL-002": _m(
        "medium",
        "reliability",
        "Checks that at least one CI pipeline has a rollback or revert stage.",
        ["patching", "rollback", "ci"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-ROLL-003": _m(
        "medium",
        "maintainability",
        "Detects migration tooling without corresponding rollback evidence.",
        ["patching", "rollback", "migrations"],
        ["ISO 25010:Maintainability"],
    ),
    "PATCH-SCOPE-001": _m(
        "low",
        "reliability",
        "Detects patch class soak configuration for graduated rollouts.",
        ["patching", "rollout"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-SCOPE-002": _m(
        "medium",
        "security",
        "Detects accelerated cadence configuration for critical-security patches.",
        ["patching", "security"],
        ["ISO 25010:Security"],
    ),
    "PATCH-TELEM-001": _m(
        "medium",
        "reliability",
        "Detects golden signal emission coverage (latency, traffic, errors, saturation) via.",
        ["patching", "observability", "otel"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-TELEM-002": _m(
        "low",
        "reliability",
        "Detects mandatory label presence (service.name, service.version) in OTel resource.",
        ["patching", "observability", "otel"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-TELEM-003": _m(
        "medium",
        "reliability",
        "Detects synthetic transaction configuration for proactive failure detection.",
        ["patching", "observability"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-TRAFFIC-001": _m(
        "high",
        "reliability",
        "Detects progressive traffic shifting configuration (canary/blue-green) in service.",
        ["patching", "traffic", "service-mesh"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-TRAFFIC-002": _m(
        "medium",
        "reliability",
        "Detects failover/DR documentation in the repository root.",
        ["patching", "traffic", "documentation"],
        ["ISO 25010:Reliability"],
    ),
    "PATCH-TRAFFIC-003": _m(
        "medium",
        "reliability",
        "Detects connection draining configuration in service mesh for graceful traffic.",
        ["patching", "traffic", "service-mesh"],
        ["ISO 25010:Reliability"],
    ),
    # --- PII ---
    "pii-in-log-statements": _m(
        "critical",
        "security",
        "Flags log statements that emit PII fields (email, SSN, credit card) using regex and.",
        ["java", "pii", "logging", "llm"],
        ["ISO 25010:Security", "OWASP:A01"],
    ),
    # --- Proto/gRPC rules ---
    "proto-field-numbering": _m(
        "high",
        "maintainability",
        "Flags protobuf messages where field number gaps exist without matching reserved.",
        ["grpc", "protobuf", "api"],
        ["ISO 25010:Maintainability"],
    ),
    "proto-method-comments": _m(
        "low",
        "maintainability",
        "Flags gRPC service methods that lack preceding comment documentation.",
        ["grpc", "protobuf", "documentation"],
        ["ISO 25010:Maintainability"],
    ),
    "proto-service-versioning": _m(
        "medium",
        "maintainability",
        "Flags gRPC services that lack version indicators in name or package.",
        ["grpc", "protobuf", "versioning"],
        ["ISO 25010:Maintainability"],
    ),
    # --- Python rules ---
    "python-async-fire-and-forget": _m(
        "high",
        "reliability",
        "Flags asyncio.create_task() calls where the returned Task reference is not stored.",
        ["python", "async", "concurrency"],
        ["ISO 25010:Reliability"],
    ),
    "python-broad-except-silent": _m(
        "high",
        "reliability",
        "Flags catch blocks that silently swallow Exception/BaseException without logging or.",
        ["python", "error-handling"],
        ["ISO 25010:Reliability"],
    ),
    "python-dormant-classes": _m(
        "medium",
        "maintainability",
        "Flags Python classes with high method count but low usage, suggesting dead or.",
        ["python", "dead-code"],
        ["ISO 25010:Maintainability"],
    ),
    "python-mutable-default": _m(
        "high",
        "reliability",
        "Flags function definitions using mutable default arguments (list, dict, set).",
        ["python", "correctness"],
        ["ISO 25010:Reliability"],
    ),
    "python-star-import": _m(
        "medium",
        "maintainability",
        "Flags wildcard imports (from x import *) that obscure dependencies and pollute.",
        ["python", "imports"],
        ["ISO 25010:Maintainability"],
    ),
    # --- Sample rule ---
    "sample-readme-exists": _m(
        "low",
        "maintainability",
        "Verifies a README file exists at the repository root.",
        ["documentation", "repo-structure"],
        ["ISO 25010:Maintainability"],
    ),
    # --- Skaffold ---
    "skaffold-build-config": _m(
        "medium",
        "maintainability",
        "Flags Skaffold configs missing build sections or with weak tag policies.",
        ["skaffold", "build", "kubernetes"],
        ["ISO 25010:Maintainability"],
    ),
    # --- Spring rules ---
    "actuator-exposure-risk": _m(
        "critical",
        "security",
        "Flags Spring Boot actuator endpoints exposed without access restriction.",
        ["java", "spring", "actuator"],
        ["ISO 25010:Security", "OWASP:A01"],
    ),
    "spring-profile-misconfiguration": _m(
        "high",
        "security",
        "Flags production Spring profiles with debug logging, in-memory databases, or.",
        ["java", "spring", "configuration"],
        ["ISO 25010:Security"],
    ),
    # --- Terraform rules ---
    "terraform-iam-policy": _m(
        "critical",
        "security",
        "Flags IAM policies with wildcard (*) actions or resources in Terraform definitions.",
        ["terraform", "iam", "cloud"],
        ["ISO 25010:Security", "OWASP:A01"],
    ),
    "terraform-provider-pinning": _m(
        "high",
        "security",
        "Flags Terraform providers that lack version constraints, risking uncontrolled.",
        ["terraform", "supply-chain"],
        ["ISO 25010:Security"],
    ),
    "terraform-state-backend": _m(
        "high",
        "security",
        "Flags Terraform repos that store state locally instead of using a remote backend.",
        ["terraform", "state"],
        ["ISO 25010:Security"],
    ),
}


def get_metadata(rule_id: str) -> RuleMetadata | None:
    """Look up metadata for a rule by its id. Returns None if not catalogued."""
    return RULE_METADATA.get(rule_id)


__all__ = ["RuleMetadata", "RULE_METADATA", "get_metadata"]
