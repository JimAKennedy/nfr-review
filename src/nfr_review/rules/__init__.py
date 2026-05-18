"""Built-in rules. Importing this package auto-registers them."""

from __future__ import annotations

from nfr_review.rules import adr_drift as adr_drift  # noqa: F401
from nfr_review.rules import adr_lifecycle as adr_lifecycle  # noqa: F401
from nfr_review.rules import apim_auth as apim_auth  # noqa: F401
from nfr_review.rules import apim_backend_url as apim_backend_url  # noqa: F401
from nfr_review.rules import apim_rate_limit as apim_rate_limit  # noqa: F401
from nfr_review.rules import ast_bare_except as ast_bare_except  # noqa: F401
from nfr_review.rules import ast_logging_stdout as ast_logging_stdout  # noqa: F401
from nfr_review.rules import ci_security_scan as ci_security_scan  # noqa: F401
from nfr_review.rules import ci_test_stage as ci_test_stage  # noqa: F401
from nfr_review.rules import (
    csharp_async_void as csharp_async_void,  # noqa: F401
)
from nfr_review.rules import (
    csharp_blocking_async as csharp_blocking_async,  # noqa: F401
)
from nfr_review.rules import (
    csharp_configure_await as csharp_configure_await,  # noqa: F401
)
from nfr_review.rules import (
    csharp_disposable_no_using as csharp_disposable_no_using,  # noqa: F401
)
from nfr_review.rules import dep_freshness as dep_freshness  # noqa: F401
from nfr_review.rules import dep_upgrade_path as dep_upgrade_path  # noqa: F401
from nfr_review.rules import (
    dockerfile_base_pinning as dockerfile_base_pinning,  # noqa: F401
)
from nfr_review.rules import dockerfile_multistage as dockerfile_multistage  # noqa: F401
from nfr_review.rules import (
    dockerfile_secret_leakage as dockerfile_secret_leakage,  # noqa: F401
)
from nfr_review.rules import (
    dockerfile_user_directive as dockerfile_user_directive,  # noqa: F401
)
from nfr_review.rules import (
    go_defer_in_loop as go_defer_in_loop,  # noqa: F401
)
from nfr_review.rules import (
    go_error_ignored as go_error_ignored,  # noqa: F401
)
from nfr_review.rules import (
    go_goroutine_leak as go_goroutine_leak,  # noqa: F401
)
from nfr_review.rules import (
    go_http_no_timeout as go_http_no_timeout,  # noqa: F401
)
from nfr_review.rules import (
    helm_chart_metadata as helm_chart_metadata,  # noqa: F401
)
from nfr_review.rules import (
    helm_secret_leakage as helm_secret_leakage,  # noqa: F401
)
from nfr_review.rules import (
    helm_values_validation as helm_values_validation,  # noqa: F401
)
from nfr_review.rules import (
    istio_circuit_breaker as istio_circuit_breaker,  # noqa: F401
)
from nfr_review.rules import (
    istio_mtls_strict as istio_mtls_strict,  # noqa: F401
)
from nfr_review.rules import (
    istio_traffic_policy as istio_traffic_policy,  # noqa: F401
)
from nfr_review.rules import java_exception as java_exception  # noqa: F401
from nfr_review.rules import java_health as java_health  # noqa: F401
from nfr_review.rules import java_resilience as java_resilience  # noqa: F401
from nfr_review.rules import java_thread_pool as java_thread_pool  # noqa: F401
from nfr_review.rules import k8s_network as k8s_network  # noqa: F401
from nfr_review.rules import k8s_probes as k8s_probes  # noqa: F401
from nfr_review.rules import k8s_resources as k8s_resources  # noqa: F401
from nfr_review.rules import k8s_security as k8s_security  # noqa: F401
from nfr_review.rules import (
    nodejs_callback_error_ignored as nodejs_callback_error_ignored,  # noqa: F401
)
from nfr_review.rules import (
    nodejs_floating_promise as nodejs_floating_promise,  # noqa: F401
)
from nfr_review.rules import (
    nodejs_promise_no_catch as nodejs_promise_no_catch,  # noqa: F401
)
from nfr_review.rules import (
    nodejs_sync_fs_api as nodejs_sync_fs_api,  # noqa: F401
)
from nfr_review.rules import otel_exporter as otel_exporter  # noqa: F401
from nfr_review.rules import otel_pipeline as otel_pipeline  # noqa: F401
from nfr_review.rules import otel_sampling as otel_sampling  # noqa: F401
from nfr_review.rules import (
    patch_arch_graceful as patch_arch_graceful,  # noqa: F401
)
from nfr_review.rules import (
    patch_arch_pdb as patch_arch_pdb,  # noqa: F401
)
from nfr_review.rules import (
    patch_arch_singleton as patch_arch_singleton,  # noqa: F401
)
from nfr_review.rules import (
    patch_arch_strategy as patch_arch_strategy,  # noqa: F401
)
from nfr_review.rules import (
    patch_deps as patch_deps,  # noqa: F401
)
from nfr_review.rules import (
    patch_forward_migration as patch_forward_migration,  # noqa: F401
)
from nfr_review.rules import (
    patch_health_probes as patch_health_probes,  # noqa: F401
)
from nfr_review.rules import (
    patch_health_startup as patch_health_startup,  # noqa: F401
)
from nfr_review.rules import (
    patch_health_termination as patch_health_termination,  # noqa: F401
)
from nfr_review.rules import (
    patch_health_trivial_probe as patch_health_trivial_probe,  # noqa: F401
)
from nfr_review.rules import (
    patch_rollback_ci as patch_rollback_ci,  # noqa: F401
)
from nfr_review.rules import (
    patch_rollback_docs as patch_rollback_docs,  # noqa: F401
)
from nfr_review.rules import (
    patch_traffic as patch_traffic,  # noqa: F401
)
from nfr_review.rules import pii_logging as pii_logging  # noqa: F401
from nfr_review.rules import (
    proto_field_numbering as proto_field_numbering,  # noqa: F401
)
from nfr_review.rules import (
    proto_method_comments as proto_method_comments,  # noqa: F401
)
from nfr_review.rules import (
    proto_service_versioning as proto_service_versioning,  # noqa: F401
)
from nfr_review.rules import (
    python_async_fire_forget as python_async_fire_forget,  # noqa: F401
)
from nfr_review.rules import (
    python_broad_except_silent as python_broad_except_silent,  # noqa: F401
)
from nfr_review.rules import (
    python_mutable_default as python_mutable_default,  # noqa: F401
)
from nfr_review.rules import (
    python_star_import as python_star_import,  # noqa: F401
)
from nfr_review.rules import sample as sample  # noqa: F401
from nfr_review.rules import (
    skaffold_build as skaffold_build,  # noqa: F401
)
from nfr_review.rules import spring_actuator as spring_actuator  # noqa: F401
from nfr_review.rules import spring_logging as spring_logging  # noqa: F401
from nfr_review.rules import spring_profile as spring_profile  # noqa: F401
from nfr_review.rules import (
    terraform_iam_policy as terraform_iam_policy,  # noqa: F401
)
from nfr_review.rules import (
    terraform_provider_pinning as terraform_provider_pinning,  # noqa: F401
)
from nfr_review.rules import (
    terraform_state_backend as terraform_state_backend,  # noqa: F401
)

__all__ = [
    "ast_bare_except",
    "ast_logging_stdout",
    "adr_drift",
    "adr_lifecycle",
    "apim_auth",
    "apim_backend_url",
    "apim_rate_limit",
    "ci_security_scan",
    "ci_test_stage",
    "csharp_async_void",
    "csharp_blocking_async",
    "csharp_configure_await",
    "csharp_disposable_no_using",
    "go_defer_in_loop",
    "go_error_ignored",
    "go_goroutine_leak",
    "go_http_no_timeout",
    "dep_freshness",
    "dep_upgrade_path",
    "dockerfile_base_pinning",
    "dockerfile_multistage",
    "dockerfile_secret_leakage",
    "dockerfile_user_directive",
    "helm_chart_metadata",
    "helm_secret_leakage",
    "helm_values_validation",
    "istio_circuit_breaker",
    "istio_mtls_strict",
    "istio_traffic_policy",
    "java_exception",
    "java_health",
    "java_resilience",
    "java_thread_pool",
    "nodejs_callback_error_ignored",
    "nodejs_floating_promise",
    "nodejs_promise_no_catch",
    "nodejs_sync_fs_api",
    "k8s_network",
    "k8s_probes",
    "k8s_resources",
    "k8s_security",
    "otel_exporter",
    "otel_pipeline",
    "otel_sampling",
    "patch_arch_graceful",
    "patch_arch_pdb",
    "patch_arch_singleton",
    "patch_arch_strategy",
    "patch_deps",
    "patch_forward_migration",
    "patch_health_probes",
    "patch_health_startup",
    "patch_health_termination",
    "patch_health_trivial_probe",
    "patch_rollback_ci",
    "patch_rollback_docs",
    "patch_traffic",
    "pii_logging",
    "proto_field_numbering",
    "proto_method_comments",
    "proto_service_versioning",
    "python_async_fire_forget",
    "python_broad_except_silent",
    "python_mutable_default",
    "python_star_import",
    "sample",
    "skaffold_build",
    "spring_actuator",
    "spring_logging",
    "spring_profile",
    "terraform_iam_policy",
    "terraform_provider_pinning",
    "terraform_state_backend",
]
