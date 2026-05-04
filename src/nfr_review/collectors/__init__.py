"""Built-in collectors. Importing this package auto-registers them."""

from __future__ import annotations

from nfr_review.collectors import adr as adr
from nfr_review.collectors import apim_policy as apim_policy
from nfr_review.collectors import ci_artifact as ci_artifact
from nfr_review.collectors import java_ast as java_ast
from nfr_review.collectors import k8s_manifest as k8s_manifest
from nfr_review.collectors import repo_structure as repo_structure
from nfr_review.collectors import spring_config as spring_config

__all__ = [
    "adr",
    "apim_policy",
    "ci_artifact",
    "java_ast",
    "k8s_manifest",
    "repo_structure",
    "spring_config",
]
