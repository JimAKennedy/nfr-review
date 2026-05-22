# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: adr-gap — cross-references LLM-derived ADR candidates against
existing ADR documents to flag undocumented architectural decisions.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class AdrGapRule:
    """Compare derived ADR candidates against existing ADR evidence to
    surface undocumented decisions and superseded-but-still-used contradictions.
    """

    id = "adr-gap"
    band: Band = 2
    required_collectors: list[str] = ["adr-derive", "adr"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        derived = [e for e in evidence if e.kind == "adr-derived"]
        existing = [e for e in evidence if e.kind == "adr-document"]

        if not derived:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no derived ADR evidence available",
            )

        existing_titles = set()
        superseded_titles = set()
        for ev in existing:
            title = (ev.payload.get("title") or "").lower().strip()
            if title:
                existing_titles.add(title)
            status = ev.payload.get("status", "")
            if status and "superseded" in status.lower():
                superseded_titles.add(title)

        findings: list[Finding] = []

        for ev in derived:
            derived_title = ev.payload.get("title", "")
            category = ev.payload.get("category", "unknown")
            confidence = ev.payload.get("confidence", 0.5)
            rationale = ev.payload.get("rationale", "")

            matched = self._find_match(derived_title, existing_titles)

            if matched is None:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Undocumented decision: '{derived_title}'"
                            f" ({category}, confidence={confidence:.1f})."
                        ),
                        recommendation=(
                            f"Consider creating an ADR for this decision."
                            f" Rationale: {rationale}"
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=confidence,
                        pattern_tag="adr-gap-undocumented",
                    )
                )
            elif matched in superseded_titles:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Superseded ADR may still be active: '{derived_title}'"
                            f" — evidence suggests this decision is still in use."
                        ),
                        recommendation=(
                            "Review the superseded ADR and update its status if"
                            " the decision is still active, or ensure the"
                            " replacement decision is properly documented."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=confidence * 0.8,
                        pattern_tag="adr-gap-superseded-active",
                    )
                )

        if not findings:
            first = derived[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        f"All {len(derived)} derived architectural decisions"
                        f" have matching ADR documents."
                    ),
                    recommendation="No action required.",
                    evidence_locator="adr-derive-summary",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.7,
                    pattern_tag="adr-gap-ok",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)

    @staticmethod
    def _find_match(derived_title: str, existing_titles: set[str]) -> str | None:
        """Fuzzy-match a derived title against existing ADR titles.

        Returns the matched existing title or None.
        """
        derived_lower = derived_title.lower().strip()
        if not derived_lower:
            return None

        for existing in existing_titles:
            if existing == derived_lower:
                return existing
            derived_words = set(derived_lower.split())
            existing_words = set(existing.split())
            if len(derived_words) > 2 and len(existing_words) > 2:
                overlap = derived_words & existing_words
                min_len = min(len(derived_words), len(existing_words))
                if len(overlap) / min_len >= 0.6:
                    return existing

        return None


def _register() -> None:
    if "adr-gap" not in rule_registry:
        rule_registry.register("adr-gap", AdrGapRule())


_register()

__all__ = ["AdrGapRule"]
