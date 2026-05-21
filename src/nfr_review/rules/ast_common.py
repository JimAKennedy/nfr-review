# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared infrastructure for cross-language AST rules (D021).

GenericASTRule sets required_collectors=[] and required_tech=[] so the engine
always runs it.  Internally it uses ANY-match semantics: iterate LanguageRuleConfig
entries, filter evidence by collector_name + kind, call the subclass's check_match()
for each hit, and aggregate findings.  If no evidence matches any config the rule
reports skipped.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band


@dataclass(frozen=True, slots=True)
class LanguageRuleConfig:
    """Maps a language to its collector/evidence identifiers."""

    language: str
    collector_name: str
    evidence_kind: str
    tech_key: str


class GenericASTRule(ABC):
    """Base class for cross-language AST rules.

    Subclasses set ``id``, ``pattern_tag``, ``language_configs``, and implement
    ``check_match()``.  The engine sees empty ``required_collectors`` /
    ``required_tech`` and always invokes ``evaluate()``.
    """

    id: str
    band: Band = 2
    required_collectors: list[str] = []
    required_tech: list[str] = []
    language_configs: list[LanguageRuleConfig]
    pattern_tag: str

    @abstractmethod
    def check_match(self, evidence: Evidence, config: LanguageRuleConfig) -> list[Finding]:
        """Return findings for a single Evidence item under *config*.

        Called once per matching evidence record.  Return an empty list
        when the evidence is clean.
        """
        ...

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        matched_any = False
        findings: list[Finding] = []

        for cfg in self.language_configs:
            lang_evidence = [
                e
                for e in evidence
                if e.collector_name == cfg.collector_name and e.kind == cfg.evidence_kind
            ]
            if not lang_evidence:
                continue
            matched_any = True
            for ev in lang_evidence:
                findings.extend(self.check_match(ev, cfg))

        if not matched_any:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no matching AST evidence for any configured language",
            )

        if not findings:
            first_cfg = self.language_configs[0]
            first_ev = next(
                (
                    e
                    for e in evidence
                    if e.collector_name == first_cfg.collector_name
                    and e.kind == first_cfg.evidence_kind
                ),
                None,
            )
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=f"No {self.pattern_tag} issues detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=first_ev.collector_name
                    if first_ev
                    else first_cfg.collector_name,
                    collector_version=first_ev.collector_version if first_ev else "0.0.0",
                    confidence=0.85,
                    pattern_tag=self.pattern_tag,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["GenericASTRule", "LanguageRuleConfig"]
