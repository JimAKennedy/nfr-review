# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""dyn-adr-drift: observed runtime topology vs ADR-declared architecture."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.output.topology import build_topology_graph
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import make_green_finding

_ARROW_RE = re.compile(r"([\w][\w-]*)\s*(?:→|->|-->)\s*([\w][\w-]*)")


def _extract_declared_edges(evidence: list[Evidence]) -> set[tuple[str, str]]:
    """Extract service relationship declarations from ADR body text.

    Looks for arrow patterns like ``service-a → service-b`` or
    ``service-a -> service-b`` in accepted ADR documents.
    """
    edges: set[tuple[str, str]] = set()
    for ev in evidence:
        if ev.collector_name != "adr" or ev.kind != "adr-document":
            continue
        status = (
            ev.payload.status
            if hasattr(ev.payload, "get")
            else getattr(ev.payload, "status", "")
        )
        if status and status not in ("accepted", "proposed"):
            continue
        body = (
            ev.payload.body_text
            if hasattr(ev.payload, "get")
            else getattr(ev.payload, "body_text", "")
        )
        if not body:
            continue
        for match in _ARROW_RE.finditer(body):
            caller = match.group(1).strip().lower()
            callee = match.group(2).strip().lower()
            if caller and callee:
                edges.add((caller, callee))
    return edges


def _normalise_name(name: str) -> str:
    return name.strip().lower()


class DynAdrDriftRule:
    """Cross-reference observed runtime topology against ADR-declared architecture."""

    id = "dyn-adr-drift"
    band: Band = 3
    required_collectors: list[str] = ["otel-trace"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        graph = build_topology_graph(evidence)

        if len(graph.services) <= 1:
            svc = next(iter(graph.services)) if graph.services else "none"
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "dyn-adr-drift-single-service",
                        summary=(
                            f"Single-service topology observed ({svc}). "
                            "ADR drift detection requires multi-service traces."
                        ),
                        recommendation=(
                            "Provide traces from multiple services to enable "
                            "topology drift detection."
                        ),
                        confidence=0.7,
                        evidence_locator="otel-trace",
                        collector_name="otel-trace",
                        collector_version="0.1.0",
                    )
                ],
            )

        declared = _extract_declared_edges(evidence)
        observed: set[tuple[str, str]] = {
            (_normalise_name(k[0]), _normalise_name(k[1])) for k in graph.edges
        }

        findings: list[Finding] = []

        if not declared:
            findings.append(
                make_green_finding(
                    self.id,
                    "dyn-adr-drift-no-declarations",
                    summary=(
                        f"Observed {len(graph.services)} services with "
                        f"{len(observed)} communication edge(s), but no ADR "
                        "topology declarations found to compare against."
                    ),
                    recommendation=(
                        "Add service topology declarations to an ADR using "
                        "arrow notation (e.g. 'service-a → service-b') so "
                        "drift detection can compare declared vs observed."
                    ),
                    confidence=0.6,
                    evidence_locator="otel-trace",
                    collector_name="otel-trace",
                    collector_version="0.1.0",
                )
            )
            return RuleResult(rule_id=self.id, findings=findings)

        undocumented = observed - declared
        for caller, callee in sorted(undocumented):
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="red",
                    severity="high",
                    summary=(
                        f"Undocumented coupling: {caller} → {callee} observed "
                        "at runtime but not declared in any ADR."
                    ),
                    recommendation=(
                        f"Document the {caller} → {callee} relationship in an "
                        "ADR, or investigate whether this coupling is intended."
                    ),
                    evidence_locator="otel-trace",
                    collector_name="otel-trace",
                    collector_version="0.1.0",
                    confidence=0.85,
                    pattern_tag=f"dyn-adr-drift-undocumented:{caller}->{callee}",
                )
            )

        unobserved = declared - observed
        for caller, callee in sorted(unobserved):
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"Unobserved declared relationship: {caller} → {callee} "
                        "declared in ADR but not observed in traces."
                    ),
                    recommendation=(
                        f"The {caller} → {callee} relationship is declared in "
                        "an ADR but was not observed in the provided traces. "
                        "This may indicate dead architecture or a test coverage gap."
                    ),
                    evidence_locator="adr",
                    collector_name="adr",
                    collector_version="0.1.0",
                    confidence=0.7,
                    pattern_tag=f"dyn-adr-drift-unobserved:{caller}->{callee}",
                )
            )

        matched = observed & declared
        if matched and not undocumented and not unobserved:
            findings.append(
                make_green_finding(
                    self.id,
                    "dyn-adr-drift-match",
                    summary=(
                        f"Runtime topology matches ADR declarations: "
                        f"{len(matched)} edge(s) confirmed."
                    ),
                    confidence=0.9,
                    evidence_locator="otel-trace",
                    collector_name="otel-trace",
                    collector_version="0.1.0",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "dyn-adr-drift" not in rule_registry:
        rule_registry.register("dyn-adr-drift", DynAdrDriftRule())


_register()

__all__ = ["DynAdrDriftRule"]
