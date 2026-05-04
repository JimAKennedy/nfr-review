"""Built-in rules. Importing this package auto-registers them."""

from __future__ import annotations

from nfr_review.rules import adr_drift as adr_drift
from nfr_review.rules import adr_lifecycle as adr_lifecycle
from nfr_review.rules import apim_auth as apim_auth
from nfr_review.rules import apim_backend_url as apim_backend_url
from nfr_review.rules import apim_rate_limit as apim_rate_limit
from nfr_review.rules import ci_security_scan as ci_security_scan
from nfr_review.rules import ci_test_stage as ci_test_stage
from nfr_review.rules import java_exception as java_exception
from nfr_review.rules import java_health as java_health
from nfr_review.rules import java_resilience as java_resilience
from nfr_review.rules import java_thread_pool as java_thread_pool
from nfr_review.rules import k8s_network as k8s_network
from nfr_review.rules import k8s_probes as k8s_probes
from nfr_review.rules import k8s_resources as k8s_resources
from nfr_review.rules import k8s_security as k8s_security
from nfr_review.rules import pii_logging as pii_logging
from nfr_review.rules import sample as sample
from nfr_review.rules import spring_actuator as spring_actuator
from nfr_review.rules import spring_logging as spring_logging
from nfr_review.rules import spring_profile as spring_profile

__all__ = [
    "adr_drift",
    "adr_lifecycle",
    "apim_auth",
    "apim_backend_url",
    "apim_rate_limit",
    "ci_security_scan",
    "ci_test_stage",
    "java_exception",
    "java_health",
    "java_resilience",
    "java_thread_pool",
    "k8s_network",
    "k8s_probes",
    "k8s_resources",
    "k8s_security",
    "pii_logging",
    "sample",
    "spring_actuator",
    "spring_logging",
    "spring_profile",
]
