# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Compliance framework → rule-ID mapping.

Extracted from ``docs/continuous-compliance.md`` (Section 2). Every rule that
appears in the control-mapping tables maps to all four frameworks; unmapped
rules are excluded when the ``--framework`` filter is active.
"""

from __future__ import annotations

# All rule IDs that appear in the compliance mapping tables.
# These IDs match the registered rule IDs in the codebase, not the
# human-readable labels used in the doc (e.g. "otel-exporter" in the doc
# is "otel-exporter-config" in code).
_MAPPED_RULES: frozenset[str] = frozenset(
    [
        # 2.1 CI/CD
        "ci-test-stage-missing",
        "ci-security-scan-missing",
        # 2.2 Kubernetes
        "probes-missing",
        "resource-limits-missing",
        "network-policy-missing",
        "non-root-container-violation",
        # 2.3 Docker
        "dockerfile-base-pinning",
        "dockerfile-secret-leakage",
        "dockerfile-user-directive",
        "dockerfile-multistage",
        "dockerfile-k8s-user-conflict",
        "dockerfile-k8s-image-drift",
        # 2.4 Java/Spring
        "health-endpoint-missing",
        "resilience-annotation-missing",
        "exception-handling-antipattern",
        "thread-pool-misconfiguration",
        "actuator-exposure-risk",
        "logging-config-missing",
        "spring-profile-misconfiguration",
        # 2.5 Security
        "pii-in-log-statements",
        "apim-auth-policy-missing",
        "apim-rate-limit-missing",
        # 2.6 Architecture
        "adr-lifecycle-gap",
        "architectural-drift-from-adr",
        # 2.7 C++
        "cmake-build-config",
        "cpp-clang-format",
        "cpp-clang-tidy",
        "cpp-raw-memory",
        "cpp-sanitizer-ci",
        # 2.8 Patching
        "PATCH-SCOPE-001",
        "PATCH-SCOPE-002",
        "PATCH-ARCH-001",
        "PATCH-ARCH-002",
        "PATCH-ARCH-003",
        "PATCH-ARCH-004",
        "PATCH-HEALTH-001",
        "PATCH-HEALTH-002",
        "PATCH-HEALTH-003",
        "PATCH-HEALTH-004",
        "PATCH-TRAFFIC-001",
        "PATCH-TRAFFIC-002",
        "PATCH-TRAFFIC-003",
        "PATCH-DEPS-001",
        "PATCH-DEPS-002",
        "PATCH-DEPS-003",
        "PATCH-TELEM-001",
        "PATCH-TELEM-002",
        "PATCH-TELEM-003",
        "PATCH-ROLL-001",
        "PATCH-ROLL-002",
        "PATCH-ROLL-003",
        # 2.9 Dependencies
        "dep-freshness",
        "dep-upgrade-path",
        # 2.10 Observability
        "otel-exporter-config",
        "otel-pipeline-completeness",
        "otel-sampling",
        "correlation-id-missing",
        # 2.11 Hygiene
        "HYG-DOC-001",
        "HYG-DOC-002",
        "HYG-DOC-003",
        "HYG-CI-001",
        "HYG-CI-002",
        "HYG-CI-003",
        "HYG-CI-004",
        "HYG-CI-005",
        "HYG-CI-006",
        "HYG-CI-007",
        "HYG-COM-001",
        "HYG-COM-002",
        "HYG-COM-003",
        "HYG-COM-004",
        "HYG-COM-005",
        "HYG-COM-006",
        "HYG-BLD-001",
        "HYG-BLD-002",
        "HYG-BLD-003",
        "HYG-BLD-004",
        "HYG-BLD-005",
        "HYG-PRV-001",
        "HYG-PRV-002",
        "HYG-PRV-003",
        "HYG-LIC-001",
        "HYG-LIC-002",
        "HYG-LIC-003",
        "HYG-LIC-004",
    ]
)

FRAMEWORK_SLUGS: tuple[str, ...] = ("soc2", "iso27001", "pci-dss", "nist-800-53")

FRAMEWORK_LABELS: dict[str, str] = {
    "soc2": "SOC 2 Type II",
    "iso27001": "ISO 27001:2022",
    "pci-dss": "PCI DSS v4.0",
    "nist-800-53": "NIST 800-53 Rev 5",
}

FRAMEWORK_RULES: dict[str, frozenset[str]] = {slug: _MAPPED_RULES for slug in FRAMEWORK_SLUGS}


def rules_for_framework(framework: str) -> frozenset[str]:
    """Return the set of rule IDs mapped to *framework*.

    Raises ``KeyError`` if *framework* is not a valid slug.
    """
    return FRAMEWORK_RULES[framework]


def frameworks_for_rule(rule_id: str) -> list[str]:
    """Return the framework slugs that *rule_id* maps to (may be empty)."""
    return [slug for slug, rules in FRAMEWORK_RULES.items() if rule_id in rules]
