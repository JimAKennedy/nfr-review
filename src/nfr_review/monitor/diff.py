# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate nfr-review Findings from baseline vs. observed interaction diffs."""

from __future__ import annotations

from nfr_review.models import Finding, Severity
from nfr_review.monitor.baseline import InteractionBaseline, diff_baselines
from nfr_review.monitor.fingerprint import InteractionFingerprint

RULE_ID_NOVEL = "mon-novel-interaction"
RULE_ID_DISAPPEARED = "mon-disappeared-interaction"
_COLLECTOR_NAME = "monitor-baseline-diff"
_COLLECTOR_VERSION = "0.1.0"


def _severity_for_novel(fp: InteractionFingerprint) -> Severity:
    if fp.protocol in ("http", "grpc", "rpc"):
        return "high"
    if fp.protocol in ("db", "messaging"):
        return "medium"
    return "low"


def _describe_fingerprint(fp: InteractionFingerprint) -> str:
    return (
        f"{fp.caller_service} → {fp.callee_service} "
        f"[{fp.operation}] ({fp.protocol}, kind={fp.span_kind})"
    )


def generate_diff_findings(
    baseline: InteractionBaseline,
    observed: set[InteractionFingerprint],
) -> list[Finding]:
    """Compare observed fingerprints against baseline and emit Findings."""
    novel, disappeared = diff_baselines(baseline, observed)
    findings: list[Finding] = []

    for fp in sorted(novel, key=lambda f: f.fingerprint_hash):
        sev = _severity_for_novel(fp)
        findings.append(
            Finding(
                rule_id=RULE_ID_NOVEL,
                rag="red" if sev in ("high", "critical") else "amber",
                severity=sev,
                summary=f"Novel interaction not seen in UAT: {_describe_fingerprint(fp)}",
                recommendation=(
                    "Verify this interaction is expected. If it is a new feature, "
                    "re-run UAT with the updated code and regenerate the baseline."
                ),
                evidence_locator=f"fingerprint:{fp.fingerprint_hash}",
                collector_name=_COLLECTOR_NAME,
                collector_version=_COLLECTOR_VERSION,
                confidence=0.9,
                pattern_tag=f"novel-{fp.protocol}",
            )
        )

    for fp in sorted(disappeared, key=lambda f: f.fingerprint_hash):
        findings.append(
            Finding(
                rule_id=RULE_ID_DISAPPEARED,
                rag="green",
                severity="info",
                summary=f"Interaction no longer observed: {_describe_fingerprint(fp)}",
                recommendation=(
                    "This interaction was in the UAT baseline but not in the current traces. "
                    "This may indicate a removed feature or a gap in trace coverage."
                ),
                evidence_locator=f"fingerprint:{fp.fingerprint_hash}",
                collector_name=_COLLECTOR_NAME,
                collector_version=_COLLECTOR_VERSION,
                confidence=0.8,
                pattern_tag="disappeared",
            )
        )

    return findings


__all__ = [
    "RULE_ID_DISAPPEARED",
    "RULE_ID_NOVEL",
    "generate_diff_findings",
]
