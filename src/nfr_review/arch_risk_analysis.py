# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Bottleneck and resilience risk analysis for architecture documentation.

Analyzes discovered components, integrations, and test coverage to identify
performance bottlenecks, resilience threats, and other architectural risks.
Operates without LLM -- pure structural/heuristic analysis.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Literal

from nfr_review.arch_models import (
    Component,
    ComponentTestCoverage,
    IntegrationPoint,
    RiskFinding,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity ordering (for sorting)
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

_CATEGORY_ORDER: dict[str, int] = {
    "performance_bottleneck": 0,
    "resilience_threat": 1,
    "change_hotspot": 2,
    "scalability_limit": 3,
    "security_surface": 4,
    "operational_risk": 5,
}


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def _build_adjacency(
    integrations: list[IntegrationPoint],
) -> dict[str, list[tuple[str, IntegrationPoint]]]:
    """Build a directed adjacency list from integrations.

    Returns a dict mapping source_component_id to a list of
    (target_component_id, IntegrationPoint) pairs.
    """
    adj: dict[str, list[tuple[str, IntegrationPoint]]] = defaultdict(list)
    for intg in integrations:
        adj[intg.source_component_id].append((intg.target_component_id, intg))
    return dict(adj)


def _compute_fan_in_out(
    components: list[Component],
    integrations: list[IntegrationPoint],
) -> dict[str, tuple[int, int]]:
    """Compute fan-in and fan-out for each component.

    Returns a dict mapping component_id to (fan_in, fan_out).
    Fan-in = number of integrations where this component is the target.
    Fan-out = number of integrations where this component is the source.
    """
    fan_in: dict[str, int] = defaultdict(int)
    fan_out: dict[str, int] = defaultdict(int)

    for intg in integrations:
        fan_in[intg.target_component_id] += 1
        fan_out[intg.source_component_id] += 1

    result: dict[str, tuple[int, int]] = {}
    for comp in components:
        result[comp.id] = (fan_in.get(comp.id, 0), fan_out.get(comp.id, 0))
    return result


def _find_sync_chains(
    integrations: list[IntegrationPoint],
) -> list[list[str]]:
    """Find longest synchronous call chains via DFS.

    Only follows integrations with style='synchronous', 'api_call', or 'rpc'.
    Returns a list of chains (each chain is a list of component IDs).
    Chains are returned longest-first.
    """
    sync_styles = {"synchronous", "api_call", "rpc"}

    # Build adjacency for sync integrations only
    adj: dict[str, list[str]] = defaultdict(list)
    for intg in integrations:
        if intg.style in sync_styles:
            adj[intg.source_component_id].append(intg.target_component_id)

    if not adj:
        return []

    # Collect all nodes involved in sync integrations
    all_nodes: set[str] = set()
    for src, targets in adj.items():
        all_nodes.add(src)
        all_nodes.update(targets)

    # DFS to find all maximal paths
    chains: list[list[str]] = []

    def _dfs(node: str, path: list[str], visited: set[str]) -> None:
        extended = False
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                extended = True
                visited.add(neighbor)
                path.append(neighbor)
                _dfs(neighbor, path, visited)
                path.pop()
                visited.discard(neighbor)
        if not extended and len(path) >= 3:
            chains.append(list(path))

    for start in all_nodes:
        _dfs(start, [start], {start})

    # Sort longest first
    chains.sort(key=lambda c: len(c), reverse=True)
    return chains


def _coverage_for_component(
    component_id: str,
    coverage: list[ComponentTestCoverage] | None,
) -> ComponentTestCoverage | None:
    """Look up coverage data for a component."""
    if coverage is None:
        return None
    for cov in coverage:
        if cov.component_id == component_id:
            return cov
    return None


def _component_by_id(
    component_id: str,
    components: list[Component],
) -> Component | None:
    """Look up a component by ID."""
    for comp in components:
        if comp.id == component_id:
            return comp
    return None


# ---------------------------------------------------------------------------
# Risk detectors
# ---------------------------------------------------------------------------


def _detect_single_point_of_failure(
    components: list[Component],
    integrations: list[IntegrationPoint],
    fan_data: dict[str, tuple[int, int]],
    *,
    spof_threshold: int = 3,
) -> list[RiskFinding]:
    """Detect components with high fan-in that may be single points of failure."""
    findings: list[RiskFinding] = []

    for comp in components:
        fan_in, _fan_out = fan_data.get(comp.id, (0, 0))
        if fan_in < spof_threshold:
            continue

        severity: Literal["critical", "high", "medium", "low"] = (
            "high" if fan_in >= 5 else "medium"
        )

        # Collect integration IDs pointing at this component
        affected_intg_ids = [
            intg.id for intg in integrations if intg.target_component_id == comp.id
        ]

        findings.append(
            RiskFinding(
                id="",  # assigned later
                category="resilience_threat",
                severity=severity,
                title=f"Single point of failure: {comp.name}",
                description=(
                    f"Component '{comp.name}' has a fan-in of {fan_in}, meaning "
                    f"{fan_in} other components depend on it. A failure in this "
                    f"component could cascade across the system."
                ),
                affected_component_ids=[comp.id],
                affected_integration_ids=affected_intg_ids,
                evidence=f"Fan-in count: {fan_in} (threshold: {spof_threshold})",
                recommendation=(
                    "Consider adding redundancy, health checks, circuit breakers, "
                    "or fallback mechanisms for this critical component."
                ),
            )
        )

    return findings


def _detect_sync_chain_risk(
    components: list[Component],
    integrations: list[IntegrationPoint],
    *,
    sync_chain_threshold: int = 3,
) -> list[RiskFinding]:
    """Detect chains of synchronous integrations that create latency risk."""
    chains = _find_sync_chains(integrations)
    if not chains:
        return []

    findings: list[RiskFinding] = []
    seen_chain_keys: set[str] = set()

    for chain in chains:
        if len(chain) < sync_chain_threshold:
            continue

        # Deduplicate chains that are subsets of longer chains
        chain_key = "->".join(chain)
        if chain_key in seen_chain_keys:
            continue
        seen_chain_keys.add(chain_key)

        severity: Literal["critical", "high", "medium", "low"] = (
            "high" if len(chain) >= 4 else "medium"
        )

        # Resolve component names for description
        names = []
        for cid in chain:
            comp = _component_by_id(cid, components)
            names.append(comp.name if comp else cid)

        # Find integration IDs involved in this chain
        sync_styles = {"synchronous", "api_call", "rpc"}
        affected_intg_ids: list[str] = []
        for i in range(len(chain) - 1):
            for intg in integrations:
                if (
                    intg.source_component_id == chain[i]
                    and intg.target_component_id == chain[i + 1]
                    and intg.style in sync_styles
                ):
                    affected_intg_ids.append(intg.id)
                    break

        chain_str = " -> ".join(names)
        findings.append(
            RiskFinding(
                id="",
                category="performance_bottleneck",
                severity=severity,
                title=f"Synchronous call chain ({len(chain)} hops)",
                description=(
                    f"A chain of {len(chain)} synchronous integrations creates "
                    f"cumulative latency risk: {chain_str}. Each hop adds latency "
                    f"and a failure point."
                ),
                affected_component_ids=list(chain),
                affected_integration_ids=affected_intg_ids,
                evidence=f"Chain length: {len(chain)} (threshold: {sync_chain_threshold})",
                recommendation=(
                    "Consider breaking the chain with asynchronous messaging, "
                    "caching, or combining fine-grained calls into coarser operations."
                ),
            )
        )

    return findings


def _detect_missing_resilience_testing(
    components: list[Component],
    integrations: list[IntegrationPoint],
    coverage: list[ComponentTestCoverage] | None,
    fan_data: dict[str, tuple[int, int]],
) -> list[RiskFinding]:
    """Detect components lacking resilience testing despite being integration-heavy."""
    if coverage is None:
        return []

    findings: list[RiskFinding] = []

    for comp in components:
        fan_in, fan_out = fan_data.get(comp.id, (0, 0))
        if fan_in + fan_out < 2:
            continue

        cov = _coverage_for_component(comp.id, coverage)
        if cov is None:
            continue

        # Check for missing resilience coverage
        has_resilience_gap = False
        if cov.nonfunctional_coverage in ("none", "minimal"):
            has_resilience_gap = True
        elif any("resilience" in gap.lower() for gap in cov.gaps):
            has_resilience_gap = True

        if not has_resilience_gap:
            continue

        # Determine severity based on integration density
        severity: Literal["critical", "high", "medium", "low"] = (
            "high" if fan_in + fan_out >= 4 else "medium"
        )

        findings.append(
            RiskFinding(
                id="",
                category="resilience_threat",
                severity=severity,
                title=f"Missing resilience testing: {comp.name}",
                description=(
                    f"Component '{comp.name}' has {fan_in} incoming and {fan_out} "
                    f"outgoing integrations but lacks resilience/non-functional "
                    f"test coverage (nonfunctional_coverage={cov.nonfunctional_coverage})."
                ),
                affected_component_ids=[comp.id],
                evidence=(
                    f"Fan-in: {fan_in}, fan-out: {fan_out}, "
                    f"nonfunctional_coverage: {cov.nonfunctional_coverage}, "
                    f"gaps: {cov.gaps}"
                ),
                recommendation=(
                    "Add resilience tests such as chaos testing, circuit-breaker "
                    "verification, timeout handling, and retry logic validation."
                ),
            )
        )

    return findings


def _detect_database_bottleneck(
    components: list[Component],
    integrations: list[IntegrationPoint],
    fan_data: dict[str, tuple[int, int]],
) -> list[RiskFinding]:
    """Detect database components accessed by many services."""
    findings: list[RiskFinding] = []

    for comp in components:
        if comp.component_type != "database":
            continue

        fan_in, _fan_out = fan_data.get(comp.id, (0, 0))
        if fan_in < 3:
            continue

        # Check for shared_database style integrations
        shared_db_count = sum(
            1
            for intg in integrations
            if intg.target_component_id == comp.id and intg.style == "shared_database"
        )

        severity: Literal["critical", "high", "medium", "low"] = (
            "high" if fan_in >= 5 else "medium"
        )

        affected_intg_ids = [
            intg.id for intg in integrations if intg.target_component_id == comp.id
        ]

        desc_extra = ""
        if shared_db_count > 0:
            desc_extra = (
                f" {shared_db_count} of these use shared_database style, "
                f"indicating tight coupling."
            )

        findings.append(
            RiskFinding(
                id="",
                category="performance_bottleneck",
                severity=severity,
                title=f"Database bottleneck: {comp.name}",
                description=(
                    f"Database '{comp.name}' is accessed by {fan_in} services, "
                    f"creating a potential performance bottleneck and single point "
                    f"of contention.{desc_extra}"
                ),
                affected_component_ids=[comp.id],
                affected_integration_ids=affected_intg_ids,
                evidence=(
                    f"Fan-in: {fan_in}, shared_database integrations: {shared_db_count}"
                ),
                recommendation=(
                    "Consider read replicas, connection pooling, caching layers, "
                    "or decomposing into per-service databases (database-per-service pattern)."
                ),
            )
        )

    return findings


def _detect_cross_repo_risk(
    components: list[Component],
    integrations: list[IntegrationPoint],
) -> list[RiskFinding]:
    """Flag cross-repo integration points as operational risks."""
    findings: list[RiskFinding] = []

    for intg in integrations:
        if not intg.is_cross_repo:
            continue

        src = _component_by_id(intg.source_component_id, components)
        tgt = _component_by_id(intg.target_component_id, components)
        src_name = src.name if src else intg.source_component_id
        tgt_name = tgt.name if tgt else intg.target_component_id

        affected_comp_ids = []
        if src:
            affected_comp_ids.append(src.id)
        if tgt:
            affected_comp_ids.append(tgt.id)

        findings.append(
            RiskFinding(
                id="",
                category="operational_risk",
                severity="medium",
                title=f"Cross-repo integration: {src_name} -> {tgt_name}",
                description=(
                    f"Integration between '{src_name}' and '{tgt_name}' crosses "
                    f"repository boundaries, making it harder to test and deploy "
                    f"atomically."
                ),
                affected_component_ids=affected_comp_ids,
                affected_integration_ids=[intg.id],
                evidence=f"Integration {intg.id} has is_cross_repo=True",
                recommendation=(
                    "Ensure contract tests exist for this cross-repo integration. "
                    "Consider API versioning and backward-compatible changes."
                ),
            )
        )

    return findings


def _detect_gateway_scalability(
    components: list[Component],
    integrations: list[IntegrationPoint],
    fan_data: dict[str, tuple[int, int]],
) -> list[RiskFinding]:
    """Detect gateway components that may be scalability limits."""
    findings: list[RiskFinding] = []

    for comp in components:
        if comp.component_type != "gateway":
            continue

        _fan_in, fan_out = fan_data.get(comp.id, (0, 0))
        if fan_out < 2:
            continue

        affected_intg_ids = [
            intg.id for intg in integrations if intg.source_component_id == comp.id
        ]

        findings.append(
            RiskFinding(
                id="",
                category="scalability_limit",
                severity="medium",
                title=f"Gateway single entry point: {comp.name}",
                description=(
                    f"Gateway '{comp.name}' routes traffic to {fan_out} downstream "
                    f"components. As a single entry point, it may become a "
                    f"scalability bottleneck under high load."
                ),
                affected_component_ids=[comp.id],
                affected_integration_ids=affected_intg_ids,
                evidence=f"Fan-out: {fan_out}",
                recommendation=(
                    "Consider horizontal scaling, load balancing, rate limiting, "
                    "and health-check-based routing for the gateway."
                ),
            )
        )

    return findings


def _detect_missing_test_coverage_hotspot(
    components: list[Component],
    integrations: list[IntegrationPoint],
    coverage: list[ComponentTestCoverage] | None,
    fan_data: dict[str, tuple[int, int]],
) -> list[RiskFinding]:
    """Detect components with many integrations but poor test coverage."""
    if coverage is None:
        return []

    findings: list[RiskFinding] = []

    for comp in components:
        fan_in, fan_out = fan_data.get(comp.id, (0, 0))
        if fan_in + fan_out < 4:
            continue

        cov = _coverage_for_component(comp.id, coverage)
        if cov is None:
            continue

        if cov.functional_coverage not in ("none", "minimal"):
            continue

        findings.append(
            RiskFinding(
                id="",
                category="change_hotspot",
                severity="high",
                title=f"Undertested change hotspot: {comp.name}",
                description=(
                    f"Component '{comp.name}' has {fan_in + fan_out} integration "
                    f"points (fan-in={fan_in}, fan-out={fan_out}) but only "
                    f"'{cov.functional_coverage}' functional test coverage. "
                    f"Changes here are high-risk."
                ),
                affected_component_ids=[comp.id],
                evidence=(
                    f"Integration points: {fan_in + fan_out}, "
                    f"functional_coverage: {cov.functional_coverage}"
                ),
                recommendation=(
                    "Prioritize adding unit and integration tests for this component "
                    "before making further changes."
                ),
            )
        )

    return findings


def _detect_security_surface(
    components: list[Component],
    integrations: list[IntegrationPoint],
    coverage: list[ComponentTestCoverage] | None,
) -> list[RiskFinding]:
    """Detect security-sensitive components lacking security test coverage."""
    findings: list[RiskFinding] = []

    # Security-sensitive component types
    security_types = {"gateway", "ui", "external"}

    for comp in components:
        is_security_boundary = comp.component_type in security_types

        # Also check if component has external-facing integrations
        has_external_integration = False
        for intg in integrations:
            if intg.source_component_id == comp.id or intg.target_component_id == comp.id:
                # Check if the other side is an external component
                other_id = (
                    intg.target_component_id
                    if intg.source_component_id == comp.id
                    else intg.source_component_id
                )
                other = _component_by_id(other_id, components)
                if other and other.component_type == "external":
                    has_external_integration = True
                    break

        if not is_security_boundary and not has_external_integration:
            continue

        # Check security test coverage
        has_security_tests = False
        if coverage is not None:
            cov = _coverage_for_component(comp.id, coverage)
            if cov is not None and "security" in cov.test_types_present:
                has_security_tests = True

        if has_security_tests:
            continue

        severity: Literal["critical", "high", "medium", "low"]
        if comp.component_type == "gateway":
            severity = "medium"
        elif comp.component_type == "external":
            severity = "medium"
        elif has_external_integration:
            severity = "medium"
        else:
            severity = "low"

        reason = (
            f"type={comp.component_type}"
            if is_security_boundary
            else "has external-facing integration"
        )

        findings.append(
            RiskFinding(
                id="",
                category="security_surface",
                severity=severity,
                title=f"Security surface without security tests: {comp.name}",
                description=(
                    f"Component '{comp.name}' is a security boundary ({reason}) "
                    f"but lacks security test coverage."
                ),
                affected_component_ids=[comp.id],
                evidence=f"Component {reason}, no 'security' in test_types_present",
                recommendation=(
                    "Add security tests covering authentication, authorization, "
                    "input validation, and common vulnerability patterns (OWASP Top 10)."
                ),
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------


def analyze_risks(
    components: list[Component],
    integrations: list[IntegrationPoint],
    coverage: list[ComponentTestCoverage] | None = None,
    *,
    spof_threshold: int = 3,
    sync_chain_threshold: int = 3,
) -> list[RiskFinding]:
    """Run all risk analyzers and return deduplicated, sorted findings.

    Parameters
    ----------
    components:
        Discovered architectural components.
    integrations:
        Discovered integration points between components.
    coverage:
        Optional test coverage data for components.
    spof_threshold:
        Minimum fan-in to trigger single-point-of-failure detection.
    sync_chain_threshold:
        Minimum chain length to trigger synchronous chain risk detection.

    Returns
    -------
    list[RiskFinding]
        Risk findings sorted by severity (critical > high > medium > low),
        then by category, with sequential IDs (RISK-001, RISK-002, ...).
    """
    logger.info(
        "Analyzing risks: %d components, %d integrations, coverage=%s",
        len(components),
        len(integrations),
        "provided" if coverage is not None else "not provided",
    )

    if not components:
        logger.info("No components to analyze")
        return []

    # Compute shared data
    fan_data = _compute_fan_in_out(components, integrations)

    # Run all detectors
    all_findings: list[RiskFinding] = []

    all_findings.extend(
        _detect_single_point_of_failure(
            components, integrations, fan_data, spof_threshold=spof_threshold
        )
    )
    all_findings.extend(
        _detect_sync_chain_risk(
            components, integrations, sync_chain_threshold=sync_chain_threshold
        )
    )
    all_findings.extend(
        _detect_missing_resilience_testing(components, integrations, coverage, fan_data)
    )
    all_findings.extend(_detect_database_bottleneck(components, integrations, fan_data))
    all_findings.extend(_detect_cross_repo_risk(components, integrations))
    all_findings.extend(_detect_gateway_scalability(components, integrations, fan_data))
    all_findings.extend(
        _detect_missing_test_coverage_hotspot(components, integrations, coverage, fan_data)
    )
    all_findings.extend(_detect_security_surface(components, integrations, coverage))

    # Sort by severity, then category
    all_findings.sort(
        key=lambda f: (
            _SEVERITY_ORDER.get(f.severity, 99),
            _CATEGORY_ORDER.get(f.category, 99),
        )
    )

    # Assign sequential IDs
    for i, finding in enumerate(all_findings, start=1):
        finding = finding.model_copy(update={"id": f"RISK-{i:03d}"})
        all_findings[i - 1] = finding

    logger.info("Risk analysis complete: %d findings", len(all_findings))
    return all_findings


__all__ = [
    "analyze_risks",
]
