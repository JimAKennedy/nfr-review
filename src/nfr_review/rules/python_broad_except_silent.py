# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Detects catching Exception/BaseException without logging or re-raising."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult, compute_content_hash
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_BROAD_TYPES = frozenset({"Exception", "BaseException"})


class PythonBroadExceptSilentRule:
    """Flag catch blocks that silently swallow Exception/BaseException."""

    id = "python-broad-except-silent"
    band: Band = 1
    required_collectors: list[str] = ["python-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        py_evidence = filter_evidence(evidence, "python-ast", "python-ast-file")
        if not py_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no python-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in py_evidence:
            file_path = ev.payload.file_path
            for block in ev.payload.catch_blocks:
                if (
                    block["caught_type"] in _BROAD_TYPES
                    and not block["rethrows"]
                    and not block["has_logging"]
                ):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="high",
                            summary=(
                                f"Silent catch({block['caught_type']})"
                                " without logging or rethrow"
                            ),
                            recommendation=(
                                "At minimum log the exception; prefer re-raising"
                                " or catching specific exception types."
                            ),
                            evidence_locator=f"{file_path}:{block['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="broad-except-silent",
                            content_hash=compute_content_hash(
                                block.get("body_text", block["caught_type"])
                            ),
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "broad-except-silent",
                    py_evidence[0],
                    summary="No silently swallowed broad exceptions detected.",
                    confidence=0.9,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "python-broad-except-silent" not in rule_registry:
        rule_registry.register("python-broad-except-silent", PythonBroadExceptSilentRule())


_register()

__all__ = ["PythonBroadExceptSilentRule"]
