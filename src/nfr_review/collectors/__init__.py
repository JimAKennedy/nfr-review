# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Built-in collectors. Importing this package auto-registers them."""

from __future__ import annotations

from nfr_review.collectors import adr as adr  # noqa: F401
from nfr_review.collectors import adr_derive as adr_derive  # noqa: F401
from nfr_review.collectors import apim_policy as apim_policy  # noqa: F401
from nfr_review.collectors import ci_artifact as ci_artifact  # noqa: F401
from nfr_review.collectors import cmake as cmake  # noqa: F401
from nfr_review.collectors import cpp_ast as cpp_ast  # noqa: F401
from nfr_review.collectors import csharp_ast as csharp_ast  # noqa: F401
from nfr_review.collectors import csharp_deps as csharp_deps  # noqa: F401
from nfr_review.collectors import dockerfile as dockerfile  # noqa: F401
from nfr_review.collectors import go_ast as go_ast  # noqa: F401
from nfr_review.collectors import go_deps as go_deps  # noqa: F401
from nfr_review.collectors import helm as helm  # noqa: F401
from nfr_review.collectors import istio as istio  # noqa: F401
from nfr_review.collectors import java_ast as java_ast  # noqa: F401
from nfr_review.collectors import java_deps as java_deps  # noqa: F401
from nfr_review.collectors import jdepend as jdepend  # noqa: F401
from nfr_review.collectors import k8s_manifest as k8s_manifest  # noqa: F401
from nfr_review.collectors import nodejs_ast as nodejs_ast  # noqa: F401
from nfr_review.collectors import nodejs_deps as nodejs_deps  # noqa: F401
from nfr_review.collectors import otel as otel  # noqa: F401
from nfr_review.collectors import proto as proto  # noqa: F401
from nfr_review.collectors import python_ast as python_ast  # noqa: F401
from nfr_review.collectors import python_deps as python_deps  # noqa: F401
from nfr_review.collectors import repo_structure as repo_structure  # noqa: F401
from nfr_review.collectors import service_mesh as service_mesh  # noqa: F401
from nfr_review.collectors import skaffold as skaffold  # noqa: F401
from nfr_review.collectors import spring_config as spring_config  # noqa: F401
from nfr_review.collectors import telemetry_config as telemetry_config  # noqa: F401
from nfr_review.collectors import terraform as terraform  # noqa: F401

__all__ = [
    "adr",
    "adr_derive",
    "apim_policy",
    "ci_artifact",
    "cmake",
    "cpp_ast",
    "csharp_ast",
    "csharp_deps",
    "dockerfile",
    "go_ast",
    "go_deps",
    "helm",
    "istio",
    "java_ast",
    "java_deps",
    "jdepend",
    "k8s_manifest",
    "nodejs_ast",
    "nodejs_deps",
    "otel",
    "proto",
    "python_ast",
    "python_deps",
    "repo_structure",
    "service_mesh",
    "skaffold",
    "spring_config",
    "telemetry_config",
    "terraform",
]
