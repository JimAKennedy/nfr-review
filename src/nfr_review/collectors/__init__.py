"""Built-in collectors. Importing this package auto-registers them."""

from __future__ import annotations

from nfr_review.collectors import adr as adr  # noqa: F401
from nfr_review.collectors import apim_policy as apim_policy  # noqa: F401
from nfr_review.collectors import ci_artifact as ci_artifact  # noqa: F401
from nfr_review.collectors import java_ast as java_ast  # noqa: F401
from nfr_review.collectors import k8s_manifest as k8s_manifest  # noqa: F401
from nfr_review.collectors import repo_structure as repo_structure  # noqa: F401
from nfr_review.collectors import spring_config as spring_config  # noqa: F401

__all__ = [
    "adr",
    "apim_policy",
    "ci_artifact",
    "java_ast",
    "k8s_manifest",
    "repo_structure",
    "spring_config",
]
