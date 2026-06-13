# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for rule boilerplate — green findings and evidence filtering."""

from __future__ import annotations

from nfr_review.models import Evidence, Finding


def make_green_finding(
    rule_id: str,
    pattern_tag: str,
    evidence_ref: Evidence | None = None,
    *,
    summary: str | None = None,
    collector_name: str = "",
    collector_version: str = "",
    confidence: float = 0.85,
    recommendation: str = "No action required.",
    evidence_locator: str = "project-wide",
) -> Finding:
    """Build a green/info Finding with standard defaults.

    Pass *evidence_ref* to pull collector_name and collector_version from
    an Evidence object, or pass them explicitly via keyword arguments.
    """
    if evidence_ref is not None:
        collector_name = collector_name or evidence_ref.collector_name
        collector_version = collector_version or evidence_ref.collector_version
    return Finding(
        rule_id=rule_id,
        rag="green",
        severity="info",
        summary=summary or f"No {pattern_tag} issues detected.",
        recommendation=recommendation,
        evidence_locator=evidence_locator,
        collector_name=collector_name,
        collector_version=collector_version,
        confidence=confidence,
        pattern_tag=pattern_tag,
    )


def filter_evidence(
    evidence: list[Evidence],
    collector_name: str,
    kind: str | None = None,
) -> list[Evidence]:
    """Filter evidence by collector_name and optionally by kind."""
    if kind is None:
        return [e for e in evidence if e.collector_name == collector_name]
    return [e for e in evidence if e.collector_name == collector_name and e.kind == kind]
