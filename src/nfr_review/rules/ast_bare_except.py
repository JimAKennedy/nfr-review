# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: bare-except-catch-all — cross-language detection of bare/broad exception catches.

Uses D021 ANY-match semantics: required_collectors=[] and required_tech=[]
so the engine always runs it. The rule filters evidence internally by
iterating LanguageRuleConfig entries.

Severity split:
  - Bare/untyped catches (Python ``except:``) → amber / medium
  - Named broad types (Exception, Throwable, BaseException) → red / high
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules._cross_language import ALL_LANGUAGES
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_BROAD_TYPES: dict[str, frozenset[str]] = {
    "java": frozenset({"Exception", "Throwable"}),
    "python": frozenset({"Exception", "BaseException"}),
    "go": frozenset(),
    "csharp": frozenset({"Exception", "SystemException"}),
    "nodejs": frozenset(),
}


class BareExceptCatchAllRule:
    """Flag bare except blocks and broad exception catch-alls across languages."""

    id = "bare-except-catch-all"
    band: Band = 1
    required_collectors: list[str] = []
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        findings: list[Finding] = []
        any_evidence = False
        first_ev: Evidence | None = None

        for lang in ALL_LANGUAGES:
            lang_ev = filter_evidence(evidence, lang.collector_name, lang.evidence_kind)
            if not lang_ev:
                continue
            any_evidence = True
            if first_ev is None:
                first_ev = lang_ev[0]

            broad = _BROAD_TYPES.get(lang.language, frozenset())

            for ev in lang_ev:
                file_path = ev.payload.file_path
                for block in ev.payload.catch_blocks:
                    caught = block["caught_type"]
                    if block["rethrows"]:
                        continue

                    if caught == "":
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="amber",
                                severity="medium",
                                summary="Bare except catch-all",
                                recommendation=(
                                    "Catch specific exception types to avoid masking"
                                    " unexpected errors."
                                ),
                                evidence_locator=f"{file_path}:{block['line']}",
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.9,
                                pattern_tag="bare-except-catch-all",
                            )
                        )
                    elif caught in broad and not block.get("has_logging", False):
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="red",
                                severity="high",
                                summary=f"Broad catch({caught}) without rethrow",
                                recommendation=(
                                    "Catch specific exception types or rethrow to"
                                    " preserve stack trace visibility."
                                ),
                                evidence_locator=f"{file_path}:{block['line']}",
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.85,
                                pattern_tag="bare-except-catch-all",
                            )
                        )

        if not any_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no AST evidence available",
            )

        if not findings:
            assert first_ev is not None
            findings.append(
                make_green_finding(
                    self.id,
                    "bare-except-catch-all",
                    first_ev,
                    summary="No bare or broad exception catch-alls detected.",
                    confidence=0.9,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "bare-except-catch-all" not in rule_registry:
        rule_registry.register("bare-except-catch-all", BareExceptCatchAllRule())


_register()

__all__ = ["BareExceptCatchAllRule"]
