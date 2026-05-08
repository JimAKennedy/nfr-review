"""Built-in collectors. Importing this package auto-registers them."""

from __future__ import annotations

from nfr_review.collectors import adr as adr  # noqa: F401
from nfr_review.collectors import apim_policy as apim_policy  # noqa: F401
from nfr_review.collectors import ci_artifact as ci_artifact  # noqa: F401
from nfr_review.collectors import csharp_ast as csharp_ast  # noqa: F401
from nfr_review.collectors import dockerfile as dockerfile  # noqa: F401
from nfr_review.collectors import go_ast as go_ast  # noqa: F401
from nfr_review.collectors import helm as helm  # noqa: F401
from nfr_review.collectors import istio as istio  # noqa: F401
from nfr_review.collectors import java_ast as java_ast  # noqa: F401
from nfr_review.collectors import k8s_manifest as k8s_manifest  # noqa: F401
from nfr_review.collectors import nodejs_ast as nodejs_ast  # noqa: F401
from nfr_review.collectors import otel as otel  # noqa: F401
from nfr_review.collectors import proto as proto  # noqa: F401
from nfr_review.collectors import python_ast as python_ast  # noqa: F401
from nfr_review.collectors import repo_structure as repo_structure  # noqa: F401
from nfr_review.collectors import skaffold as skaffold  # noqa: F401
from nfr_review.collectors import spring_config as spring_config  # noqa: F401
from nfr_review.collectors import terraform as terraform  # noqa: F401

__all__ = [
    "adr",
    "apim_policy",
    "ci_artifact",
    "csharp_ast",
    "dockerfile",
    "go_ast",
    "helm",
    "istio",
    "java_ast",
    "k8s_manifest",
    "nodejs_ast",
    "otel",
    "proto",
    "python_ast",
    "repo_structure",
    "skaffold",
    "spring_config",
    "terraform",
]
