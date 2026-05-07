"""Built-in rules. Importing this package auto-registers them."""

from __future__ import annotations

from nfr_review.rules import adr_drift as adr_drift  # noqa: F401
from nfr_review.rules import adr_lifecycle as adr_lifecycle  # noqa: F401
from nfr_review.rules import apim_auth as apim_auth  # noqa: F401
from nfr_review.rules import apim_backend_url as apim_backend_url  # noqa: F401
from nfr_review.rules import apim_rate_limit as apim_rate_limit  # noqa: F401
from nfr_review.rules import ci_security_scan as ci_security_scan  # noqa: F401
from nfr_review.rules import ci_test_stage as ci_test_stage  # noqa: F401
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
from nfr_review.rules import otel_exporter as otel_exporter  # noqa: F401
from nfr_review.rules import otel_pipeline as otel_pipeline  # noqa: F401
from nfr_review.rules import otel_sampling as otel_sampling  # noqa: F401
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
    "adr_drift",
    "adr_lifecycle",
    "apim_auth",
    "apim_backend_url",
    "apim_rate_limit",
    "ci_security_scan",
    "ci_test_stage",
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
    "k8s_network",
    "k8s_probes",
    "k8s_resources",
    "k8s_security",
    "otel_exporter",
    "otel_pipeline",
    "otel_sampling",
    "pii_logging",
    "proto_field_numbering",
    "proto_method_comments",
    "proto_service_versioning",
    "sample",
    "skaffold_build",
    "spring_actuator",
    "spring_logging",
    "spring_profile",
    "terraform_iam_policy",
    "terraform_provider_pinning",
    "terraform_state_backend",
]
