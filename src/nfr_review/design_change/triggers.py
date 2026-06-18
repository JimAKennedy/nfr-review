# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from nfr_review.design_change.diff import CategoryDiff, NumericDelta, SetDelta
from nfr_review.models import Finding, Severity

COLLECTOR_NAME = "design-change"
COLLECTOR_VERSION = "1.0.0"
RULE_ID = "design-change-trigger"


def _numeric_summary(cat: str, nd: NumericDelta) -> str:
    pct = f" ({nd.pct_change:+.1f}%)" if nd.pct_change is not None else " (new)"
    return (
        f"{cat}/{nd.name} changed: {nd.old_value:.0f} → {nd.new_value:.0f}"
        f" (delta {nd.delta:+.0f}){pct}"
    )


def _numeric_recommendation(cat: str, nd: NumericDelta) -> str:
    tag = f"design_change:{nd.name}"
    return f"Review the structural change flagged by {tag} before it drifts further."


def _set_summary(cat: str, sd: SetDelta) -> str:
    parts: list[str] = [f"{cat}/{sd.name}:"]
    if sd.added:
        parts.append(f"added {', '.join(sd.added)}")
    if sd.removed:
        parts.append(f"removed {', '.join(sd.removed)}")
    return " ".join(parts)


def _set_recommendation(cat: str, sd: SetDelta) -> str:
    tag = f"design_change:{sd.name}"
    return f"Review the structural change flagged by {tag} before it drifts further."


def _severity_from_pct(nd: NumericDelta) -> Severity:
    abs_pct = abs(nd.pct_change) if nd.pct_change is not None else 100.0
    if abs_pct >= 50.0:
        return "high"
    if abs_pct >= 20.0:
        return "medium"
    return "low"


def _severity_from_set(sd: SetDelta) -> Severity:
    total = len(sd.added) + len(sd.removed)
    if total >= 5:
        return "high"
    if total >= 3:
        return "medium"
    return "low"


def findings_from_diffs(
    diffs: dict[str, CategoryDiff],
    baseline_path: str = "",
) -> list[Finding]:
    findings: list[Finding] = []

    for cat_name in sorted(diffs):
        cat_diff = diffs[cat_name]

        for nd in cat_diff.numeric_deltas:
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    rag="amber",
                    severity=_severity_from_pct(nd),
                    summary=_numeric_summary(cat_name, nd),
                    recommendation=_numeric_recommendation(cat_name, nd),
                    evidence_locator=baseline_path,
                    collector_name=COLLECTOR_NAME,
                    collector_version=COLLECTOR_VERSION,
                    confidence=1.0,
                    pattern_tag=f"design_change:{nd.name}",
                )
            )

        for sd in cat_diff.set_deltas:
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    rag="amber",
                    severity=_severity_from_set(sd),
                    summary=_set_summary(cat_name, sd),
                    recommendation=_set_recommendation(cat_name, sd),
                    evidence_locator=baseline_path,
                    collector_name=COLLECTOR_NAME,
                    collector_version=COLLECTOR_VERSION,
                    confidence=1.0,
                    pattern_tag=f"design_change:{sd.name}",
                )
            )

    return findings
