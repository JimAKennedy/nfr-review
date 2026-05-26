# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Deep-review flagging and recommendation generation for architecture reports.

Identifies areas that need deeper human or LLM-assisted review by analyzing
coverage gaps, risks, integration complexity, domain model structure, and
maturity assessments. Operates without LLM -- pure heuristic analysis.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Literal

from nfr_review.arch_models import (
    Component,
    ComponentTestCoverage,
    DomainModelSection,
    IntegrationPoint,
    MarketAnalysisSection,
    Recommendation,
    RiskFinding,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority ordering (for sorting and deduplication)
# ---------------------------------------------------------------------------

_PRIORITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

# Expected test types by component type
_EXPECTED_TEST_TYPES: dict[str, list[str]] = {
    "service": ["unit", "integration"],
    "library": ["unit"],
    "ui": ["unit", "accessibility"],
    "gateway": ["unit", "integration", "security"],
    "worker": ["unit", "integration"],
    "queue": ["integration"],
    "database": ["integration"],
    "external": ["contract"],
}

# Synchronous integration styles (for chain detection)
_SYNC_STYLES = frozenset({"synchronous", "api_call", "rpc"})


# ---------------------------------------------------------------------------
# 1. Coverage-gap recommendations
# ---------------------------------------------------------------------------


def recommend_from_coverage_gaps(
    test_coverage: list[ComponentTestCoverage],
    components: list[Component],
) -> list[Recommendation]:
    """Flag components with poor test coverage.

    - Components with "none" functional coverage -> critical priority
    - Components with "none" or "minimal" NFR coverage -> high priority
    - Missing expected test types for the component type -> medium priority
    """
    recommendations: list[Recommendation] = []
    comp_map = {c.id: c for c in components}

    for cov in test_coverage:
        comp = comp_map.get(cov.component_id)
        comp_name = comp.name if comp else cov.component_id

        # No functional coverage is critical
        if cov.functional_coverage == "none":
            recommendations.append(
                Recommendation(
                    id="",
                    category="additional_testing",
                    priority="critical",
                    title=f"No functional test coverage: {comp_name}",
                    description=(
                        f"Component '{comp_name}' has no functional test coverage. "
                        f"This is a critical gap that must be addressed before "
                        f"any production deployment."
                    ),
                    rationale=(
                        f"Functional coverage is '{cov.functional_coverage}'. "
                        f"Without functional tests, regressions cannot be detected."
                    ),
                    affected_component_ids=[cov.component_id],
                )
            )

        # Poor NFR coverage
        if cov.nonfunctional_coverage in ("none", "minimal"):
            recommendations.append(
                Recommendation(
                    id="",
                    category="additional_testing",
                    priority="high",
                    title=f"Insufficient non-functional test coverage: {comp_name}",
                    description=(
                        f"Component '{comp_name}' has "
                        f"'{cov.nonfunctional_coverage}' non-functional test "
                        f"coverage. Performance, security, and resilience aspects "
                        f"are not adequately tested."
                    ),
                    rationale=(
                        f"Non-functional coverage is "
                        f"'{cov.nonfunctional_coverage}'. NFR gaps can lead to "
                        f"production incidents that functional tests won't catch."
                    ),
                    affected_component_ids=[cov.component_id],
                )
            )

        # Missing expected test types for this component type
        if comp is not None:
            expected = _EXPECTED_TEST_TYPES.get(comp.component_type, [])
            present = set(cov.test_types_present)
            missing = [t for t in expected if t not in present]

            if missing:
                recommendations.append(
                    Recommendation(
                        id="",
                        category="additional_testing",
                        priority="medium",
                        title=(
                            f"Missing expected test types for "
                            f"{comp.component_type}: {comp_name}"
                        ),
                        description=(
                            f"Component '{comp_name}' (type={comp.component_type}) "
                            f"is missing expected test types: {', '.join(missing)}."
                        ),
                        rationale=(
                            f"Components of type '{comp.component_type}' typically "
                            f"require {', '.join(expected)} tests. Missing: "
                            f"{', '.join(missing)}."
                        ),
                        affected_component_ids=[cov.component_id],
                    )
                )

    return recommendations


# ---------------------------------------------------------------------------
# 2. Risk-based recommendations
# ---------------------------------------------------------------------------


def recommend_from_risks(
    risks: list[RiskFinding],
    components: list[Component],
) -> list[Recommendation]:
    """Generate recommendations from risk findings.

    - Critical/high severity risks -> human_review at matching priority
    - Clusters of risks on the same component -> architecture_improvement
    - Security-surface risks -> always human_review at high priority
    """
    recommendations: list[Recommendation] = []
    comp_map = {c.id: c for c in components}

    # Track risk counts per component for cluster detection
    component_risk_counts: dict[str, int] = defaultdict(int)

    for risk in risks:
        for comp_id in risk.affected_component_ids:
            component_risk_counts[comp_id] += 1

        # Security-surface risks always get human_review at high
        if risk.category == "security_surface":
            recommendations.append(
                Recommendation(
                    id="",
                    category="human_review",
                    priority="high",
                    title=f"Security review needed: {risk.title}",
                    description=(
                        f"A security-surface risk has been identified: {risk.description}"
                    ),
                    rationale=(
                        f"Security risks require expert human review regardless "
                        f"of automated severity assessment. "
                        f"Risk severity: {risk.severity}."
                    ),
                    affected_component_ids=list(risk.affected_component_ids),
                )
            )
        elif risk.severity in ("critical", "high"):
            # Critical/high risks -> human_review at matching priority
            recommendations.append(
                Recommendation(
                    id="",
                    category="human_review",
                    priority=risk.severity,
                    title=f"Review required: {risk.title}",
                    description=(
                        f"A {risk.severity}-severity risk requires human review: "
                        f"{risk.description}"
                    ),
                    rationale=(
                        f"Risk category: {risk.category}, "
                        f"severity: {risk.severity}. "
                        f"{risk.recommendation}"
                    ),
                    affected_component_ids=list(risk.affected_component_ids),
                )
            )

    # Cluster detection: components with 3+ risks
    for comp_id, count in component_risk_counts.items():
        if count < 3:
            continue

        comp = comp_map.get(comp_id)
        comp_name = comp.name if comp else comp_id

        recommendations.append(
            Recommendation(
                id="",
                category="architecture_improvement",
                priority="high",
                title=f"Risk cluster on component: {comp_name}",
                description=(
                    f"Component '{comp_name}' has {count} associated risk "
                    f"findings, indicating a systemic architectural concern "
                    f"that may require redesign."
                ),
                rationale=(
                    f"{count} risks concentrated on a single component "
                    f"suggest the component has taken on too many "
                    f"responsibilities or lacks proper isolation."
                ),
                affected_component_ids=[comp_id],
            )
        )

    return recommendations


# ---------------------------------------------------------------------------
# 3. Integration complexity recommendations
# ---------------------------------------------------------------------------


def recommend_from_integrations(
    integrations: list[IntegrationPoint],
    components: list[Component],
) -> list[Recommendation]:
    """Flag integration complexity issues.

    - Cross-repo integrations -> documentation_gap (integration contracts)
    - Components with >5 integrations -> architecture_improvement (facade)
    - Synchronous chains of depth >=3 -> human_review (latency/resilience)
    """
    recommendations: list[Recommendation] = []
    comp_map = {c.id: c for c in components}

    # Cross-repo integrations
    for intg in integrations:
        if not intg.is_cross_repo:
            continue

        src = comp_map.get(intg.source_component_id)
        tgt = comp_map.get(intg.target_component_id)
        src_name = src.name if src else intg.source_component_id
        tgt_name = tgt.name if tgt else intg.target_component_id

        affected = []
        if src:
            affected.append(src.id)
        if tgt:
            affected.append(tgt.id)

        recommendations.append(
            Recommendation(
                id="",
                category="documentation_gap",
                priority="medium",
                title=(
                    f"Cross-repo integration needs contract documentation: "
                    f"{src_name} -> {tgt_name}"
                ),
                description=(
                    f"Integration between '{src_name}' and '{tgt_name}' crosses "
                    f"repository boundaries. Integration contracts, versioning "
                    f"strategy, and deployment coordination should be documented."
                ),
                rationale=(
                    "Cross-repo integrations are harder to test atomically and "
                    "require explicit contract documentation to prevent "
                    "breaking changes."
                ),
                affected_component_ids=affected,
            )
        )

    # High fan-out/fan-in: components with >5 total integrations
    integration_counts: dict[str, int] = defaultdict(int)
    for intg in integrations:
        integration_counts[intg.source_component_id] += 1
        integration_counts[intg.target_component_id] += 1

    for comp_id, count in integration_counts.items():
        if count <= 5:
            continue

        comp = comp_map.get(comp_id)
        comp_name = comp.name if comp else comp_id

        recommendations.append(
            Recommendation(
                id="",
                category="architecture_improvement",
                priority="medium",
                title=f"High integration complexity: {comp_name}",
                description=(
                    f"Component '{comp_name}' participates in {count} "
                    f"integrations. Consider introducing a facade or gateway "
                    f"pattern to reduce coupling."
                ),
                rationale=(
                    f"Components with many integration points (>{5}) become "
                    f"change hotspots and increase the blast radius of failures."
                ),
                affected_component_ids=[comp_id],
            )
        )

    # Synchronous chains of depth >= 3
    sync_chains = _find_sync_chains(integrations)
    seen_chain_keys: set[str] = set()

    for chain in sync_chains:
        if len(chain) < 3:
            continue

        chain_key = "->".join(chain)
        if chain_key in seen_chain_keys:
            continue
        seen_chain_keys.add(chain_key)

        names = []
        for cid in chain:
            comp = comp_map.get(cid)
            names.append(comp.name if comp else cid)

        chain_str = " -> ".join(names)

        recommendations.append(
            Recommendation(
                id="",
                category="human_review",
                priority="high",
                title=f"Synchronous call chain ({len(chain)} hops)",
                description=(
                    f"A chain of {len(chain)} synchronous integrations creates "
                    f"cumulative latency and resilience risk: {chain_str}. "
                    f"Review for timeout cascades and failure propagation."
                ),
                rationale=(
                    "Deep synchronous chains multiply latency and create "
                    "cascading failure risks. Each hop adds a failure point "
                    "and increases end-to-end response time."
                ),
                affected_component_ids=list(chain),
            )
        )

    return recommendations


def _find_sync_chains(
    integrations: list[IntegrationPoint],
) -> list[list[str]]:
    """Find synchronous call chains via DFS.

    Only follows integrations with style in _SYNC_STYLES.
    Returns chains sorted longest-first.
    """
    adj: dict[str, list[str]] = defaultdict(list)
    for intg in integrations:
        if intg.style in _SYNC_STYLES:
            adj[intg.source_component_id].append(intg.target_component_id)

    if not adj:
        return []

    all_nodes: set[str] = set()
    for src, targets in adj.items():
        all_nodes.add(src)
        all_nodes.update(targets)

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

    chains.sort(key=lambda c: len(c), reverse=True)
    return chains


# ---------------------------------------------------------------------------
# 4. Domain model recommendations
# ---------------------------------------------------------------------------


def recommend_from_domain(
    domain: DomainModelSection | None,
) -> list[Recommendation]:
    """Flag domain model issues needing review.

    - Entities with no relationships -> human_review (orphaned entity)
    - Bounded contexts with no upstream/downstream -> documentation_gap
    - Skips if domain is None
    """
    if domain is None:
        return []

    recommendations: list[Recommendation] = []

    # Orphaned entities (no relationships)
    for entity in domain.entities:
        if not entity.relationships:
            recommendations.append(
                Recommendation(
                    id="",
                    category="human_review",
                    priority="medium",
                    title=f"Orphaned domain entity: {entity.name}",
                    description=(
                        f"Domain entity '{entity.name}' has no relationships "
                        f"to other entities. This may indicate a missing "
                        f"relationship or an entity that should be removed."
                    ),
                    rationale=(
                        "Entities without relationships are either incompletely "
                        "modeled or represent dead concepts that add complexity "
                        "without value."
                    ),
                    affected_component_ids=[],
                )
            )

    # Isolated bounded contexts
    for ctx in domain.bounded_contexts:
        if not ctx.upstream_contexts and not ctx.downstream_contexts:
            recommendations.append(
                Recommendation(
                    id="",
                    category="documentation_gap",
                    priority="medium",
                    title=f"Isolated bounded context: {ctx.name}",
                    description=(
                        f"Bounded context '{ctx.name}' has no upstream or "
                        f"downstream contexts documented. Context relationships "
                        f"should be mapped to understand data flow and "
                        f"dependencies."
                    ),
                    rationale=(
                        "Bounded contexts without documented relationships "
                        "suggest incomplete context mapping, which can lead "
                        "to unexpected coupling or integration issues."
                    ),
                    affected_component_ids=list(ctx.component_ids),
                )
            )

    return recommendations


# ---------------------------------------------------------------------------
# 5. Maturity recommendations
# ---------------------------------------------------------------------------


def recommend_from_maturity(
    market: MarketAnalysisSection | None,
) -> list[Recommendation]:
    """Flag low maturity assessments.

    - Overall maturity "initial" or "developing" -> architecture_improvement
    - Skips if market is None
    """
    if market is None:
        return []

    recommendations: list[Recommendation] = []

    if market.overall_maturity in ("initial", "developing"):
        priority: Literal["critical", "high", "medium", "low"] = (
            "high" if market.overall_maturity == "initial" else "medium"
        )
        recommendations.append(
            Recommendation(
                id="",
                category="architecture_improvement",
                priority=priority,
                title=(f"Low architecture maturity: {market.overall_maturity}"),
                description=(
                    f"The overall architecture maturity is assessed as "
                    f"'{market.overall_maturity}'. "
                    f"{market.maturity_rationale or 'No rationale provided.'}"
                ),
                rationale=(
                    "Low maturity levels indicate the architecture may not "
                    "be well-defined or consistently applied, increasing "
                    "risk of technical debt and inconsistency."
                ),
                affected_component_ids=[],
            )
        )

    return recommendations


# ---------------------------------------------------------------------------
# 6. Top-level orchestrator
# ---------------------------------------------------------------------------


def generate_recommendations(
    components: list[Component],
    integrations: list[IntegrationPoint],
    test_coverage: list[ComponentTestCoverage],
    risks: list[RiskFinding],
    domain: DomainModelSection | None = None,
    market: MarketAnalysisSection | None = None,
) -> list[Recommendation]:
    """Generate all recommendations, deduplicate, sort, and assign IDs.

    Calls all sub-functions, merges results, deduplicates by
    (affected_component_ids, category) keeping higher priority,
    sorts by priority (critical -> low), and assigns sequential IDs
    (REC-001, REC-002, ...).

    Parameters
    ----------
    components:
        Discovered architectural components.
    integrations:
        Discovered integration points between components.
    test_coverage:
        Test coverage data for components.
    risks:
        Risk findings from risk analysis.
    domain:
        Optional domain model section.
    market:
        Optional market analysis section.

    Returns
    -------
    list[Recommendation]
        Deduplicated and sorted recommendations with sequential IDs.
    """
    logger.info(
        "Generating recommendations: %d components, %d integrations, "
        "%d coverage entries, %d risks",
        len(components),
        len(integrations),
        len(test_coverage),
        len(risks),
    )

    all_recs: list[Recommendation] = []

    all_recs.extend(recommend_from_coverage_gaps(test_coverage, components))
    all_recs.extend(recommend_from_risks(risks, components))
    all_recs.extend(recommend_from_integrations(integrations, components))
    all_recs.extend(recommend_from_domain(domain))
    all_recs.extend(recommend_from_maturity(market))

    # Deduplicate by (frozenset of affected_component_ids, category)
    # Keep the one with higher priority (lower _PRIORITY_ORDER value)
    dedup_map: dict[tuple[frozenset[str], str], Recommendation] = {}

    for rec in all_recs:
        key = (frozenset(rec.affected_component_ids), rec.category)
        existing = dedup_map.get(key)
        if existing is None:
            dedup_map[key] = rec
        else:
            # Keep the higher-priority recommendation
            existing_order = _PRIORITY_ORDER.get(existing.priority, 99)
            new_order = _PRIORITY_ORDER.get(rec.priority, 99)
            if new_order < existing_order:
                dedup_map[key] = rec

    deduped = list(dedup_map.values())

    # Sort by priority (critical first)
    deduped.sort(key=lambda r: _PRIORITY_ORDER.get(r.priority, 99))

    # Assign sequential IDs
    result: list[Recommendation] = []
    for i, rec in enumerate(deduped, start=1):
        result.append(rec.model_copy(update={"id": f"REC-{i:03d}"}))

    logger.info("Recommendation generation complete: %d recommendations", len(result))
    return result


__all__ = [
    "generate_recommendations",
    "recommend_from_coverage_gaps",
    "recommend_from_domain",
    "recommend_from_integrations",
    "recommend_from_maturity",
    "recommend_from_risks",
]
