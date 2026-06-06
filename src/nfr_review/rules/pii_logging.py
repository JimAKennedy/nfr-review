# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: pii-in-log-statements — Band 2 regex pre-filter + LLM confirmation for PII in logs."""

from __future__ import annotations

import logging
import re
from typing import Any, cast

from nfr_review.llm_client import (
    LlmUnavailableError,
    create_llm_client,
    extract_json,
    serialize_evidence_bundle,
)
from nfr_review.models import RAG, Evidence, Finding, RuleResult
from nfr_review.protocols import Band, LlmClient
from nfr_review.registry import rule_registry

logger = logging.getLogger(__name__)

PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"(?i)\bemail|e-mail\b")),
    ("credit_card", re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b")),
    ("phone", re.compile(r"(?i)\bphone|phoneNumber|phone_number\b")),
    (
        "secret_variable",
        re.compile(
            r"(?i)\bpassword|secret|token|apiKey|api_key|credential\b",
        ),
    ),
]

_LLM_PROMPT = (
    "You are a security reviewer. For each log statement below, determine whether "
    "it genuinely logs PII (personally identifiable information) at runtime. "
    "Consider variable names, format-string placeholders, and string literals.\n\n"
    "Respond with a JSON array of objects, one per log statement, each with:\n"
    '  {"index": <0-based>, "is_pii": true/false, "reason": "<short explanation>"}\n\n'
    "Only mark is_pii=true if the log statement would expose real PII at runtime "
    "(e.g. SSN values, email addresses, credit card numbers, passwords). "
    "Variable names like 'email' used as keys or format-string placeholders "
    "that clearly reference PII data count as true."
)


class PiiInLogStatementsRule:
    id = "pii-in-log-statements"
    band: Band = 2
    required_collectors: list[str] = ["java-ast"]

    def __init__(self, llm_client: LlmClient | None = None) -> None:
        self._llm = llm_client if llm_client is not None else create_llm_client()

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_evidence = [
            e
            for e in evidence
            if e.collector_name == "java-ast"
            and e.kind == "java-ast-file"
            and e.payload.get("log_statements")
        ]
        if not java_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-ast evidence with log statements",
            )

        regex_hits: list[dict[str, Any]] = []
        for ev in java_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for stmt in ev.payload["log_statements"]:
                matched_patterns: list[str] = []
                for pattern_name, pattern_re in PII_PATTERNS:
                    if pattern_re.search(stmt["arguments_text"]):
                        matched_patterns.append(pattern_name)
                if matched_patterns:
                    regex_hits.append(
                        {
                            "file_path": file_path,
                            "method": stmt["method"],
                            "arguments_text": stmt["arguments_text"],
                            "line": stmt["line"],
                            "matched_patterns": matched_patterns,
                            "collector_name": ev.collector_name,
                            "collector_version": ev.collector_version,
                        }
                    )

        if not regex_hits:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary="No PII patterns detected in log statements.",
                        recommendation="No action required.",
                        evidence_locator="project-wide",
                        collector_name=java_evidence[0].collector_name,
                        collector_version=java_evidence[0].collector_version,
                        confidence=0.85,
                        pattern_tag="pii-logging",
                    )
                ],
            )

        llm_verdicts = self._try_llm_confirmation(regex_hits)
        return self._build_result(regex_hits, llm_verdicts)

    def _try_llm_confirmation(self, hits: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if not self._llm.available:
            logger.warning("LLM not configured; skipping LLM confirmation for PII rule")
            return None

        bundle_items = [
            {
                "index": i,
                "file": h["file_path"],
                "line": h["line"],
                "method": h["method"],
                "arguments": h["arguments_text"],
                "regex_matches": h["matched_patterns"],
            }
            for i, h in enumerate(hits)
        ]
        bundle = serialize_evidence_bundle(bundle_items)

        try:
            response_text = self._llm.analyze(_LLM_PROMPT, bundle)
            logger.info("LLM PII confirmation received (%d chars)", len(response_text))
            return self._parse_llm_response(response_text, len(hits))
        except LlmUnavailableError:
            logger.warning("LLM unavailable for PII confirmation; falling back to regex-only")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM PII confirmation failed: %s", exc)
            return None

    def _parse_llm_response(
        self, text: str, expected_count: int
    ) -> list[dict[str, Any]] | None:
        result = extract_json(text, expect="array")
        if result is None:
            logger.warning("Could not parse LLM PII response; falling back to regex-only")
            return None
        return result if isinstance(result, list) else None

    def _build_result(
        self,
        hits: list[dict[str, Any]],
        llm_verdicts: list[dict[str, Any]] | None,
    ) -> RuleResult:
        verdict_map: dict[int, bool] = {}
        if llm_verdicts:
            for v in llm_verdicts:
                idx = v.get("index")
                is_pii = v.get("is_pii")
                if isinstance(idx, int) and isinstance(is_pii, bool):
                    verdict_map[idx] = is_pii

        findings: list[Finding] = []
        for i, hit in enumerate(hits):
            if llm_verdicts is None:
                confidence = 0.6
                rag = "amber"
                note = " (LLM confirmation unavailable)"
            elif i in verdict_map:
                if verdict_map[i]:
                    confidence = 0.85
                    rag = "red"
                    note = ""
                else:
                    confidence = 0.4
                    rag = "amber"
                    note = " (LLM assessed as likely false positive)"
            else:
                confidence = 0.6
                rag = "amber"
                note = " (LLM confirmation unavailable)"

            findings.append(
                Finding(
                    rule_id=self.id,
                    rag=cast(RAG, rag),
                    severity="high" if rag == "red" else "medium",
                    summary=(
                        f"Potential PII in log statement:"
                        f" matched {', '.join(hit['matched_patterns'])}{note}"
                    ),
                    recommendation=(
                        "Remove or mask PII data before logging. "
                        "Use structured logging with redaction filters."
                    ),
                    evidence_locator=f"{hit['file_path']}:{hit['line']}",
                    collector_name=hit["collector_name"],
                    collector_version=hit["collector_version"],
                    confidence=confidence,
                    pattern_tag="pii-logging",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "pii-in-log-statements" not in rule_registry:
        rule_registry.register("pii-in-log-statements", PiiInLogStatementsRule())


_register()

__all__ = ["PiiInLogStatementsRule"]
