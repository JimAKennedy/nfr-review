"""Rule: architectural-drift-from-adr — Band 2 LLM-only ADR drift rule."""

from __future__ import annotations

import json
import logging
from typing import Any

from nfr_review.llm_client import ClaudeClient, LlmUnavailableError, serialize_evidence_bundle
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

logger = logging.getLogger(__name__)

_LLM_PROMPT = (
    "You are a software architecture reviewer. You are given two inputs:\n"
    "1. A set of Architecture Decision Records (ADRs) describing intended decisions.\n"
    "2. A summary of the Java codebase structure "
    "(classes, annotations, imports, packages).\n\n"
    "Identify any architectural decisions in the ADRs that appear to be violated or "
    "drifted from in the actual code. Consider:\n"
    "- Technology choices (frameworks, libraries) specified in ADRs vs. actual imports\n"
    "- Structural patterns (layering, packaging conventions) vs. actual package structure\n"
    "- Annotation usage patterns vs. what ADRs prescribe\n\n"
    "Respond with a JSON object:\n"
    '{"drifts": [{"adr_title": "<title>", "violation": "<description>", '
    '"severity": "high"|"medium"|"low"}], "summary": "<one-line overall assessment>"}\n\n'
    "If no drift is found, return: "
    '{"drifts": [], "summary": "No architectural drift detected."}'
)


class ArchitecturalDriftFromAdrRule:
    id = "architectural-drift-from-adr"
    band: Band = 2
    required_collectors: list[str] = ["adr", "java-ast"]

    def __init__(self, llm_client: ClaudeClient | None = None) -> None:
        self._llm = llm_client if llm_client is not None else ClaudeClient()

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        adr_evidence = [
            e for e in evidence if e.collector_name == "adr" and e.kind == "adr-document"
        ]
        java_evidence = [
            e for e in evidence if e.collector_name == "java-ast" and e.kind == "java-ast-file"
        ]

        if not adr_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ADR evidence found",
            )

        if not java_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no Java AST evidence found",
            )

        bundle = self._build_evidence_bundle(adr_evidence, java_evidence)

        if not self._llm.available:
            logger.warning("ANTHROPIC_API_KEY missing; skipping architectural drift analysis")
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason=(
                    "LLM unavailable — architectural drift analysis requires Claude API"
                ),
            )

        return self._analyze_with_llm(bundle, adr_evidence)

    def _build_evidence_bundle(
        self,
        adr_evidence: list[Evidence],
        java_evidence: list[Evidence],
    ) -> str:
        adr_items: list[dict[str, Any]] = []
        for ev in adr_evidence:
            payload = ev.payload
            if not payload.get("title"):
                continue
            adr_items.append(
                {
                    "title": payload.get("title"),
                    "status": payload.get("status"),
                    "date": payload.get("date"),
                    "file": payload.get("file_path", ev.locator),
                }
            )

        java_items: list[dict[str, Any]] = []
        for ev in java_evidence:
            payload = ev.payload
            classes = payload.get("classes", [])
            java_items.append(
                {
                    "file": payload.get("file_path", ev.locator),
                    "classes": [
                        {
                            "name": c.get("name"),
                            "annotations": c.get("annotations", []),
                        }
                        for c in classes
                    ],
                    "imports": payload.get("imports", []),
                }
            )

        bundle_items: list[dict[str, Any]] = [
            {"section": "adrs", "items": adr_items},
            {"section": "code_structure", "items": java_items},
        ]
        return serialize_evidence_bundle(bundle_items)

    def _analyze_with_llm(
        self,
        bundle: str,
        adr_evidence: list[Evidence],
    ) -> RuleResult:
        try:
            response_text = self._llm.analyze(_LLM_PROMPT, bundle)
            logger.info(
                "LLM architectural drift analysis received (%d chars)",
                len(response_text),
            )
            return self._parse_response(response_text, adr_evidence)
        except LlmUnavailableError:
            logger.warning("LLM unavailable for architectural drift analysis")
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason=(
                    "LLM unavailable — architectural drift analysis requires Claude API"
                ),
            )
        except Exception as exc:
            logger.warning("LLM architectural drift analysis failed: %s", exc)
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason=f"LLM analysis error: {exc}",
            )

    def _parse_response(
        self,
        text: str,
        adr_evidence: list[Evidence],
    ) -> RuleResult:
        first_ev = adr_evidence[0]

        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            parsed = json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.warning("Could not parse LLM drift response; returning skipped")
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="LLM response could not be parsed",
            )

        drifts = parsed.get("drifts", [])
        if not isinstance(drifts, list):
            drifts = []

        if not drifts:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary="No architectural drift detected between ADRs and code.",
                        recommendation="No action required.",
                        evidence_locator="project-wide",
                        collector_name=first_ev.collector_name,
                        collector_version=first_ev.collector_version,
                        confidence=0.75,
                        pattern_tag="adr-drift",
                    )
                ],
            )

        findings: list[Finding] = []
        for drift in drifts:
            if not isinstance(drift, dict):
                continue
            adr_title = drift.get("adr_title", "Unknown ADR")
            violation = drift.get("violation", "Architectural drift detected")
            sev = drift.get("severity", "medium")
            rag = "red" if sev == "high" else "amber"
            severity = "high" if sev == "high" else "medium"

            findings.append(
                Finding(
                    rule_id=self.id,
                    rag=rag,
                    severity=severity,
                    summary=f"Drift from ADR '{adr_title}': {violation}",
                    recommendation=(
                        "Review the ADR decision and either update the code to align "
                        "with the decision or update the ADR to reflect the current approach."
                    ),
                    evidence_locator="project-wide",
                    collector_name=first_ev.collector_name,
                    collector_version=first_ev.collector_version,
                    confidence=0.75,
                    pattern_tag="adr-drift",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "architectural-drift-from-adr" not in rule_registry:
        rule_registry.register("architectural-drift-from-adr", ArchitecturalDriftFromAdrRule())


_register()

__all__ = ["ArchitecturalDriftFromAdrRule"]
